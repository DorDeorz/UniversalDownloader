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

    def download_video(self, url, options, progress_hook, complete_callback, error_callback):
        self.threads.add(threading.get_ident())
        progress_hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})
        if url in self.fail_urls:
            raise RuntimeError(f"cannot download {url}")
        self.downloaded.append(url)
        progress_hook({"status": "finished"})
        complete_callback(url)


class WorkerSide:
    """Only what worker threads may use: the event queue and the manager."""

    log = ui.App.log
    run_analysis = ui.App.run_analysis
    run_queue = ui.App.run_queue
    progress_hook = ui.App.progress_hook
    on_error = ui.App.on_error

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
    kinds = [(e.kind, e.payload) for e in w.drain()]
    assert kinds == [
        (events.LOG, {"message": "Fetching info..."}),
        (events.ANALYSIS_DONE, {"info": info, "url": "https://example.com/v"}),
    ]


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
    assert logs == ["[1/2] A", "[2/2] B", "Failed: cannot download b"]
    progress = [e.payload for e in evs if e.kind == events.PROGRESS]
    assert progress[0] == {"fraction": 0.5, "text": "50.0%"}
    assert evs[-1].kind == events.JOB_DONE
    assert evs[-1].payload == {"total": 2}


def test_run_queue_posts_job_done_even_if_worker_crashes():
    w = WorkerSide(FakeManager())
    with pytest.raises(KeyError):
        w.run_queue([{"no_url": 1}], {})
    assert w.drain()[-1].kind == events.JOB_DONE


def test_on_error_posts_log():
    w = WorkerSide(FakeManager())
    w.on_error("oops")
    assert [(e.kind, e.payload) for e in w.drain()] == [(events.LOG, {"message": "Error: oops"})]


def _has_display():
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY"))


@pytest.mark.skipif(not _has_display(), reason="needs a display for Tk")
def test_real_window_applies_worker_events_on_main_thread(monkeypatch):
    shown = []
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: shown.append(threading.get_ident()))
    app = ui.App()
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
        assert "> FINISHED." in console
    finally:
        app.destroy()
