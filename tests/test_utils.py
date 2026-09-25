import os
import sys

import utils

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_resource_path_is_anchored_on_module_dir_not_cwd(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.chdir(tmp_path)

    assert utils.resource_path("app.ico") == os.path.join(REPO_ROOT, "app.ico")


def test_resource_path_uses_pyinstaller_bundle_dir_when_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert utils.resource_path("app.ico") == os.path.join(str(tmp_path), "app.ico")


def test_ffmpeg_and_ffprobe_paths_point_into_bin(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert utils.get_ffmpeg_path() == os.path.join(REPO_ROOT, "bin", "ffmpeg.exe")
    assert utils.get_ffprobe_path() == os.path.join(REPO_ROOT, "bin", "ffprobe.exe")
