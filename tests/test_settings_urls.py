import json

import pytest

import settings
import urls


def test_missing_file_gives_defaults(tmp_path):
    s = settings.load(str(tmp_path / "none.json"), "/dl")
    assert s == settings.Settings("/dl", "Video + Audio", "mp4", "Best", "System")


def test_round_trip(tmp_path):
    path = str(tmp_path / "s" / "settings.json")
    settings.save(path, settings.Settings("/music", "Audio Only", "flac", "Best", "Dark"))
    assert settings.load(path, "/dl") == settings.Settings("/music", "Audio Only", "flac", "Best", "Dark")


@pytest.mark.parametrize("content", ["{broken", "[1, 2]", '"text"'])
def test_damaged_file_is_ignored(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content)
    assert settings.load(str(path), "/dl").mode == "Video + Audio"


def test_invalid_values_fall_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"mode": "Audio Only", "format": "mp4", "quality": "1080p", "theme": "Pink",
                                "download_folder": 5, "unknown": "x"}))
    s = settings.load(str(path), "/dl")
    assert (s.mode, s.format, s.quality, s.theme, s.download_folder) == ("Audio Only", "mp3", "Best", "System", "/dl")


@pytest.mark.parametrize("text, expected", [
    ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc"),
    ("  youtu.be/abc  ", "https://youtu.be/abc"),
    ("http://localhost:8000/v.mp4", "http://localhost:8000/v.mp4"),
])
def test_valid_urls(text, expected):
    assert urls.normalize_url(text) == expected


@pytest.mark.parametrize("text, reason", [
    ("", "Paste a link"),
    ("hello world", "spaces"),
    ("ftp://example.com/x", "Only http and https"),
    ("javascript:alert(1)", "web link"),
    ("notalink", "web link"),
])
def test_invalid_urls(text, reason):
    with pytest.raises(ValueError, match=reason):
        urls.normalize_url(text)


def test_app_settings_round_trip_and_bad_types_are_ignored(tmp_path):
    path = str(tmp_path / "settings.json")
    settings.save(path, settings.Settings(download_folder="D:\\Videos", text_size="Large",
                                          open_folder_when_done=True, show_summary=False))
    loaded = settings.load(path, "C:\\default")
    assert (loaded.text_size, loaded.open_folder_when_done, loaded.show_summary) == ("Large", True, False)

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"text_size": "Huge", "open_folder_when_done": "yes", "show_summary": 0}, f)
    loaded = settings.load(path, "C:\\default")
    assert (loaded.text_size, loaded.open_folder_when_done, loaded.show_summary) == ("Normal", False, True)
