"""Orbida 1.2.4: the remaining suggestions of the code reviews (desktop window)."""

import json
import os
import sys

import pytest

import formats
import logic
import playlist
import settings as settings_store

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


@pytest.fixture(autouse=True)
def reset_network():
    yield
    logic.set_network_options("")


@pytest.fixture
def app(monkeypatch, tmp_path):
    pytest.importorskip("customtkinter")
    from ui_helpers import make_app
    from test_ui_queue import QueueManager
    window = make_app(monkeypatch)
    window.manager = QueueManager(window.tools)
    window.manager.release.set()
    window.settings.show_summary = False
    window.download_folder = str(tmp_path)
    yield window
    window.destroy()


def _song_analysis():
    item = playlist.QueueItem(url=playlist.SEARCH_PREFIX + "Artist - Song audio", title="Artist - Song")
    return playlist.AnalysisResult(title="Artist - Song", items=[item])


def _video_analysis(url="https://example.com/v"):
    return playlist.AnalysisResult(title="Video", items=[playlist.QueueItem(url=url, title="Video")])


# --- Spotify does not change the saved mode (review #11) ----------------------------

@needs_display
def test_a_spotify_link_switches_to_audio_only_for_itself(app):
    app._apply_mode(formats.VIDEO_AUDIO, "mkv", "720p")
    app._save_settings()
    app._on_analysis_done(_song_analysis(), "https://open.spotify.com/track/x")
    assert app.cmb_mode.get() == formats.AUDIO_ONLY
    app._on_setting_changed("keep_awake", False)  # any later save
    saved = settings_store.load(app.settings_path, "")
    assert (saved.mode, saved.format, saved.quality) == (formats.VIDEO_AUDIO, "mkv", "720p")
    # The next link that is not Spotify gets the user's mode back.
    app._on_analysis_done(_video_analysis(), "https://example.com/v")
    assert (app.cmb_mode.get(), app.cmb_format.get(), app.cmb_quality.get()) == (formats.VIDEO_AUDIO, "mkv", "720p")


@needs_display
def test_a_mode_picked_after_the_switch_is_kept(app):
    app._apply_mode(formats.VIDEO_AUDIO)
    app._on_analysis_done(_song_analysis(), "https://open.spotify.com/track/x")
    app.cmb_mode.set(formats.AUDIO_ONLY)
    app._on_mode_changed(formats.AUDIO_ONLY)  # the user clicks Audio Only themselves
    assert settings_store.load(app.settings_path, "").mode == formats.AUDIO_ONLY
    app._on_analysis_done(_video_analysis(), "https://example.com/v")
    assert app.cmb_mode.get() == formats.AUDIO_ONLY


def test_settings_file_round_trip(tmp_path):
    path = str(tmp_path / "settings.json")
    settings_store.save(path, settings_store.Settings(mode=formats.VIDEO_ONLY))
    assert json.load(open(path))["mode"] == formats.VIDEO_ONLY
