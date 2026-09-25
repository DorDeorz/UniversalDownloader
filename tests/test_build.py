"""Build script checks and startup helpers (ISSUES.md #46, #48, #63-#66, #69, #72, #77, #81)."""

import json
import os
import subprocess
import sys

import app_setup
import build_app
import version

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ok_run(cmd, **kwargs):
    return subprocess.CompletedProcess(cmd, 0, stdout=f"{os.path.basename(cmd[0])} version 7.1 x\n", stderr="")


def make_root(tmp_path, tool_bytes=b"MZ real", ico=build_app.ICO_MAGIC + b"rest"):
    (tmp_path / "bin").mkdir()
    for tool in ("ffmpeg.exe", "ffprobe.exe"):
        (tmp_path / "bin" / tool).write_bytes(tool_bytes)
    (tmp_path / "app.ico").write_bytes(ico)
    (tmp_path / "app.png").write_bytes(b"png")
    (tmp_path / "THIRD_PARTY_NOTICES.md").write_text("x")
    return tmp_path


def test_repo_icon_is_a_real_ico():
    assert build_app.check_icon(os.path.join(ROOT, "app.ico")) is None


def test_png_renamed_to_ico_is_rejected(tmp_path):
    fake = tmp_path / "app.ico"
    fake.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert "not a real .ico" in build_app.check_icon(str(fake))


def test_preflight_passes_with_good_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(build_app, "check_virtualenv", lambda: None)
    root = make_root(tmp_path)
    assert build_app.preflight(str(root), run=ok_run, require_windows=False) == []


def test_preflight_rejects_lfs_pointers_and_bad_icon(tmp_path, monkeypatch):
    monkeypatch.setattr(build_app, "check_virtualenv", lambda: None)
    root = make_root(tmp_path, tool_bytes=b"version https://git-lfs.github.com/spec/v1\n", ico=b"\x89PNG")
    problems = build_app.preflight(str(root), run=ok_run, require_windows=False)
    assert any("Git LFS pointer" in p for p in problems)
    assert any("not a real .ico" in p for p in problems)


def test_preflight_requires_virtualenv(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "base_prefix", sys.prefix)
    root = make_root(tmp_path)
    problems = build_app.preflight(str(root), run=ok_run, require_windows=False)
    assert any("virtual environment" in p for p in problems)


def test_manifest_records_version_and_checksums(tmp_path):
    root = make_root(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    exe = dist / "UniversalDownloader-1.0.0.exe"
    exe.write_bytes(b"exe")

    info = build_app.write_manifest(str(exe), dist=str(dist), root=str(root))

    assert info["version"] == version.__version__
    sums = (dist / "SHA256SUMS.txt").read_text().splitlines()
    assert sums[0].endswith("  UniversalDownloader-1.0.0.exe")
    assert len(sums) == 3
    assert json.loads((dist / "build-info.json").read_text())["sha256"] == info["sha256"]


def test_only_one_spec_file():
    specs = [f for f in os.listdir(ROOT) if f.endswith(".spec")]
    assert specs == ["UniversalDownloader.spec"]


def test_logging_writes_rotating_file(tmp_path):
    import logging
    path = app_setup.configure_logging(str(tmp_path / "logs"))
    try:
        logging.getLogger("x").warning("hello")
        for h in logging.getLogger().handlers:
            h.flush()
        assert "hello" in open(path, encoding="utf-8").read()
    finally:
        root = logging.getLogger()
        for h in list(root.handlers):
            if getattr(h, "baseFilename", None) == path:
                root.removeHandler(h)
                h.close()


def test_single_instance_is_a_noop_off_windows():
    instance = app_setup.SingleInstance("test")
    if sys.platform != "win32":
        assert not instance.already_running
    instance.release()


def test_second_instance_is_detected_on_windows():
    if sys.platform != "win32":
        return
    first = app_setup.SingleInstance("uvd-test-mutex")
    second = app_setup.SingleInstance("uvd-test-mutex")
    try:
        assert not first.already_running
        assert second.already_running
    finally:
        second.release()
        first.release()


def deno_run(cmd, **kwargs):
    if os.path.basename(cmd[0]) == "deno.exe":
        return subprocess.CompletedProcess(cmd, 0, stdout="deno 2.5.0 (stable)\nv8 x\n", stderr="")
    return ok_run(cmd, **kwargs)


def test_preflight_can_require_deno(tmp_path, monkeypatch):
    monkeypatch.setattr(build_app, "check_virtualenv", lambda: None)
    root = make_root(tmp_path)
    problems = build_app.preflight(str(root), run=deno_run, require_windows=False, require_deno=True)
    assert any("deno.exe not found" in p for p in problems)
    (root / "bin" / "deno.exe").write_bytes(b"MZ")
    assert build_app.preflight(str(root), run=deno_run, require_windows=False, require_deno=True) == []
    problems = build_app.preflight(str(root), run=ok_run, require_windows=False, require_deno=True)
    assert any("like Deno" in p for p in problems)


def test_folder_build_is_what_the_installer_packs():
    exe = build_app.output_exe(onedir=True, dist="dist")
    assert exe == os.path.join("dist", "UniversalDownloader", "UniversalDownloader.exe")
    with open(os.path.join(ROOT, "installer", "UniversalDownloader.iss"), encoding="utf-8") as f:
        script = f.read()
    assert '#define SourceDir "..\\dist\\UniversalDownloader"' in script
    assert '#define AppExe "UniversalDownloader.exe"' in script
    # Setup asks to close the running app by the mutex it holds.
    assert f"AppMutex=Local\\{version.APP_USER_MODEL_ID}" in script
    assert "PrivilegesRequired=lowest" in script


def test_release_workflow_builds_with_real_tools():
    with open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8") as f:
        workflow = f.read()
    assert "lfs: true" in workflow
    assert "build_app.py --onedir --require-deno" in workflow
    assert "installer\\UniversalDownloader.iss" in workflow
