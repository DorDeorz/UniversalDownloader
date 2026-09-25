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
        first.seg_theme.set("Light")
        first._on_theme_changed("Light")
    finally:
        first.destroy()
    second = new_app()
    try:
        assert second.cmb_mode.get() == "Audio Only"
        assert second.cmb_format.get() == "flac"
        assert second.cmb_quality.get() == "192 kbps"
        assert second.seg_theme.get() == "Light"
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
