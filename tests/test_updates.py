"""The updater: which releases count, version order, and a verified download."""

import hashlib
import io
import json
import threading
import urllib.error

import pytest

import updates
from version import GITHUB_REPO, __version__

REAL_CHECK = updates.check  # conftest replaces updates.check for the UI tests


def release_json(tag="orbida-v1.2.0", assets=(), **extra):
    return {"tag_name": tag, "html_url": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}",
            "body": "**New**\n- Faster", "draft": False, "prerelease": False,
            "assets": [{"name": n, "browser_download_url": f"https://dl/{n}"} for n in assets], **extra}


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def opener_for(files):
    """An opener serving ``files`` (URL -> bytes or exception) and recording requests."""
    calls = []

    def opener(url, accept="application/octet-stream"):
        calls.append(url)
        value = files[url]
        if isinstance(value, Exception):
            raise value
        return Response(value)
    opener.calls = calls
    return opener


@pytest.mark.parametrize("tag, version", [
    ("orbida-v1.0.0", "1.0.0"), ("orbida-v2.10.3", "2.10.3"),
    ("v1.0.2", None), ("android-preview-57", None), ("orbida-v1.0", None), ("orbida-v1.0.0-beta", None), (None, None),
])
def test_only_orbida_tags_carry_a_version(tag, version):
    assert updates.version_from_tag(tag) == version


def test_versions_compare_as_numbers():
    assert updates.is_newer("1.0.10", "1.0.9")
    assert updates.is_newer("2.0.0", "1.99.99")
    assert not updates.is_newer("1.0.0", "1.0.0")
    assert not updates.is_newer("0.9.0", "1.0.0")
    assert not updates.is_newer("garbage", "1.0.0")


def test_release_json_is_read():
    release = updates.parse_release(release_json(assets=["Orbida-Setup-1.2.0.exe", "SHA256SUMS.txt"]))
    assert release.version == "1.2.0"
    assert release.asset_url("Orbida-Setup-1.2.0.exe") == "https://dl/Orbida-Setup-1.2.0.exe"
    assert release.page.endswith("/releases/tag/orbida-v1.2.0")


@pytest.mark.parametrize("data", [
    release_json(tag="v1.0.2"),                       # an old UniversalDownloader release
    release_json(tag="android-preview-57"),
    release_json(prerelease=True),
    release_json(draft=True),
    "not a dict",
])
def test_other_releases_are_ignored(data):
    assert updates.parse_release(data) is None


def test_check_reports_only_a_newer_release():
    newer = json.dumps(release_json(tag="orbida-v99.0.0")).encode()
    same = json.dumps(release_json(tag=f"orbida-v{__version__}")).encode()
    assert REAL_CHECK(opener=opener_for({updates.LATEST_URL: newer})).version == "99.0.0"
    assert REAL_CHECK(opener=opener_for({updates.LATEST_URL: same})) is None


def test_no_release_yet_is_not_an_error():
    missing = urllib.error.HTTPError(updates.LATEST_URL, 404, "Not Found", {}, None)
    assert REAL_CHECK(opener=opener_for({updates.LATEST_URL: missing})) is None


def test_network_problems_raise_update_error():
    with pytest.raises(updates.UpdateError):
        REAL_CHECK(opener=opener_for({updates.LATEST_URL: OSError("offline")}))


def test_https_is_verified():
    assert updates._context().verify_mode.name == "CERT_REQUIRED"
    assert updates.LATEST_URL.startswith("https://api.github.com/")


def test_sums_are_parsed():
    digest = "a" * 64
    text = f"{digest}  Orbida-Setup-1.2.0.exe\n{'B' * 64} *Orbida-1.2.0.apk\nnot a line\n"
    assert updates.parse_sums(text) == {"Orbida-Setup-1.2.0.exe": digest, "Orbida-1.2.0.apk": "b" * 64}


def make_release(data, listed=None):
    name = updates.installer_name("1.2.0")
    digest = hashlib.sha256(data).hexdigest() if listed is None else listed
    release = updates.parse_release(release_json(assets=[name, "SHA256SUMS.txt"]))
    files = {f"https://dl/{name}": data, "https://dl/SHA256SUMS.txt": f"{digest}  {name}\n".encode()}
    return release, files


def test_installer_is_downloaded_and_verified(tmp_path):
    data = b"MZ" + b"x" * 700_000
    release, files = make_release(data)
    seen = []
    path = updates.download_installer(release, str(tmp_path), progress=lambda d, t: seen.append((d, t)),
                                      opener=opener_for(files))
    assert path == str(tmp_path / "Orbida-Setup-1.2.0.exe")
    assert open(path, "rb").read() == data
    assert seen[-1] == (len(data), len(data))
    assert list(tmp_path.iterdir()) == [tmp_path / "Orbida-Setup-1.2.0.exe"]


def test_a_changed_installer_is_refused_and_removed(tmp_path):
    release, files = make_release(b"MZ tampered", listed="0" * 64)
    with pytest.raises(updates.UpdateError, match="checksum"):
        updates.download_installer(release, str(tmp_path), opener=opener_for(files))
    assert list(tmp_path.iterdir()) == []


def test_a_release_without_checksums_is_refused(tmp_path):
    release = updates.parse_release(release_json(assets=["Orbida-Setup-1.2.0.exe"]))
    with pytest.raises(updates.UpdateError, match="SHA256SUMS"):
        updates.download_installer(release, str(tmp_path), opener=opener_for({}))


def test_a_release_without_the_installer_is_refused(tmp_path):
    release = updates.parse_release(release_json(assets=["SHA256SUMS.txt", "Orbida-1.2.0.apk"]))
    with pytest.raises(updates.UpdateError, match="no Orbida-Setup-1.2.0.exe"):
        updates.download_installer(release, str(tmp_path), opener=opener_for({}))


def test_cancel_stops_the_download(tmp_path):
    release, files = make_release(b"x" * 600_000)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(updates.UpdateError, match="Cancelled"):
        updates.download_installer(release, str(tmp_path), cancel_event=cancel, opener=opener_for(files))
    assert list(tmp_path.iterdir()) == []


def test_installer_runs_silently_and_restarts_the_app():
    assert updates.installer_command("C:\\t\\Orbida-Setup-1.2.0.exe") == [
        "C:\\t\\Orbida-Setup-1.2.0.exe", "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"]


def test_notes_are_shortened_for_the_dialog():
    notes = "## What's new\n**Faster** downloads, see [the page](https://x)\n\n\n\n- `mp3`\n" + "line\n" * 500
    text = updates.notes_summary(notes, limit=200)
    assert text.startswith("What's new\nFaster downloads, see the page\n\n- mp3")
    assert len(text) <= 202 and text.endswith("…")
