"""UI event routing tests.

The worker-side tests run the real ``App`` worker methods on a stand-in object
that has no widgets at all, so any direct widget access from a worker thread
fails the test. The Tk test drives a real window and needs a display; it is
skipped when none is available.
"""

import os
import sys
import threading
import time

import pytest

ctk = pytest.importorskip("customtkinter")
messagebox = pytest.importorskip("tkinter.messagebox")

import events  # noqa: E402
import ui  # noqa: E402
from ui_helpers import ToolsOnlyManager, pump  # noqa: E402
from results import ItemResult, ItemStatus  # noqa: E402


class FakeManager:
    def __init__(self, info=None, fail_urls=(), raise_on_fetch=None):
        self.info = info
        self.fail_urls = set(fail_urls)
        self.raise_on_fetch = raise_on_fetch
        self.downloaded = []
        self.threads = set()

    def fetch_info(self, url):
        self.threads.add(threading.get_ident())
        if self.raise_on_fetch:
            raise self.raise_on_fetch
        return self.info

    def download_video(self, url, options, progress_hook=None, log_callback=None, title=None, cancel_event=None):
        self.threads.add(threading.get_ident())
        progress_hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})
        if url in self.fail_urls:
            raise RuntimeError(f"cannot download {url}")
        self.downloaded.append(url)
        progress_hook({"status": "finished"})
        return ItemResult(url, title, ItemStatus.COMPLETED, path=f"/out/{url}.mp4")


class WorkerSide:
    """Only what worker threads may use: the event queue and the manager."""

    log = ui.App.log
    run_analysis = ui.App.run_analysis
    run_queue = ui.App.run_queue
    progress_hook = ui.App.progress_hook

    def __init__(self, manager):
        self.events = events.EventQueue()
        self.manager = manager

    def drain(self):
        out = []
        while True:
            try:
                out.append(self.events._queue.get_nowait())
            except Exception:
                return out


def run_in_thread(fn, *args):
    t = threading.Thread(target=fn, args=args)
    t.start()
    t.join(5)
    assert not t.is_alive()


def test_analysis_single_video_posts_done_event():
    info = {"title": "Clip", "original_url": "https://example.com/v"}
    w = WorkerSide(FakeManager(info=info))
    run_in_thread(w.run_analysis, "https://example.com/v")
    evs = w.drain()
    assert [e.kind for e in evs] == [events.LOG, events.ANALYSIS_DONE]
    assert evs[0].payload == {"message": "Fetching info..."}
    analysis = evs[1].payload["analysis"]
    assert evs[1].payload["url"] == "https://example.com/v"
    assert [(i.url, i.title) for i in analysis.items] == [("https://example.com/v", "Clip")]


@pytest.mark.parametrize(
    "manager, message",
    [
        (FakeManager(info=None), "ERROR: Info is None."),
        (FakeManager(info={"error": "private"}), "FAILED: private"),
        (FakeManager(raise_on_fetch=ValueError("boom")), "Error: boom"),
    ],
)
def test_analysis_failures_post_failed_event(manager, message):
    w = WorkerSide(manager)
    run_in_thread(w.run_analysis, "u")
    last = w.drain()[-1]
    assert last.kind == events.ANALYSIS_FAILED
    assert last.payload == {"message": message}


def test_run_queue_posts_logs_progress_and_job_done_without_widgets():
    manager = FakeManager(fail_urls={"b"})
    w = WorkerSide(manager)
    items = [{"url": "a", "title": "A"}, {"url": "b", "title": "B"}]
    run_in_thread(w.run_queue, items, {})
    evs = w.drain()
    assert manager.downloaded == ["a"]
    assert threading.get_ident() not in manager.threads
    logs = [e.payload["message"] for e in evs if e.kind == events.LOG]
    assert logs == ["[1/2] A", "[2/2] B"]
    progress = [e.payload for e in evs if e.kind == events.PROGRESS]
    assert progress[0] == {"fraction": 0.5, "text": "50.0%"}
    items = [e.payload["result"] for e in evs if e.kind == events.ITEM_DONE]
    assert [(r.url, r.status) for r in items] == [("a", ItemStatus.COMPLETED), ("b", ItemStatus.FAILED)]
    assert items[1].error == "cannot download b"
    assert evs[-1].kind == events.JOB_DONE
    summary = evs[-1].payload["summary"]
    assert summary.headline() == "1 completed, 1 failed"


def test_run_queue_posts_job_done_even_if_worker_crashes():
    w = WorkerSide(FakeManager())
    with pytest.raises(KeyError):
        w.run_queue([{"no_url": 1}], {})
    assert w.drain()[-1].kind == events.JOB_DONE


def _has_display():
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY"))


@pytest.mark.skipif(not _has_display(), reason="needs a display for Tk")
def test_real_window_applies_worker_events_on_main_thread(monkeypatch):
    shown = []
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: shown.append(threading.get_ident()))
    monkeypatch.setattr(ui.messagebox, "showwarning", lambda *a, **k: shown.append("warning"))
    monkeypatch.setattr(ui, "DownloadManager", lambda: ToolsOnlyManager())
    app = ui.App()
    pump(app, lambda: app.tools is not None)
    try:
        app.manager = FakeManager()
        app.set_queue([{"url": "a", "title": "A"}])
        app.start_download_queue()

        deadline = time.monotonic() + 5
        while not shown and time.monotonic() < deadline:
            app.update()
            time.sleep(0.01)

        assert shown == [threading.get_ident()]
        assert app.btn_download.cget("text") == "DOWNLOAD (1)"
        assert app.lbl_progress.cget("text") == "Complete"
        assert app.progress_bar.get() == 1
        console = app.console.get("1.0", "end")
        assert "> Welcome!" in console
        assert "> [1/1] A" in console
        assert "> Saved: /out/a.mp4" in console
        assert "> Result: 1 completed" in console
    finally:
        app.destroy()
