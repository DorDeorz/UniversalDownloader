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


# --- Skip a version, update channel, check once a day (review #44, B4-9) --------------

@needs_display
def test_a_skipped_version_is_not_offered_again(app):
    import events
    import updates
    from ui_helpers import pump
    release = updates.Release("9.9.9", "orbida-v9.9.9", "https://example.invalid/r", "", {})
    app.events.post(events.UPDATE_CHECKED, release=release, error=None, manual=False)
    pump(app, timeout=0.3)
    app.show_update_dialog()
    app.update_dialog.skip()
    pump(app, timeout=0.2)
    assert app.update_dialog is None and app.available_update is None and not app.btn_update.winfo_ismapped()
    assert settings_store.load(app.settings_path, "").skipped_version == "9.9.9"


@needs_display
def test_the_check_uses_the_channel_the_cache_and_the_skipped_version(app, monkeypatch):
    import updates
    from ui_helpers import pump
    asked = []
    monkeypatch.setattr(updates, "check", lambda **kw: asked.append(kw))
    app.settings.update_channel, app.settings.skipped_version = "beta", "9.9.9"
    for manual in (False, True):
        app.check_for_updates(manual=manual)
        app._update_thread.join(5)
    pump(app, timeout=0.2)
    automatic, manual = asked
    assert automatic["channel"] == "beta" and automatic["skipped"] == "9.9.9"
    assert automatic["max_age"] == updates.CHECK_EVERY and automatic["cache_path"].endswith("update-check.json")
    assert manual["skipped"] == "" and manual["max_age"] == 0  # "Check now" always asks, and shows any version


# --- Long playlists: progress while reading (review #27) -----------------------------

@needs_display
def test_reading_a_long_list_shows_how_far_it_got(app):
    app._job_kind = "analysis"
    try:
        app._on_analysis_progress(120, 850)
        assert "120 / 850" in app.lbl_media.cget("text")
        app._on_analysis_progress(50)
        assert "50" in app.lbl_media.cget("text")
    finally:
        app._job_kind = None


# --- Settings › Advanced and About (review #13, #28, #29, #30, #31, #34, #35, UI-8, UI-17) ----

def _settings_page(app, tab):
    from ui_helpers import pump
    app.open_settings()
    app.settings_view.show_tab(tab)
    pump(app, timeout=0.2)
    return app.settings_view


@needs_display
def test_subtitle_choices_are_saved_and_used(app):
    view = _settings_page(app, "advanced")
    view.ent_sub_langs.insert(0, "TR; en,, x!y")
    view._save_sub_langs()
    assert app.settings.subtitle_langs == "TR, en" and view.ent_sub_langs.get() == "TR, en"
    view.seg_sub_format.set("ass")
    view.seg_sub_format._picked(view.seg_sub_format._labels()[1])
    view.sw_sub_embed.toggle()
    saved = settings_store.load(app.settings_path, "")
    assert (saved.subtitle_langs, saved.subtitle_format, saved.subtitle_embed) == ("TR, en", "ass", True)


@needs_display
def test_sponsorblock_categories_can_be_chosen(app):
    view = _settings_page(app, "advanced")
    assert all(box.get() for box in view.sponsor_boxes.values())  # all by default
    view.sponsor_boxes["intro"].toggle()
    view.sponsor_boxes["outro"].toggle()
    assert app.settings.sponsorblock_categories == "sponsor,selfpromo,interaction,music_offtopic"


@needs_display
def test_download_options_carry_the_advanced_choices(app, monkeypatch):
    started = []
    monkeypatch.setattr(app, "_start_job", lambda kind, fn, items, opts: started.append(opts) or False)
    app.settings.subtitles = app.settings.sponsorblock = app.settings.live_from_start = True
    app.settings.subtitle_langs, app.settings.subtitle_format, app.settings.subtitle_embed = "de", "ass", True
    app.settings.sponsorblock_categories = "sponsor"
    app.tools = app.tools or object()
    app.download_queue = [{"url": "https://example.com/v", "title": "V"}]
    app._apply_mode(formats.VIDEO_AUDIO)
    app.start_download_queue()
    opts, = started
    assert opts["subtitle_langs"] == ["de"] and opts["subtitle_format"] == "ass" and opts["subtitle_embed"]
    assert opts["sponsorblock_categories"] == "sponsor" and opts["live_from_start"]


@needs_display
def test_connection_test_shows_its_result(app, monkeypatch):
    from ui_helpers import pump
    monkeypatch.setattr(logic, "check_connection", lambda proxy: (0.123, None))
    view = _settings_page(app, "advanced")
    view.btn_test.invoke()
    assert pump(app, lambda: "123" in view.lbl_test.cget("text"), timeout=3)
    monkeypatch.setattr(logic, "check_connection", lambda proxy: (None, "Proxy refused: 407"))
    view.btn_test.invoke()
    assert pump(app, lambda: "407" in view.lbl_test.cget("text"), timeout=3)


@needs_display
def test_detailed_log_applies_at_once(app):
    import app_setup
    view = _settings_page(app, "advanced")
    try:
        view.sw_verbose.toggle()
        assert logic.base_ydl_options().get("verbose") is True
    finally:
        logic.set_verbose(False)
        app_setup.set_verbose_logging(False)


@needs_display
def test_diagnostics_are_copied(app):
    view = _settings_page(app, "advanced")
    view.copy_diagnostics()
    text = app.clipboard_get()
    assert text.startswith("Orbida ") and "yt-dlp" in text


@needs_display
def test_forgetting_the_archive_starts_playlists_fresh(app, monkeypatch):
    app.archive.add("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    import ui
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: True)
    view = _settings_page(app, "advanced")
    view.btn_forget.invoke()
    assert len(app.archive) == 0


@needs_display
def test_reset_brings_back_the_defaults_but_keeps_the_folder(app, monkeypatch, tmp_path):
    import ui
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: True)
    app.settings.download_folder = str(tmp_path)
    for name, value in (("speed_limit", 5), ("subtitles", True), ("update_channel", "beta"), ("fragments", 8),
                        ("sponsorblock_categories", "sponsor")):
        app._on_setting_changed(name, value)
    view = _settings_page(app, "advanced")
    view.btn_reset.invoke()
    saved = settings_store.load(app.settings_path, "")
    default = settings_store.Settings()
    assert (saved.speed_limit, saved.subtitles, saved.update_channel, saved.fragments) == \
        (default.speed_limit, default.subtitles, default.update_channel, default.fragments)
    assert saved.sponsorblock_categories == default.sponsorblock_categories
    assert saved.download_folder == str(tmp_path)
    assert app.settings_view.tab == "advanced" and not app.chk_subtitles.get()


@needs_display
def test_about_names_the_versions_and_the_licenses(app):
    view = _settings_page(app, "about")
    text = view.lbl_versions.cget("text")
    assert "yt-dlp" in text and "Python" in text
    licenses = view.txt_licenses.get("1.0", "end")
    assert "FFmpeg" in licenses and "](" not in licenses  # Markdown links read as names


@needs_display
def test_the_settings_tab_is_kept(app):
    _settings_page(app, "about")
    app._on_setting_changed("language", "de")  # rebuilds the page
    assert app.settings_view.tab == "about"
    app.close_settings()
    app.open_settings()
    assert app.settings_view.tab == "about"
    app._on_setting_changed("language", "en")
