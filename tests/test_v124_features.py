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


# --- Download page (UI-1 … UI-16, #21) ---------------------------------------------------

@needs_display
def test_the_download_buttons_stay_below_the_scrolling_page(app):
    assert app.btn_download.master is app.action_bar and app.action_bar.master is app
    app.open_settings()
    assert not app.action_bar.winfo_manager()  # not under other pages
    app.close_settings()
    assert app.action_bar.winfo_manager()


@needs_display
def test_the_log_can_be_copied_and_cleared(app):
    app._append_log("hello")
    app.copy_log()
    assert "> hello" in app.clipboard_get()
    app.clear_log()
    assert app.console.get("1.0", "end-1c") == ""


@needs_display
def test_an_error_shows_in_a_band_that_can_be_closed(app):
    from ui_helpers import pump
    app.hide_band()  # the first-run tips
    app._job_kind = "analysis"
    app._on_analysis_failed("FAILED: no such video")
    pump(app, timeout=0.1)
    assert app.band_kind == "error" and "no such video" in app.lbl_band.cget("text")
    app.btn_band_close.invoke()
    assert app.band_kind is None and not app.band.winfo_manager()


@needs_display
def test_first_run_tips_show_once(app):
    assert app.band_kind == "info"
    app.hide_band()
    assert settings_store.load(app.settings_path, "").onboarded


@needs_display
def test_failed_downloads_offer_retry_and_a_finished_file_can_be_opened(app, tmp_path, monkeypatch):
    from results import ItemResult, ItemStatus, JobSummary
    import ui
    opened = []
    monkeypatch.setattr(ui, "open_file", opened.append)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    ok = ItemResult("https://a", "A", ItemStatus.COMPLETED, path=str(video))
    bad = ItemResult("https://b", "B", ItemStatus.FAILED, error="boom")
    app._on_item_done(ok)
    app._on_item_done(bad)
    app._on_job_done(JobSummary([ok, bad]))
    assert app.band_kind == "error" and app.btn_band.winfo_manager()
    assert app.done_buttons.winfo_manager()
    app.btn_open_file.invoke()
    assert opened == [str(video)]


@needs_display
def test_the_whole_job_has_its_own_bar(app):
    app._on_item_started(3, 10, "Song 3")
    assert app.overall.winfo_manager() and app.lbl_overall.cget("text") == "3 / 10"
    app._show_progress(0.5, "50%")
    assert abs(app.overall_bar.get() - 0.25) < 0.01
    app._on_item_started(1, 1, "One")
    app._job_total = 0


@needs_display
def test_the_link_field_has_a_clear_button(app):
    from ui_helpers import pump
    app.url_entry.insert(0, "https://example.com/v")
    pump(app, timeout=0.15)
    assert app.btn_clear_url.winfo_manager()
    app.btn_clear_url.invoke()
    pump(app, timeout=0.15)
    assert app.url_entry.get() == "" and not app.btn_clear_url.winfo_manager()


@needs_display
def test_waiting_links_can_be_reordered_and_removed(app):
    app.link_queue = ["https://a", "https://b", "https://c"]
    app._show_link_queue()
    app.move_link(2, -1)
    assert app.link_queue == ["https://a", "https://c", "https://b"]
    app.move_link(0, -1)  # already first
    app.remove_link(1)
    assert app.link_queue == ["https://a", "https://b"]
    app.link_queue = [f"https://x/{i}" for i in range(8)]
    app._show_link_queue()
    assert len(app.queue_rows) == app.QUEUE_ROWS + 1  # five rows and "…and 3 more"


@needs_display
def test_long_titles_wrap_instead_of_widening_the_window(app):
    from ui_helpers import pump
    width = app.winfo_width()
    app._on_item_started(1, 1, "A very long title " * 20)
    pump(app, timeout=0.3)
    assert app.lbl_item.cget("wraplength") > 0 and app.winfo_width() == width


@needs_display
def test_buttons_explain_themselves(app):
    import ui
    tip = app.btn_analyze._tooltip
    assert "Enter" in tip.current_text()
    tip.show()
    assert tip.tip is not None
    tip.hide()
    assert isinstance(app.btn_clear_url._tooltip, ui.Tooltip)


@needs_display
def test_the_window_comes_back_where_it_was(monkeypatch):
    pytest.importorskip("customtkinter")
    from ui_helpers import isolate_settings, new_app, pump, ToolsOnlyManager
    import ui
    isolate_settings(monkeypatch)
    monkeypatch.setattr(ui, "DownloadManager", lambda: ToolsOnlyManager())
    window = new_app()
    pump(window, timeout=0.6)  # its own fit at start first
    window.geometry("1100x820+40+30")
    pump(window, lambda: window.winfo_height() == 820, timeout=3)
    window.destroy()
    window = new_app()
    try:
        pump(window, lambda: window.winfo_height() == 820, timeout=3)
        assert window.settings.window_geometry.startswith("1100x820")
        assert (window.winfo_width(), window.winfo_height()) == (1100, 820)
    finally:
        window.destroy()


@needs_display
def test_a_smaller_text_size_shrinks_the_window_again(app):
    from ui_helpers import pump
    import customtkinter as ctk
    app.hide_band()
    pump(app, timeout=1.0)
    start = app.winfo_height()
    try:
        app._on_setting_changed("text_size", "Larger")
        pump(app, lambda: app.winfo_height() > start, timeout=3)
        grown = app.winfo_height()
        assert grown > start
        app._on_setting_changed("text_size", "Normal")
        pump(app, lambda: app.winfo_height() < grown, timeout=3)
        assert abs(app.winfo_height() - start) <= 2  # back to the size for normal text
    finally:
        ctk.set_widget_scaling(1.0)


# --- History (UI-9, #17) -------------------------------------------------------------

@needs_display
def test_history_search_more_undo_and_download_again(app, tmp_path, monkeypatch):
    for i in range(70):
        title = f"Song {i}" + (" (Live)" if i >= 60 else "")
        app.history.add(title, str(tmp_path / f"{i}.mp3"), f"https://youtu.be/{i}", save=False)
    app.open_history()
    view = app.history_view
    assert len(view.rows) == view.STEP + 1  # 50 entries and "Show more"
    view.show_more()
    assert len(view.rows) == 70
    view.search("LIVE song")
    assert len(view.rows) == 10  # every word, any case
    view.search("")
    view.remove(str(tmp_path / "69.mp3"))
    assert view.notice.winfo_manager() and "not deleted" in view.lbl_notice.cget("text")
    assert len(app.history.entries) == 69
    view.undo()
    assert app.history.entries[0].title == "Song 69 (Live)"
    started = []
    monkeypatch.setattr(app, "start_analysis_thread", lambda: started.append(app.url_entry.get()))
    view.download_again(app.history.entries[0])
    assert started == ["https://youtu.be/69"] and app.history_view is None
