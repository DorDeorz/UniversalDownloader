"""Tests for the redesigned main window: link checks, saved settings,
progress details and the end-of-job display. They drive a real window."""

import os
import sys

import pytest

ctk = pytest.importorskip("customtkinter")

import events  # noqa: E402
import playlist  # noqa: E402
import ui  # noqa: E402
from results import ItemResult, ItemStatus, JobSummary  # noqa: E402
from ui_helpers import ToolsOnlyManager, make_app, new_app, pump  # noqa: E402

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


@pytest.mark.parametrize("seconds, text", [(0, "0:00"), (65, "1:05"), (3599, "59:59"), (3600, "1:00:00"),
                                           (7384.9, "2:03:04")])
def test_format_duration(seconds, text):
    assert ui.format_duration(seconds) == text


@pytest.fixture
def app(monkeypatch):
    window = make_app(monkeypatch)
    yield window
    window.destroy()


@needs_display
@pytest.mark.parametrize("text", ["", "not a link", "ftp://example.com/video", "localhostx"])
def test_invalid_link_is_rejected_without_starting_a_job(app, text):
    app.url_entry.insert(0, text)
    app.start_analysis_thread()
    assert not app.is_busy()
    assert app.lbl_media.cget("text_color") == ui.DANGER
    assert app.lbl_media.cget("text")


@needs_display
def test_link_without_scheme_is_completed(app, monkeypatch):
    started = []
    monkeypatch.setattr(app, "_start_job", lambda kind, target, *args: started.append(args) or False)
    app.url_entry.insert(0, "youtube.com/watch?v=abc")
    app.start_analysis_thread()
    assert app.url_entry.get() == "https://youtube.com/watch?v=abc"
    assert started == [("https://youtube.com/watch?v=abc",)]


@needs_display
def test_choices_are_remembered_between_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(ui, "DownloadManager", lambda: ToolsOnlyManager())
    first = new_app()
    try:
        first.cmb_mode.set("Audio Only")
        first._on_mode_changed("Audio Only")
        first.cmb_format.set("flac")
        first.cmb_quality.set("192 kbps")
        first._save_settings()
        first._on_setting_changed("theme", "Light")
        first._on_setting_changed("show_summary", False)
    finally:
        first.destroy()
    second = new_app()
    try:
        assert second.cmb_mode.get() == "Audio Only"
        assert second.cmb_format.get() == "flac"
        assert second.cmb_quality.get() == "192 kbps"
        assert second.settings.theme == "Light"
        assert second.settings.show_summary is False
    finally:
        second.destroy()
        ctk.set_appearance_mode("System")


@needs_display
def test_progress_shows_item_speed_and_stage(app):
    app.events.post(events.ITEM_STARTED, position=2, total=5, title="Highway Lights")
    app.events.post(events.PROGRESS, fraction=0.5, text="50.0%", detail="1.0 MB/s, 0:03 left")
    pump(app, lambda: app.lbl_progress.cget("text") == "50.0%")
    assert app.lbl_item.cget("text") == "2 of 5:  Highway Lights"
    assert app.lbl_detail.cget("text") == "1.0 MB/s, 0:03 left"
    app.events.post(events.STAGE, text="Converting audio...")
    pump(app, lambda: app.lbl_detail.cget("text") == "Converting audio...")
    assert app.lbl_detail.cget("text") == "Converting audio..."


@needs_display
def test_finished_job_colours_the_progress_bar(app):
    app._job_kind = "download"
    mixed = JobSummary([ItemResult("a", "A", ItemStatus.COMPLETED, path="x"),
                        ItemResult("b", "B", ItemStatus.FAILED, error="403")])
    app._on_job_done(mixed)
    assert app.progress_bar.cget("progress_color") == ui.WARNING
    assert app.progress_bar.get() == pytest.approx(0.5)
    assert app.btn_retry.cget("text") == "Retry 1 failed"

    app._job_kind = "download"
    app._on_job_done(JobSummary([ItemResult("a", "A", ItemStatus.COMPLETED, path="x")]))
    assert app.progress_bar.cget("progress_color") == ui.SUCCESS
    assert app.lbl_progress.cget("text") == "Complete"

    app._on_item_started(1, 1, "Next")
    assert app.progress_bar.cget("progress_color") == ui.ACCENT


@needs_display
def test_disabled_download_button_uses_muted_colour(app):
    assert app.btn_download.cget("state") == "disabled"
    assert app.btn_download.cget("fg_color") == ui.ACCENT_DISABLED
    app.set_queue([{"url": "https://example.com/v", "title": "v"}])
    assert app.btn_download.cget("state") == "normal"
    assert app.btn_download.cget("fg_color") == ui.ACCENT


@needs_display
def test_playlist_dialog_names_how_many_will_be_queued(app):
    info = {"title": "Mix", "entries": [{"id": f"v{i}", "title": f"Song {i}", "ie_key": "Youtube"}
                                         for i in range(3)]}
    chosen = []
    dialog = ui.PlaylistSelector(app, playlist.analyze(info, "https://youtube.com/playlist?list=x"),
                                 chosen.append)
    try:
        assert dialog.btn_confirm.cget("text") == "Add 3 to queue"
        dialog.select_none()
        assert dialog.btn_confirm.cget("text") == "Nothing selected"
        assert dialog.btn_confirm.cget("state") == "disabled"
        dialog.vars[1].set(1)
        dialog._update_count()
        dialog.confirm_selection()
        assert [item.title for item in chosen[0]] == ["Song 1"]
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


@pytest.mark.parametrize("path, limit, expected", [
    ("C:\\short", 64, "C:\\short"),
    ("C:\\Users\\someone\\Downloads\\UniversalVideos", 20, "C:\\Us...versalVideos"),
])
def test_shorten_path(path, limit, expected):
    assert ui.shorten_path(path, limit) == expected
    assert len(ui.shorten_path(path, limit)) <= limit


@needs_display
def test_settings_dialog_applies_and_saves_changes(app, monkeypatch):
    scales = []
    monkeypatch.setattr(ui.ctk, "set_widget_scaling", scales.append)
    app.open_settings()
    dialog = app.settings_dialog
    assert dialog.seg_theme.get() == app.settings.theme
    app.open_settings()
    assert app.settings_dialog is dialog  # one dialog at a time

    dialog.seg_text.set("Larger")
    dialog.on_change("text_size", "Larger")
    dialog.sw_open.toggle()
    assert scales == [1.3]
    assert app.settings.text_size == "Larger"
    assert app.settings.open_folder_when_done is True
    saved = ui.settings_store.load(app.settings_path, "unused")
    assert (saved.text_size, saved.open_folder_when_done) == ("Larger", True)
    dialog.close()
    assert not dialog.winfo_exists()


@needs_display
@pytest.mark.parametrize("show_summary, open_folder", [(True, False), (False, True)])
def test_finish_actions_follow_settings(app, monkeypatch, show_summary, open_folder):
    shown, opened = [], []
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(app, "open_folder", lambda: opened.append(True))
    app.settings.show_summary, app.settings.open_folder_when_done = show_summary, open_folder
    app._job_kind = "download"
    app._on_job_done(JobSummary([ItemResult("a", "A", ItemStatus.COMPLETED, path="x")]))
    assert bool(shown) is show_summary
    assert bool(opened) is open_folder


@needs_display
def test_folder_is_not_opened_when_nothing_completed(app, monkeypatch):
    opened = []
    monkeypatch.setattr(app, "open_folder", lambda: opened.append(True))
    app.settings.open_folder_when_done = True
    app._job_kind = "download"
    app._on_job_done(JobSummary([ItemResult("a", "A", ItemStatus.FAILED, error="x")]))
    assert opened == []


@needs_display
def test_keyboard_shortcuts(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "start_download_queue", lambda: calls.append("download"))
    monkeypatch.setattr(app, "start_analysis_thread", lambda: calls.append("analyze"))
    monkeypatch.setattr(app, "cancel_job", lambda: calls.append("cancel"))
    monkeypatch.setattr(app, "open_settings", lambda: calls.append("settings"))
    app._bind_shortcuts()
    app.set_queue([{"url": "https://example.com/v", "title": "v"}])
    entry = app.url_entry._entry
    entry.focus_force()
    pump(app, lambda: app.focus_get() is entry, timeout=2)
    for sequence in ("<Control-Return>", "<Escape>", "<Control-comma>"):
        entry.event_generate(sequence)
    pump(app, timeout=0.3)
    assert calls == ["download", "cancel", "settings"]

    calls.clear()
    app.set_queue([])  # Download disabled: the shortcut does nothing
    entry.event_generate("<Control-Return>")
    pump(app, timeout=0.3)
    assert calls == []


def _contrast(fg, bg):
    def luminance(colour):
        channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    high, low = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("fg, bgs", [
    (ui.TEXT, (ui.BG, ui.CARD, ui.FIELD, ui.SECONDARY)),
    (ui.MUTED, (ui.BG, ui.CARD, ui.FIELD)),
    (ui.SUCCESS, (ui.CARD, ui.FIELD)),
    (ui.DANGER, (ui.CARD,)),
    (ui.WARNING, (ui.CARD,)),
    ((ui.ON_ACCENT, ui.ON_ACCENT), (ui.ACCENT,)),
])
def test_text_colours_meet_wcag_aa(fg, bgs):
    for bg in bgs:
        for mode in (0, 1):  # light, dark
            assert _contrast(fg[mode], bg[mode]) >= 4.5, (fg[mode], bg[mode])


@pytest.fixture
def larger_text():
    ctk.set_widget_scaling(1.3)
    yield
    ctk.set_widget_scaling(1.0)


def _outer_bottom(window):
    return window.winfo_y() + ui.WINDOW_FRAME_PX + window.winfo_height()


@needs_display
@pytest.mark.parametrize("area_height", [1040, 728])  # 1080p and 768p screens minus a taskbar
def test_larger_text_stays_above_the_taskbar(monkeypatch, larger_text, area_height):
    monkeypatch.setattr(ui, "work_area", lambda window: (0, 0, 1920, area_height))
    window = make_app(monkeypatch)
    try:
        window.geometry("+0+300")  # start low, as a restored window might
        window._fit_to_content()
        pump(window, timeout=0.5)
        assert _outer_bottom(window) <= area_height
        # Everything is reachable: it fits, or the content scrolls.
        content = window.main_frame.winfo_reqheight()
        fits = content <= window._scroll_canvas.winfo_height() + 1
        assert fits != window.content_scrolls
        assert window.content_scrolls is (area_height < 1000)
    finally:
        window.destroy()


@needs_display
def test_activity_box_takes_spare_height(app):
    app.geometry("1040x1000")
    pump(app, timeout=0.5)
    tall = app.console.cget("height")
    assert tall > app.LOG_HEIGHT
    assert not app.content_scrolls
    app.geometry("1040x640")
    pump(app, timeout=0.5)
    assert app.console.cget("height") == app.LOG_MIN_HEIGHT


@needs_display
def test_settings_dialog_grows_with_text_size_and_fits_the_screen(app, monkeypatch, larger_text):
    monkeypatch.setattr(ui, "work_area", lambda window: (0, 0, 1920, 1040))
    app.open_settings()
    dialog = app.settings_dialog
    pump(app, timeout=0.3)
    scale = dialog._get_window_scaling()
    assert dialog.winfo_width() >= round(560 * 1.3 * scale) - 2
    assert _outer_bottom(dialog) <= 1040


@needs_display
def test_dialogs_get_the_app_icon(app, monkeypatch):
    windows = []
    monkeypatch.setattr(ui, "set_window_icon", windows.append)
    app.open_settings()
    info = {"title": "Mix", "entries": [{"id": "a", "title": "A", "ie_key": "Youtube"}]}
    selector = ui.PlaylistSelector(app, playlist.analyze(info, "https://youtube.com/playlist?list=x"),
                                   lambda items: None)
    pump(app, timeout=0.5)  # also after CustomTkinter sets its own icon
    assert windows.count(app.settings_dialog) == 2
    assert windows.count(selector) == 2
    selector.cancel()


def test_place_on_screen_caps_size_and_keeps_window_visible():
    class Window:
        def __init__(self):
            self.calls = {}

        def _get_window_scaling(self):
            return 1.25

        def winfo_x(self):
            return 100

        def winfo_y(self):
            return 500

        def minsize(self, w, h):
            self.calls["minsize"] = (w, h)

        def geometry(self, spec):
            self.calls["geometry"] = spec

    window = Window()
    original = ui.work_area
    ui.work_area = lambda w: (0, 0, 1920, 1040)
    try:
        used = ui.place_on_screen(window, 1300, 1300, min_px=(1125, 1200))
    finally:
        ui.work_area = original
    assert used == (1300, 1040 - ui.WINDOW_FRAME_PX)
    # Sizes are in CustomTkinter units (pixels / 1.25); the position moves up.
    assert window.calls["geometry"] == f"1040x{round(992 / 1.25)}+100+0"
    assert window.calls["minsize"] == (900, int(992 / 1.25))
