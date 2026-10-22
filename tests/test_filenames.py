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


def test_unique_base_ignores_case(tmp_path):
    # Windows treats title.mp4 and Title.mp4 as the same file.
    (tmp_path / "clip.mp4").write_bytes(b"x")
    assert filenames.unique_base(str(tmp_path / "Clip.webm"), "mp4") == str(tmp_path / "Clip (2)")


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
    # A long folder leaves less, but never less than SHORTEST_TITLE_BYTES.
    assert "%(title).16B" in long
    medium = filenames.output_template("C:\\" + "x" * 120)
    assert len("C:\\" + "x" * 120) + 1 + int(medium.split("%(title).")[1].split("B")[0]) + 26 \
        <= filenames.MAX_PATH


def test_output_template_leaves_room_for_the_playlist_number():
    folder = "C:\\" + "x" * 100
    plain = filenames.output_template(folder)
    numbered = filenames.output_template(folder, playlist_index=3)
    size = lambda t: int(t.split("%(title).")[1].split("B")[0])  # noqa: E731
    assert size(plain) - size(numbered) == len("003 - ")


def test_playlist_folder_is_shorter_in_a_long_download_folder():
    base = "C:\\" + "d" * 120
    folder = filenames.output_folder(base, {"extractor_key": "Youtube"}, "P" * 200)
    assert len(os.path.basename(folder)) < 80
    assert len(os.path.basename(folder)) >= 20


@pytest.mark.parametrize("length, ok", [(filenames.LONGEST_FOLDER, True), (filenames.LONGEST_FOLDER + 1, False)])
def test_check_folder_refuses_a_folder_too_long_for_windows(tmp_path, length, ok):
    base = str(tmp_path)
    folder = base + os.sep + "f" * (length - len(base) - 1)
    assert len(folder) == length
    error, _warning = filenames.check_folder(folder, windows=True)
    if ok:
        assert error is None or "characters" not in error
    else:
        assert error == filenames.FOLDER_TOO_LONG.format(length=length, limit=filenames.LONGEST_FOLDER)
    # Elsewhere the path length is not limited.
    assert filenames.check_folder(str(tmp_path / "short"), windows=False)[0] is None


@pytest.mark.parametrize("name", ["CON", "con", "Nul", "aux", "PRN", "COM1", "lpt9", "CON.part2", "nul "])
def test_reserved_windows_names_get_a_prefix(name):
    assert filenames.is_reserved(name)
    assert filenames.avoid_reserved(name) == "_" + name
    assert not filenames.is_reserved(filenames.safe_name(name))


@pytest.mark.parametrize("name", ["Console", "CONTACT", "COM10", "LPT", "nullify", "001 - CON"])
def test_ordinary_names_are_kept(name):
    assert not filenames.is_reserved(name)
    assert filenames.avoid_reserved(name) == name


def test_unique_base_avoids_reserved_names(tmp_path):
    assert filenames.unique_base(str(tmp_path / "CON.webm"), "mp4") == str(tmp_path / "_CON")
    (tmp_path / "_CON.mp4").write_bytes(b"x")
    assert filenames.unique_base(str(tmp_path / "CON.webm"), "mp4") == str(tmp_path / "_CON (2)")


def test_folder_listing_is_reused_until_the_folder_changes(tmp_path, monkeypatch):
    calls = []
    real = os.scandir

    def counting(path):
        calls.append(path)
        return real(path)
    monkeypatch.setattr(filenames.os, "scandir", counting)
    filenames._listings.clear()
    old = os.stat(tmp_path).st_mtime_ns - 60 * 10**9  # changed a minute ago
    os.utime(tmp_path, ns=(old, old))
    prepared = str(tmp_path / "Clip.webm")
    assert filenames.unique_base(prepared) == str(tmp_path / "Clip")
    assert filenames.unique_base(prepared) == str(tmp_path / "Clip")
    assert len(calls) == 1
    (tmp_path / "Clip.mp4").write_bytes(b"x")
    assert filenames.unique_base(prepared) == str(tmp_path / "Clip (2)")
    assert len(calls) == 2


def test_a_folder_changed_just_now_is_listed_again(tmp_path, monkeypatch):
    # A drive that keeps times in 2-second steps may not show a change in the time.
    filenames._listings.clear()
    prepared = str(tmp_path / "Clip.webm")
    assert filenames.unique_base(prepared) == str(tmp_path / "Clip")
    stamp = os.stat(tmp_path).st_mtime_ns
    (tmp_path / "Clip.mp4").write_bytes(b"x")
    os.utime(tmp_path, ns=(stamp, stamp))  # the time did not move
    assert filenames.unique_base(prepared) == str(tmp_path / "Clip (2)")


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
    assert filenames.low_space_mb(str(tmp_path)) == 10


def test_enough_space_gives_no_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(filenames.shutil, "disk_usage", lambda p: type("U", (), {"free": 50 * 1024 ** 3})())
    assert filenames.check_folder(str(tmp_path)) == (None, None)
    assert filenames.low_space_mb(str(tmp_path)) is None


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
    assert os.path.basename(default_download_dir()) == "Orbida"
