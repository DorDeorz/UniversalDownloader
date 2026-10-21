"""The Mozilla-signed Firefox add-on: signing helper, build, release workflow and the app's button."""

import base64
import hashlib
import hmac
import io
import json
import os
import sys
import urllib.error
import zipfile

import pytest

import app_setup
import build_app
import firefox_addon
from version import __version__

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTENSION = os.path.join(ROOT, "browser_extension")

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


def signed_xpi(path, source=EXTENSION, signature=firefox_addon.SIGNATURE_FILES, change=None):
    """An add-on file laid out like the one AMO returns (the source files plus META-INF)."""
    with zipfile.ZipFile(path, "w") as archive:
        for folder, _dirs, files in os.walk(source):
            for name in files:
                full = os.path.join(folder, name)
                inside = os.path.relpath(full, source).replace(os.sep, "/")
                with open(full, "rb") as f:
                    data = f.read()
                archive.writestr(inside, (change or {}).get(inside, data))
        for name in signature:
            archive.writestr(name, b"signature")
    return str(path)


def b64decode(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_the_manifest_is_ready_for_mozilla_signing():
    with open(os.path.join(EXTENSION, "manifest.json"), encoding="utf-8") as f:
        gecko = json.load(f)["browser_specific_settings"]["gecko"]
    assert gecko["id"] == firefox_addon.addon_id() == "orbida@dordeorz.github.io"
    # AMO refuses new add-ons that do not declare what they collect; Orbida collects nothing.
    assert gecko["data_collection_permissions"] == {"required": ["none"]}
    assert int(gecko["strict_min_version"].split(".")[0]) >= 140  # the first Firefox that reads that key


def test_the_token_is_what_amo_expects():
    token = firefox_addon.jwt_token("user:1:2", "secret", now=1000)
    header, payload, signature = token.split(".")
    assert json.loads(b64decode(header)) == {"alg": "HS256", "typ": "JWT"}
    claims = json.loads(b64decode(payload))
    assert claims["iss"] == "user:1:2" and claims["iat"] == 1000 and claims["exp"] == 1060
    assert claims["jti"] != json.loads(b64decode(firefox_addon.jwt_token("user:1:2", "secret", 1000).split(".")[1]))["jti"]
    expected = hmac.new(b"secret", f"{header}.{payload}".encode(), hashlib.sha256).digest()
    assert b64decode(signature) == expected


class FakeAMO:
    """Answers like addons.mozilla.org: version details, then the file."""

    def __init__(self, status=200, file_status="public"):
        self.status, self.file_status, self.requests = status, file_status, []

    def __call__(self, request, timeout):
        self.requests.append(request)
        assert request.get_header("Authorization").startswith("JWT ")
        if request.full_url.endswith(".xpi"):
            return io.BytesIO(b"signed file")
        if self.status != 200:
            raise urllib.error.HTTPError(request.full_url, self.status, "error", {}, None)
        return io.BytesIO(json.dumps({"file": {"status": self.file_status,
                                               "url": "https://addons.mozilla.org/files/orbida.xpi"}}).encode())


def test_fetch_downloads_the_version_amo_signed_before(tmp_path):
    amo = FakeAMO()
    target = tmp_path / "firefox" / "Orbida.xpi"
    assert firefox_addon.fetch(str(target), "key", "secret", version="1.2.0", opener=amo)
    assert target.read_bytes() == b"signed file"
    assert amo.requests[0].full_url == \
        "https://addons.mozilla.org/api/v5/addons/addon/orbida@dordeorz.github.io/versions/v1.2.0/"


def test_fetch_reports_a_version_amo_does_not_have(tmp_path):
    target = tmp_path / "Orbida.xpi"
    assert not firefox_addon.fetch(str(target), "key", "secret", opener=FakeAMO(status=404))
    assert not target.exists()


@pytest.mark.parametrize("amo, message", [
    (FakeAMO(file_status="unreviewed"), "not signed"),
    (FakeAMO(status=401), "refused the API key"),
])
def test_fetch_stops_on_an_unsigned_version_or_a_bad_key(tmp_path, amo, message):
    with pytest.raises(RuntimeError, match=message):
        firefox_addon.fetch(str(tmp_path / "Orbida.xpi"), "key", "secret", opener=amo)


def test_main_needs_the_api_key(monkeypatch, capsys):
    monkeypatch.delenv("AMO_JWT_ISSUER", raising=False)
    monkeypatch.delenv("AMO_JWT_SECRET", raising=False)
    assert firefox_addon.main(["fetch", "x.xpi"]) == 1
    assert "AMO_JWT_ISSUER" in capsys.readouterr().out


def test_main_ignores_spaces_around_the_pasted_key(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setenv("AMO_JWT_ISSUER", " user:1:2\n")
    monkeypatch.setenv("AMO_JWT_SECRET", "  abc123 \n")
    monkeypatch.setattr(firefox_addon, "fetch", lambda path, issuer, secret: seen.append((issuer, secret)))
    assert firefox_addon.main(["fetch", str(tmp_path / "x.xpi")]) == firefox_addon.NOT_SIGNED
    assert seen == [("user:1:2", "abc123")]


def test_a_signed_copy_of_these_files_passes(tmp_path):
    assert firefox_addon.check(signed_xpi(tmp_path / "a.xpi")) == []
    # The newer COSE signature alone is enough too.
    assert firefox_addon.check(signed_xpi(tmp_path / "b.xpi", signature=["META-INF/cose.sig"])) == []


def test_an_unsigned_old_or_different_copy_is_refused(tmp_path):
    assert "not signed" in firefox_addon.check(signed_xpi(tmp_path / "a.xpi", signature=[]))[0]
    old = signed_xpi(tmp_path / "b.xpi")
    assert "the app is 9.9.9" in firefox_addon.check(old, version="9.9.9")[0]
    changed = signed_xpi(tmp_path / "c.xpi", change={"background.js": b"// other code"})
    assert any("background.js differs" in p for p in firefox_addon.check(changed))
    (tmp_path / "d.xpi").write_bytes(b"not a zip")
    assert "not an add-on file" in firefox_addon.check(str(tmp_path / "d.xpi"))[0]


def make_root(tmp_path):
    (tmp_path / "bin").mkdir()
    for tool in ("ffmpeg.exe", "ffprobe.exe"):
        (tmp_path / "bin" / tool).write_bytes(b"MZ real")
    (tmp_path / "app.ico").write_bytes(build_app.ICO_MAGIC + b"rest")
    (tmp_path / "app.png").write_bytes(b"png")
    (tmp_path / "THIRD_PARTY_NOTICES.md").write_text("x")
    return tmp_path


def ok_run(cmd, **kwargs):
    import subprocess
    return subprocess.CompletedProcess(cmd, 0, stdout=f"{os.path.basename(cmd[0])} version 7.1 x\n", stderr="")


def test_the_build_can_require_the_signed_add_on(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(build_app, "check_virtualenv", lambda: None)
    root = make_root(tmp_path)
    shutil.copytree(EXTENSION, root / "browser_extension")
    assert build_app.preflight(str(root), run=ok_run, require_windows=False) == []
    problems = build_app.preflight(str(root), run=ok_run, require_windows=False, require_firefox=True)
    assert any("Orbida.xpi not found" in p for p in problems)
    (root / "firefox").mkdir()
    signed_xpi(root / "firefox" / "Orbida.xpi")
    assert build_app.preflight(str(root), run=ok_run, require_windows=False, require_firefox=True) == []
    signed_xpi(root / "firefox" / "Orbida.xpi", signature=[])
    assert any("not signed" in p for p in build_app.preflight(str(root), run=ok_run, require_windows=False))


def test_the_installer_ships_the_add_on_and_the_release_carries_it():
    with open(os.path.join(ROOT, "Orbida.spec"), encoding="utf-8") as f:
        assert "(os.path.join('firefox', 'Orbida.xpi'), 'firefox')" in f.read()
    assert app_setup.FIREFOX_XPI == os.path.join("firefox", "Orbida.xpi")
    with open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8") as f:
        workflow = f.read()
    assert "web-ext@10.7.0 sign --channel unlisted --source-dir browser_extension" in workflow
    assert "python firefox_addon.py fetch firefox/Orbida.xpi" in workflow
    assert "python firefox_addon.py check firefox/Orbida.xpi" in workflow
    assert "--require-firefox" in workflow
    assert '"release/Orbida-Firefox-$VERSION.xpi"' in workflow
    assert "Only a signed Firefox add-on is published" in workflow


def test_firefox_opens_the_add_on_file(monkeypatch, tmp_path):
    import subprocess
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args: started.append(args))
    assert app_setup.open_in_firefox("Orbida.xpi", firefox="C:/Firefox/firefox.exe")
    assert started == [["C:/Firefox/firefox.exe", os.path.abspath("Orbida.xpi")]]
    monkeypatch.setattr(app_setup, "firefox_path", lambda: None)
    assert not app_setup.open_in_firefox("Orbida.xpi")


@pytest.fixture
def dialog(monkeypatch):
    pytest.importorskip("customtkinter")
    from ui_helpers import make_app
    import ui
    window = make_app(monkeypatch)
    view = ui.ExtensionDialog(window)
    yield ui, view
    view.destroy()
    window.destroy()


@needs_display
def test_add_to_firefox_opens_the_signed_file(dialog, monkeypatch, tmp_path):
    ui, view = dialog
    xpi = tmp_path / "firefox" / "Orbida.xpi"
    monkeypatch.setattr(ui, "resource_path", lambda name: str(tmp_path / name))
    opened, folders, pages = [], [], []
    monkeypatch.setattr(ui.app_setup, "open_in_firefox", lambda path: opened.append(path) or True)
    monkeypatch.setattr(ui, "open_path", folders.append)
    monkeypatch.setattr(ui.webbrowser, "open", pages.append)

    view.add_to_firefox()  # a build without the signed file: the release page has it
    assert pages == [ui.updates.RELEASES_PAGE] and not opened
    assert view.lbl_note.cget("text") == ui.tr("extension.firefox_missing")

    xpi.parent.mkdir()
    xpi.write_bytes(b"xpi")
    view.add_to_firefox()
    assert opened == [str(xpi)]
    assert view.lbl_note.cget("text") == ui.tr("extension.firefox_opened")

    monkeypatch.setattr(ui.app_setup, "open_in_firefox", lambda path: False)  # Firefox not found
    view.add_to_firefox()
    assert folders == [str(xpi.parent)]
    assert view.lbl_note.cget("text") == ui.tr("extension.firefox_file")


def test_every_language_explains_the_firefox_button():
    for name in os.listdir(os.path.join(ROOT, "locales")):
        with open(os.path.join(ROOT, "locales", name), encoding="utf-8") as f:
            texts = json.load(f)
        for key in ("extension.add_firefox", "extension.firefox_opened", "extension.firefox_file",
                    "extension.firefox_missing"):
            assert texts.get(key), (name, key)
        assert "about:debugging" not in texts["extension.firefox"], name  # the temporary add-on is gone
        assert texts["extension.add_firefox"] in texts["extension.firefox"], name


def test_the_signed_add_on_follows_the_app_version():
    with open(os.path.join(EXTENSION, "manifest.json"), encoding="utf-8") as f:
        assert json.load(f)["version"] == __version__  # AMO signs each version once
