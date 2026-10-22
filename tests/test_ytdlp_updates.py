"""yt-dlp updates without a new Orbida release (ytdlp_updates.py)."""

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile

import pytest

import ytdlp_updates

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_LATEST = ytdlp_updates.latest_version  # conftest replaces it for the UI tests


def fake_build(path, version, marker="downloaded"):
    """A tiny stand-in for yt-dlp's zipimport build, with a shebang line as the real one has."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__main__.py", "import yt_dlp\n")
        archive.writestr("yt_dlp/__init__.py", f"WHERE = {marker!r}\n")
        archive.writestr("yt_dlp/version.py", f"__version__ = '{version}'\n")
        archive.writestr("yt_dlp/extractor/__init__.py", "")
        archive.writestr("yt_dlp/extractor/common.py", "NAME = 'common'\n")
        archive.writestr("yt_dlp_ejs/__init__.py", "")
    data = b"#!/usr/bin/env python3\n" + buffer.getvalue()
    if path:
        with open(path, "wb") as f:
            f.write(data)
    return data


class Response(io.BytesIO):
    def __init__(self, data=b"", url=None):
        super().__init__(data)
        self.url = url
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def opener_for(files, latest="2026.12.01"):
    def opener(url):
        if url == ytdlp_updates.LATEST_API:
            return Response(json.dumps({"tag_name": latest}).encode())
        if url not in files:
            raise OSError(f"HTTP Error 404: {url}")
        return Response(files[url])
    return opener


def release_files(version, data, digest=None):
    digest = digest or hashlib.sha256(data).hexdigest()
    url = ytdlp_updates.DOWNLOAD.format
    return {url(version=version, name="SHA2-256SUMS"): f"{'0' * 64}  yt-dlp.exe\n{digest}  yt-dlp\n".encode(),
            url(version=version, name="yt-dlp"): data}


def test_versions_are_compared_as_dates():
    assert ytdlp_updates.parse_version("2026.08.19") == (2026, 8, 19)
    assert ytdlp_updates.parse_version("2026.8.19") == (2026, 8, 19)
    assert ytdlp_updates.parse_version("2026.10.02.123") == (2026, 10, 2, 123)
    assert ytdlp_updates.is_newer("2026.10.02", "2026.09.30")
    assert not ytdlp_updates.is_newer("2026.08.19", "2026.8.19")
    assert ytdlp_updates.parse_version("nightly") is None


def test_bundled_version_matches_the_pins():
    requirements = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
    spec = open(os.path.join(ROOT, "android", "buildozer.spec"), encoding="utf-8").read()
    pins = re.findall(r"yt-dlp==([\d.]+)", requirements + spec)
    assert pins and all(ytdlp_updates.parse_version(p) == ytdlp_updates.parse_version(ytdlp_updates.BUNDLED_VERSION)
                        for p in pins)


def test_zip_version_needs_a_real_yt_dlp_build(tmp_path):
    fake_build(tmp_path / "ok.zip", "2026.12.01")
    assert ytdlp_updates.zip_version(tmp_path / "ok.zip") == "2026.12.01"
    (tmp_path / "junk.zip").write_bytes(b"not a zip")
    assert ytdlp_updates.zip_version(tmp_path / "junk.zip") is None
    assert ytdlp_updates.zip_version(tmp_path / "missing.zip") is None


def test_latest_version_is_the_latest_release_tag():
    assert REAL_LATEST(opener_for({}, latest="2026.12.01")) == "2026.12.01"
    with pytest.raises(ytdlp_updates.UpdateError):
        REAL_LATEST(lambda url: Response(b'{"message": "API rate limit exceeded"}'))


def test_download_checks_the_checksum_and_the_version(tmp_path):
    data = fake_build(None, "2026.12.01")
    path = ytdlp_updates.download("2026.12.01", str(tmp_path), opener_for(release_files("2026.12.01", data)))
    assert path == str(tmp_path / "yt-dlp.zip") and ytdlp_updates.zip_version(path) == "2026.12.01"

    with pytest.raises(ytdlp_updates.UpdateError, match="checksum"):
        ytdlp_updates.download("2026.12.02", str(tmp_path / "bad"),
                               opener_for(release_files("2026.12.02", data, digest="f" * 64)))
    with pytest.raises(ytdlp_updates.UpdateError, match="is not yt-dlp"):
        ytdlp_updates.download("2026.12.02", str(tmp_path / "other"), opener_for(release_files("2026.12.02", data)))
    assert os.listdir(tmp_path / "bad") == [] and os.listdir(tmp_path / "other") == []


def test_update_downloads_only_something_newer(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_updates, "latest_version", REAL_LATEST)
    monkeypatch.setattr(ytdlp_updates, "running_version", lambda: "2026.08.19")
    data = fake_build(None, "2026.12.01")
    files = release_files("2026.12.01", data)
    assert ytdlp_updates.update(str(tmp_path), opener_for(files, latest="2026.08.19")) is None
    assert not os.listdir(tmp_path)
    assert ytdlp_updates.update(str(tmp_path), opener_for(files)) == "2026.12.01"
    # Already downloaded, waiting for the next start: not again.
    assert ytdlp_updates.update(str(tmp_path), lambda url: pytest.fail(url) if "download" in url
                                else opener_for(files)(url)) is None


_START = """
import sys
sys.path.insert(0, {root!r})
import ytdlp_updates
print("ACTIVE", ytdlp_updates.activate({folder!r}, bundled={bundled!r}))
import yt_dlp
from yt_dlp.extractor import common
import yt_dlp_ejs
print("FROM", getattr(yt_dlp, "WHERE", "bundled"), common.__file__.endswith("common.py"))
"""


def start(folder, bundled):
    out = subprocess.run([sys.executable, "-c", _START.format(root=ROOT, folder=str(folder), bundled=bundled)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_a_newer_download_is_imported_instead_of_the_bundled_one(tmp_path):
    fake_build(tmp_path / "yt-dlp.zip", "2026.12.01")
    out = start(tmp_path, bundled="2026.08.19")
    assert "ACTIVE 2026.12.01" in out and "FROM downloaded True" in out


def test_an_older_download_is_removed_after_an_orbida_update(tmp_path):
    fake_build(tmp_path / "yt-dlp.zip", "2026.07.01")
    out = start(tmp_path, bundled="2026.08.19")
    assert "ACTIVE None" in out and "FROM bundled" in out
    assert not (tmp_path / "yt-dlp.zip").exists()


def test_a_broken_download_falls_back_to_the_bundled_yt_dlp(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("yt_dlp/__init__.py", "raise ImportError('broken build')\n")
        archive.writestr("yt_dlp/version.py", "__version__ = '2026.12.01'\n")
    (tmp_path / "yt-dlp.zip").write_bytes(buffer.getvalue())
    script = f"""
import sys
sys.path.insert(0, {ROOT!r})
import app_setup
app_setup.ytdlp_dir = lambda: {str(tmp_path)!r}
print("USING", app_setup.use_downloaded_ytdlp())
import yt_dlp
print("OK", hasattr(yt_dlp, "YoutubeDL"))
"""
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert "USING None" in out.stdout and "OK True" in out.stdout, out.stderr
    assert not (tmp_path / "yt-dlp.zip").exists()
