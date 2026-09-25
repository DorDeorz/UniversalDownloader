"""Collision-safe output names and folders (ISSUES.md #34-#41)."""

import os
import sys

import pytest

import filenames
from results import ItemStatus


@pytest.mark.parametrize("key, folder", [
    ("Youtube", "YouTube"), ("YoutubeTab", "YouTube"), ("TikTok", "TikTok"), ("Instagram", "Instagram"),
    ("Twitter", "X_Twitter"), ("Generic", "Other"), ("Vimeo", "Vimeo"), ("", "Other"),
])
def test_platform_folder_uses_extractor(key, folder):
    assert filenames.platform_folder({"extractor_key": key}) == folder


def test_platform_folder_ignores_url_text():
    # A non-YouTube site whose URL mentions youtube is not filed under YouTube.
    info = {"extractor_key": "Generic", "webpage_url": "https://example.com/youtube-clip"}
    assert filenames.platform_folder(info) == "Other"


def test_unique_base_adds_numeric_suffix(tmp_path):
    prepared = str(tmp_path / "Clip.webm")
    assert filenames.unique_base(prepared, "mp4") == str(tmp_path / "Clip")
    (tmp_path / "Clip.mp4").write_bytes(b"x")
    assert filenames.unique_base(prepared, "mp4") == str(tmp_path / "Clip (2)")
    (tmp_path / "Clip (2).mp4.part").write_bytes(b"x")
    assert filenames.unique_base(prepared, "mp4") == str(tmp_path / "Clip (3)")


def test_unique_base_avoids_any_extension(tmp_path):
    # yt-dlp would treat an existing Clip.mp4 as the already-downloaded
    # source for Clip.mp3, so any extension makes the name taken.
    (tmp_path / "Clip.mp4").write_bytes(b"x")
    assert filenames.unique_base(str(tmp_path / "Clip.webm"), "mp3") == str(tmp_path / "Clip (2)")


def test_unique_base_ignores_similar_names(tmp_path):
    (tmp_path / "Clip extended.mp4").write_bytes(b"x")
    assert filenames.unique_base(str(tmp_path / "Clip.webm"), "mp4") == str(tmp_path / "Clip")


def test_output_template_numbers_playlist_items(tmp_path):
    tmpl = filenames.output_template(str(tmp_path), playlist_index=7)
    assert os.path.basename(tmpl).startswith("007 - %(title).")


def test_output_template_limits_title_length(tmp_path):
    short = filenames.output_template("C:\\d")
    long_folder = "C:\\" + "x" * 200
    long = filenames.output_template(long_folder)
    assert "%(title).150B" in short
    assert "%(title).40B" in long


def test_output_template_escapes_percent_in_folder():
    assert filenames.output_template("C:\\100% music").startswith("C:\\100%% music")


def test_playlist_folder_is_sanitized(tmp_path):
    folder = filenames.output_folder(str(tmp_path), {"extractor_key": "Youtube"}, 'Best: of <2024> / "mix"?')
    name = os.path.basename(folder)
    assert not set('<>:"/\\|?*') & set(name)
    assert os.path.dirname(folder) == os.path.join(str(tmp_path), "YouTube")


def test_safe_name_never_empty():
    assert filenames.safe_name("...") == "Untitled"


def test_check_folder_creates_and_accepts_writable(tmp_path):
    target = tmp_path / "new" / "dir"
    error, _ = filenames.check_folder(str(target))
    assert error is None
    assert target.is_dir()
    assert list(target.iterdir()) == []


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions as non-root")
def test_check_folder_reports_unwritable(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        error, _ = filenames.check_folder(str(locked))
    finally:
        locked.chmod(0o700)
    assert error and "Cannot write" in error


def test_check_folder_reports_file_in_the_way(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_bytes(b"x")
    error, _ = filenames.check_folder(str(blocker / "sub"))
    assert error and "Cannot write" in error


def test_check_folder_warns_on_low_space(tmp_path, monkeypatch):
    monkeypatch.setattr(filenames.shutil, "disk_usage", lambda p: type("U", (), {"free": 10 * 1024 ** 2})())
    error, warning = filenames.check_folder(str(tmp_path))
    assert error is None and "10 MB free" in warning


# --- through download_video ----------------------------------------------

def test_same_title_twice_gets_suffix_not_overwrite(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"id": "a", "title": "Same", "ext": "mp4", "extractor_key": "Youtube"}
    first = manager.download_video("https://youtu.be/a", {"save_path": str(tmp_path)})
    lines = []
    second = manager.download_video("https://youtu.be/b", {"save_path": str(tmp_path)}, log_callback=lines.append)

    assert first.path == str(tmp_path / "YouTube" / "Same.mp4")
    assert second.path == str(tmp_path / "YouTube" / "Same (2).mp4")
    assert second.status is ItemStatus.COMPLETED
    assert "File exists; saving as Same (2).mp4" in lines


def test_playlist_item_goes_to_playlist_folder_with_index(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"id": "a", "title": "Song", "ext": "webm", "extractor_key": "Youtube"}
    result = manager.download_video(
        "https://youtu.be/a",
        {"save_path": str(tmp_path), "mode": "Audio Only", "format": "mp3",
         "playlist_index": 3, "playlist_title": "Road Trip"})

    assert result.path == str(tmp_path / "YouTube" / "Road Trip" / "003 - Song.mp3")


def test_title_with_percent_and_reserved_chars(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"id": "a", "title": 'Top 10% <live> "A/B"?', "ext": "mp4", "extractor_key": "Youtube"}
    result = manager.download_video("https://youtu.be/a", {"save_path": str(tmp_path)})

    assert result.status is ItemStatus.COMPLETED
    name = os.path.basename(result.path)
    assert "10%" in name
    assert not set('<>:"/\\|?*') & set(name)


def test_default_download_dir_is_under_downloads():
    from utils import default_download_dir
    assert os.path.basename(default_download_dir()) == "UniversalVideos"
