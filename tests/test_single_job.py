"""One job at a time, and no stale queue (ISSUES.md #14, #15, #27, #28, #30).

Drives a real window, so it needs a display (use xvfb-run on Linux).
"""

import os
import sys
import threading
import time

import pytest

ctk = pytest.importorskip("customtkinter")
pytest.importorskip("tkinter.messagebox")

import ui  # noqa: E402

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


class BlockingManager:
    """fetch_info blocks until released, so a job stays 'running'."""

    def __init__(self, info):
        self.info = info
        self.release = threading.Event()
        self.calls = 0

    def fetch_info(self, url, log_callback=None):
        self.calls += 1
        self.release.wait(5)
        return self.info


def pump(app, until, timeout=5):
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)
    return until()


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: None)
    window = ui.App()
    yield window
    window.destroy()


def type_url(app, url):
    app.url_entry.delete(0, "end")
    app.url_entry.insert(0, url)
    app._on_url_changed()


@needs_display
def test_second_analysis_is_refused_while_one_runs(app):
    manager = BlockingManager({"title": "Clip"})
    app.manager = manager
    type_url(app, "https://example.com/a")

    app.start_analysis_thread()
    app.start_analysis_thread()
    app.start_download_queue()

    assert pump(app, lambda: manager.calls == 1)
    assert app.is_busy()
    assert app.btn_analyze.cget("state") == "disabled"
    assert app.url_entry.cget("state") == "disabled"
    assert app.btn_download.cget("state") == "disabled"

    manager.release.set()
    assert pump(app, lambda: not app.is_busy())
    assert manager.calls == 1
    assert app.btn_analyze.cget("state") == "normal"
    assert app.btn_download.cget("text") == "DOWNLOAD (1)"


@needs_display
def test_editing_url_clears_the_analysed_queue(app):
    manager = BlockingManager({"title": "Clip"})
    manager.release.set()
    app.manager = manager
    type_url(app, "https://example.com/a")
    app.start_analysis_thread()
    assert pump(app, lambda: app.download_queue)

    type_url(app, "https://example.com/other")

    assert app.download_queue == []
    assert app.btn_download.cget("state") == "disabled"


@needs_display
def test_new_analysis_resets_queue_and_progress(app):
    manager = BlockingManager({"title": "Clip"})
    app.manager = manager
    app.set_queue([{"url": "old", "title": "Old"}])
    app._show_progress(0.7, "70%")
    type_url(app, "https://example.com/a")

    app.start_analysis_thread()

    assert app.download_queue == []
    assert app.progress_bar.get() == 0
    manager.release.set()
    assert pump(app, lambda: not app.is_busy())


@needs_display
def test_worker_thread_is_daemon_and_tracked(app):
    manager = BlockingManager({"title": "Clip"})
    app.manager = manager
    type_url(app, "https://example.com/a")
    app.start_analysis_thread()

    assert app._job_thread is not None and app._job_thread.daemon
    manager.release.set()
    assert pump(app, lambda: not app.is_busy())
    assert app._job_thread is None
