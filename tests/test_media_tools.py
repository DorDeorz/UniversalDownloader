"""FFmpeg/ffprobe detection (ISSUES.md #47-#49)."""

import os
import subprocess

import pytest

import media_tools

REPO_BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")


def fake_run(version="7.1", returncode=0):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        out = f"{os.path.basename(cmd[0])} version {version} Copyright (c) 2000-2026\n"
        return subprocess.CompletedProcess(cmd, returncode, stdout=out, stderr="")

    run.calls = calls
    return run


def make_tools(folder, content=b"MZ fake exe"):
    folder.mkdir(parents=True, exist_ok=True)
    for tool in ("ffmpeg", "ffprobe"):
        (folder / media_tools.exe_name(tool)).write_bytes(content)
    return folder


def lfs_pointer():
    return (b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:1a549c3427b8eee98def0c321acfafad3c3eab4766e44c8ce18904fd6cb081d0\nsize 100749312\n")


def test_bundled_tools_are_used_and_versioned(tmp_path):
    folder = make_tools(tmp_path / "bin")
    run = fake_run("7.1-full")

    status = media_tools.find_tools(run=run, which=lambda n: None, bundled=str(folder))

    assert status.ok and status.source == "bundled"
    assert status.version == "7.1-full"
    assert status.directory == str(folder)
    assert [os.path.basename(c[0]) for c in run.calls] == [media_tools.exe_name("ffmpeg"),
                                                         media_tools.exe_name("ffprobe")]


def test_lfs_pointer_is_reported_with_fix(tmp_path):
    folder = make_tools(tmp_path / "bin", lfs_pointer())

    status = media_tools.find_tools(run=fake_run(), which=lambda n: None, bundled=str(folder))

    assert not status.ok
    assert "Git LFS pointer" in status.error and "git lfs pull" in status.error


def test_repo_checkout_without_lfs_is_detected():
    ffmpeg = os.path.join(REPO_BIN, "ffmpeg.exe")
    if os.path.getsize(ffmpeg) > 1024:
        pytest.skip("real FFmpeg checked out with git lfs pull")
    assert media_tools.is_lfs_pointer(ffmpeg)


def test_falls_back_to_path(tmp_path):
    bundled = tmp_path / "missing"
    on_path = make_tools(tmp_path / "path")
    which = {"ffmpeg": str(on_path / media_tools.exe_name("ffmpeg")),
             "ffprobe": str(on_path / media_tools.exe_name("ffprobe"))}.get

    status = media_tools.find_tools(run=fake_run(), which=which, bundled=str(bundled))

    assert status.ok and status.source == "PATH"
    assert status.directory == str(on_path)


def test_missing_everywhere_explains(tmp_path):
    status = media_tools.find_tools(run=fake_run(), which=lambda n: None, bundled=str(tmp_path))

    assert not status.ok
    assert "not found" in status.error and "Downloads need FFmpeg" in status.error


def test_broken_binary_is_rejected(tmp_path):
    folder = make_tools(tmp_path / "bin")

    status = media_tools.find_tools(run=fake_run(returncode=1), which=lambda n: None, bundled=str(folder))

    assert not status.ok and "-version failed" in status.error


def test_hanging_binary_times_out(tmp_path):
    folder = make_tools(tmp_path / "bin")

    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    status = media_tools.find_tools(run=run, which=lambda n: None, bundled=str(folder))

    assert not status.ok and "did not answer" in status.error


def test_activate_puts_folder_first_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))
    media_tools.activate(media_tools.ToolStatus(True, directory=str(tmp_path)))
    media_tools.activate(media_tools.ToolStatus(True, directory=str(tmp_path)))

    assert os.environ["PATH"].split(os.pathsep) == [str(tmp_path), "/usr/bin", "/bin"]


def test_activate_ignores_failed_status(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    media_tools.activate(media_tools.ToolStatus(False, error="x"))
    assert os.environ["PATH"] == "/usr/bin"


def test_summary():
    assert media_tools.ToolStatus(True, directory="/b", version="7.1", source="PATH").summary() == \
        "FFmpeg 7.1 (PATH: /b)"
    assert media_tools.ToolStatus(False, error="gone").summary() == "FFmpeg problem: gone"
