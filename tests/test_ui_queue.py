"""Link queue, playlist selection memory and the Black theme in the window."""

import os
import sys
import threading

import pytest

ctk = pytest.importorskip("customtkinter")

import playlist  # noqa: E402
import ui  # noqa: E402
from results import ItemResult, ItemStatus  # noqa: E402
from ui_helpers import make_app, pump  # noqa: E402

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


class QueueManager:
    """Analyses every link as one video; the first download waits for ``release``."""

    def __init__(self, tools):
        self.tools = tools
        self.release = threading.Event()
        self.downloaded = []

    def ensure_tools(self):
        return self.tools

    def fetch_info(self, url, log_callback=None):
        return {"title": url.rsplit("/", 1)[-1], "webpage_url": url}

    def download_video(self, url, options, progress_hook=None, log_callback=None, title=None,
                       cancel_event=None, **_kw):
        if not self.downloaded:
            self.release.wait(5)
        self.downloaded.append(url)
        if cancel_event is not None and cancel_event.is_set():
            return ItemResult(url, title, ItemStatus.CANCELLED, error="Cancelled by user")
        return ItemResult(url, title, ItemStatus.COMPLETED)


@pytest.fixture
def app(monkeypatch, tmp_path):
    window = make_app(monkeypatch)
    window.manager = QueueManager(window.tools)
    window.settings.show_summary = False
    window.download_folder = str(tmp_path)
    yield window
    window.manager.release.set()
    window.destroy()


def _analyze_and_start(app, url):
    app.url_entry.delete(0, "end")
    app.url_entry.insert(0, url)
    app.start_analysis_thread()
    assert pump(app, lambda: app.download_queue)
    app.start_download_queue()
    assert app._job_kind == "download"


@needs_display
def test_links_added_while_downloading_download_next(app):
    _analyze_and_start(app, "https://example.com/first")
    assert app.btn_analyze.cget("text") == ui.tr("queue.add")
    assert app.url_entry.cget("state") == "normal"
    for url in ("https://example.com/second", "https://example.com/third"):
        app.url_entry.insert(0, url)
        app.start_analysis_thread()  # the button now adds to the queue
        assert app.url_entry.get() == ""
    assert app.link_queue == ["https://example.com/second", "https://example.com/third"]
    assert app.lbl_queue.cget("text") == ui.tr("queue.waiting", count=2)
    app.manager.release.set()
    assert pump(app, lambda: len(app.manager.downloaded) == 3 and not app.is_busy(), timeout=10)
    assert app.manager.downloaded == ["https://example.com/first", "https://example.com/second",
                                      "https://example.com/third"]
    assert app.link_queue == [] and not app.queue_row.winfo_ismapped()


@needs_display
def test_cancel_also_clears_the_queue(app):
    _analyze_and_start(app, "https://example.com/first")
    app.url_entry.insert(0, "https://example.com/second")
    app.add_to_queue()
    app.cancel_job()
    app.manager.release.set()
    assert pump(app, lambda: not app.is_busy(), timeout=10)
    pump(app, timeout=0.3)
    assert app.link_queue == [] and app.manager.downloaded == ["https://example.com/first"]


@needs_display
def test_playlist_entries_downloaded_before_start_unticked(app, monkeypatch):
    items = [playlist.QueueItem(url=f"https://www.youtube.com/watch?v=v{i}", title=f"V{i}", index=i)
             for i in (1, 2, 3)]
    analysis = playlist.AnalysisResult(title="List", items=items, is_playlist=True)
    app.history.add("V2", "/x/v2.mp4", "https://youtu.be/v2", "Video + Audio")
    app._on_analysis_done(analysis, "https://www.youtube.com/playlist?list=L")
    dialog = app.playlist_dialog
    try:
        pump(app, timeout=0.2)
        assert [item.title for item in dialog.selected_items()] == ["V1", "V3"]
        dialog.select_all()
        assert len(dialog.selected_items()) == 3
        dialog.select_new()
        assert [item.title for item in dialog.selected_items()] == ["V1", "V3"]
    finally:
        dialog.cancel()


@needs_display
def test_black_theme_makes_the_dark_surfaces_black(app):
    try:
        app._on_setting_changed("theme", "Black")
        assert ctk.get_appearance_mode() == "Dark"
        assert ui.BG[1] == "#000000" and tuple(app.cget("fg_color")) == ui.BG
        assert app.log_card.cget("fg_color")[1] == "#121212"
        app._on_setting_changed("theme", "Dark")
        assert ui.BG[1] != "#000000" and app.log_card.cget("fg_color")[1] == ui.CARD[1]
    finally:
        ui.apply_pure_black(False)
        ctk.set_appearance_mode("System")
