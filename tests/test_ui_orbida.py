"""The 1.0.0 additions to the window: History page, accent colours, auto-paste,
keeping the PC awake and the update button. They drive a real window."""

import json
import os
import sys

import pytest

ctk = pytest.importorskip("customtkinter")

import app_setup  # noqa: E402
import events  # noqa: E402
import ui  # noqa: E402
import ui_helpers  # noqa: E402
import updates  # noqa: E402
from results import ItemResult, ItemStatus, JobSummary  # noqa: E402
from ui_helpers import ToolsOnlyManager, make_app, new_app, pump  # noqa: E402
from version import __version__  # noqa: E402

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


@pytest.fixture
def app(monkeypatch):
    window = make_app(monkeypatch)
    yield window
    window.destroy()


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def test_every_accent_keeps_white_text_readable():
    from test_ui_design import _contrast
    for name, tokens in ui.ACCENTS.items():
        for mode in (0, 1):
            assert _contrast(ui.ON_ACCENT, tokens["accent"][mode]) >= 4.5, name


@needs_display
def test_finished_downloads_appear_in_history(app, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    app._job_mode = "Audio Only"
    app._on_item_done(ItemResult("https://a", "Clip", ItemStatus.COMPLETED, path=str(video)))
    app._on_item_done(ItemResult("https://b", "Broken", ItemStatus.FAILED, error="boom"))
    assert [(e.title, e.path, e.mode) for e in app.history.entries] == [("Clip", str(video), "Audio Only")]

    app.open_history()
    pump(app, timeout=0.2)
    view = app.history_view
    assert view.winfo_ismapped() and not app.main_frame.winfo_ismapped()
    texts = [w.cget("text") for w in _descendants(view.list) if isinstance(w, ctk.CTkLabel)]
    assert "Clip" in texts
    view.remove(str(video))
    assert app.history.entries == []
    texts = [w.cget("text") for w in _descendants(view.list) if isinstance(w, ctk.CTkLabel)]
    assert texts == ["Downloads you finish appear here."]

    app.event_generate("<Escape>")  # Esc leaves the page
    pump(app, timeout=0.2)
    assert app.history_view is None and app.main_frame.winfo_ismapped()


@needs_display
def test_history_is_not_kept_when_switched_off(app, tmp_path):
    app.settings.save_history = False
    app._on_item_done(ItemResult("https://a", "Clip", ItemStatus.COMPLETED, path=str(tmp_path / "c.mp4")))
    assert app.history.entries == []


@needs_display
def test_settings_and_history_pages_replace_each_other(app):
    app.open_settings()
    app.open_history()
    assert app.settings_view is None and app.history_view is not None
    app.toggle_settings()
    assert app.settings_view is not None and app.history_view is None
    app.close_settings()
    pump(app, timeout=0.2)
    assert app.main_frame.winfo_ismapped()


@needs_display
def test_accent_change_repaints_the_window(app):
    blue = ui.ACCENTS["Blue"]["accent"]
    try:
        app.open_settings()
        app._on_setting_changed("accent", "Blue")
        assert tuple(app.progress_bar.cget("progress_color")) == blue
        assert tuple(app.btn_analyze.cget("fg_color")) == blue
        assert tuple(app.settings_view.sw_history.cget("progress_color")) == blue
        assert ui.settings_store.load(app.settings_path, "unused").accent == "Blue"
        assert tuple(ui.primary_button(app, "x", None).cget("fg_color")) == blue  # new widgets too
    finally:
        ui.apply_accent("Indigo")


@needs_display
def test_copied_link_is_pasted_at_start(monkeypatch):
    ui_helpers.isolate_settings(monkeypatch)
    monkeypatch.setattr(ui, "DownloadManager", lambda: ToolsOnlyManager())
    window = new_app()
    try:
        pump(window, lambda: window.tools is not None)
        window.clipboard_clear()
        window.clipboard_append("  youtube.com/watch?v=abc")  # no scheme: not taken
        window.auto_paste()
        assert window.url_entry.get() == ""
        window.clipboard_clear()
        window.clipboard_append("https://www.youtube.com/watch?v=abc")
        window.auto_paste()
        assert window.url_entry.get() == "https://www.youtube.com/watch?v=abc"
        window.clipboard_clear()
        window.clipboard_append("https://other.example/v")
        window.auto_paste()  # a link already in the field is kept
        assert window.url_entry.get() == "https://www.youtube.com/watch?v=abc"
    finally:
        window.destroy()


@needs_display
def test_pc_is_kept_awake_only_while_downloading(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app_setup, "keep_awake", calls.append)
    app.set_queue([{"url": "https://youtu.be/a", "title": "A"}])
    monkeypatch.setattr(app, "_run_queue_with_cancel", lambda items, opts: None)
    app.start_download_queue()
    assert calls == [True]
    app._on_job_done(JobSummary())
    assert calls == [True, False]
    app.settings.keep_awake = False
    app.start_download_queue()
    app._on_job_done(JobSummary())
    assert calls == [True, False, False]


@needs_display
def test_download_options_carry_the_speed_setting(app, monkeypatch):
    seen = []
    monkeypatch.setattr(app, "_run_queue_with_cancel", lambda items, opts: seen.append(opts))
    app.settings.fragments = 8
    app.set_queue([{"url": "https://youtu.be/a", "title": "A"}])
    app.start_download_queue()
    pump(app, lambda: seen, timeout=1)
    assert seen[0]["concurrent_fragment_downloads"] == 8
    app._on_job_done(JobSummary())


def newer_release():
    return updates.Release("9.9.9", "orbida-v9.9.9", "https://example.invalid/release", "- Faster",
                           {"Orbida-Setup-9.9.9.exe": "https://x/setup", "SHA256SUMS.txt": "https://x/sums"})


@needs_display
def test_a_newer_version_shows_the_update_button(app):
    assert not app.btn_update.winfo_ismapped()
    app.events.post(events.UPDATE_CHECKED, release=newer_release(), error=None, manual=False)
    pump(app, timeout=0.3)
    assert app.btn_update.winfo_ismapped()
    assert "9.9.9" in app.btn_update.cget("text")
    app.open_settings()
    assert "9.9.9" in app.settings_view.lbl_update.cget("text")
    app.show_update_dialog()
    dialog = app.update_dialog
    assert dialog is not None and "9.9.9" in dialog.title() + "".join(
        w.cget("text") for w in _descendants(dialog) if isinstance(w, ctk.CTkLabel))
    dialog.later()
    assert app.update_dialog is None


@needs_display
def test_manual_check_reports_the_latest_version(app):
    app.open_settings()
    app._on_update_checked(release=None, error=None, manual=True)
    assert __version__ in app.settings_view.lbl_update.cget("text")
    app._on_update_checked(release=None, error="offline", manual=True)
    assert app.settings_view.lbl_update.cget("text") == ui.tr("update.failed")
    assert not app.btn_update.winfo_ismapped()


@needs_display
def test_update_waits_for_a_running_download(app, monkeypatch):
    shown = []
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: shown.append(a))
    app._job_kind = "download"
    try:
        assert app.start_update(newer_release()) is False
        assert shown
    finally:
        app._job_kind = None


@needs_display
def test_verified_installer_is_started_and_the_app_closes(monkeypatch):
    ui_helpers.isolate_settings(monkeypatch)
    monkeypatch.setattr(ui, "DownloadManager", lambda: ToolsOnlyManager())
    started = []
    monkeypatch.setattr(ui.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))

    class Instance:
        released = False

        def release(self):
            self.released = True
    instance = Instance()
    window = ui.App(instance=instance)
    window._on_update_ready("/tmp/Orbida-Setup-9.9.9.exe")
    assert started == [updates.installer_command("/tmp/Orbida-Setup-9.9.9.exe")]
    assert instance.released
    assert window._closing
    with pytest.raises(Exception):
        window.winfo_exists()  # destroyed


@needs_display
def test_update_note_is_logged_once_after_an_update(monkeypatch):
    ui_helpers.isolate_settings(monkeypatch)
    folder = os.path.join(os.environ["LOCALAPPDATA"], "Orbida")
    os.makedirs(folder)
    with open(os.path.join(folder, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"last_version": "0.9.0"}, f)
    monkeypatch.setattr(ui, "DownloadManager", lambda: ToolsOnlyManager())
    window = new_app()
    try:
        assert f"was updated to {__version__}" in window.console.get("1.0", "end")
        assert ui.settings_store.load(window.settings_path, "unused").last_version == __version__
    finally:
        window.destroy()
