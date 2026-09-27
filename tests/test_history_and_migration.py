"""Download history, the settings added in 1.0.0 and the move from UniversalDownloader's data folder."""

import json

import pytest

import app_setup
import download_history
import settings


def test_history_is_newest_first_and_saved(tmp_path):
    path = str(tmp_path / "h" / "history.json")
    history = download_history.History(path)
    history.add("A", "/v/a.mp4", "https://a", "Video + Audio", now=1)
    history.add("B", "/v/b.mp3", "https://b", "Audio Only", now=2)
    history.add("A again", "/v/a.mp4", now=3)
    assert [e.title for e in history.entries] == ["A again", "B"]
    again = download_history.History(path)
    assert [(e.title, e.path, e.time) for e in again.entries] == [("A again", "/v/a.mp4", 3), ("B", "/v/b.mp3", 2)]
    again.remove("/v/b.mp3")
    assert [e.title for e in download_history.History(path).entries] == ["A again"]
    again.clear()
    assert download_history.History(path).entries == []


def test_history_keeps_at_most_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(download_history, "LIMIT", 3)
    history = download_history.History(str(tmp_path / "history.json"))
    for i in range(5):
        history.add(str(i), f"/v/{i}")
    assert [e.title for e in history.entries] == ["4", "3", "2"]


@pytest.mark.parametrize("content", ["{broken", '{"a": 1}', "[1, null, {\"title\": 5, \"path\": \"/x\"}]"])
def test_damaged_history_is_ignored(tmp_path, content):
    path = tmp_path / "history.json"
    path.write_text(content)
    assert download_history.History(str(path)).entries == []


def test_history_skips_only_the_bad_entries(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps([{"title": "ok", "path": "/v/ok.mp4", "time": "x"}, {"path": ""}]))
    entries = download_history.History(str(path)).entries
    assert [(e.title, e.time, e.mode) for e in entries] == [("ok", 0.0, "")]


def test_new_settings_have_defaults_and_limits(tmp_path):
    s = settings.load(str(tmp_path / "none.json"), "/dl")
    assert (s.accent, s.fragments, s.auto_paste, s.keep_awake, s.save_history, s.check_updates) == \
        ("Indigo", 4, True, True, True, True)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"accent": "Chartreuse", "fragments": 99, "auto_paste": "yes"}))
    s = settings.load(str(path), "/dl")
    assert (s.accent, s.fragments, s.auto_paste) == ("Indigo", settings.FRAGMENTS_MAX, True)
    path.write_text(json.dumps({"fragments": 0, "accent": "Teal"}))
    s = settings.load(str(path), "/dl")
    assert (s.accent, s.fragments) == ("Teal", 1)


def test_speed_options_follow_the_setting():
    s = settings.Settings(fragments=8)
    assert settings.download_speed_options(s) == {"concurrent_fragment_downloads": 8,
                                                  "http_chunk_size": 10 * 1024 * 1024}


def test_settings_move_from_the_old_folder_once(tmp_path):
    old = tmp_path / "UniversalDownloader"
    old.mkdir()
    (old / "settings.json").write_text('{"theme": "Dark"}')
    (old / "logs").mkdir()
    assert app_setup.migrate_legacy_data(str(tmp_path)) == ["settings.json"]
    assert (tmp_path / "Orbida" / "settings.json").read_text() == '{"theme": "Dark"}'
    assert (old / "settings.json").exists()  # the old folder is left alone
    (old / "settings.json").write_text('{"theme": "Light"}')
    assert app_setup.migrate_legacy_data(str(tmp_path)) == []  # never again once Orbida has settings
    assert (tmp_path / "Orbida" / "settings.json").read_text() == '{"theme": "Dark"}'


def test_nothing_to_move_on_a_fresh_install(tmp_path):
    assert app_setup.migrate_legacy_data(str(tmp_path)) == []
    assert not (tmp_path / "Orbida").exists()


def test_data_folder_is_named_after_the_app(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert app_setup.data_dir() == str(tmp_path / "Orbida")


def test_keep_awake_is_harmless_off_windows(monkeypatch):
    monkeypatch.setattr(app_setup.sys, "platform", "linux")
    assert app_setup.keep_awake(True) is False
