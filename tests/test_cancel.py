"""Cancellation, retries and controlled shutdown (ISSUES.md #13, #14, #42, #45, #85, #88)."""

import os
import sys
import threading
import time

import pytest

import logic
from results import ItemResult, ItemStatus


def test_network_timeouts_and_retries_are_bounded():
    opts = logic.base_ydl_options()
    assert opts["socket_timeout"] == logic.SOCKET_TIMEOUT
    assert opts["retries"] == opts["fragment_retries"] == logic.RETRIES


def test_cancel_before_start_does_no_network(manager, fake_ydl, tmp_path):
    ev = threading.Event()
    ev.set()

    result = manager.download_video("https://youtu.be/abc", {"save_path": str(tmp_path)}, cancel_event=ev)

    assert result.status is ItemStatus.CANCELLED
    assert fake_ydl.instances == []


def test_cancel_during_download_removes_partial_files(manager, fake_ydl, tmp_path, monkeypatch):
    ev = threading.Event()
    part = tmp_path / "YouTube" / "clip.f137.mp4"
    part.parent.mkdir()
    for name in ("clip.f137.mp4.part", "clip.f137.mp4.ytdl", "clip.f137.mp4.part-Frag3"):
        (part.parent / name).write_bytes(b"x")
    keep = part.parent / "other.mp4"
    keep.write_bytes(b"done earlier")

    def process(self, info, download=True):
        for hook in self.params["progress_hooks"]:
            hook({"status": "downloading", "filename": str(part), "tmpfilename": str(part) + ".part",
                  "downloaded_bytes": 1, "total_bytes": 10})
            ev.set()
            hook({"status": "downloading", "filename": str(part), "tmpfilename": str(part) + ".part",
                  "downloaded_bytes": 2, "total_bytes": 10})
        raise AssertionError("cancel should have stopped the download")

    monkeypatch.setattr(fake_ydl, "process_ie_result", process)
    lines = []

    result = manager.download_video("https://youtu.be/abc", {"save_path": str(tmp_path)},
                                    log_callback=lines.append, cancel_event=ev)

    assert result.status is ItemStatus.CANCELLED
    assert sorted(os.listdir(part.parent)) == ["other.mp4"]
    assert "Removed 3 partial file(s)" in lines


def test_cancel_during_postprocessing(manager, fake_ydl, tmp_path, monkeypatch):
    ev = threading.Event()

    def process(self, info, download=True):
        ev.set()
        for hook in self.params["postprocessor_hooks"]:
            hook({"status": "started", "postprocessor": "Merger"})
        raise AssertionError("cancel should have stopped postprocessing")

    monkeypatch.setattr(fake_ydl, "process_ie_result", process)

    result = manager.download_video("https://youtu.be/abc", {"save_path": str(tmp_path)}, cancel_event=ev)

    assert result.status is ItemStatus.CANCELLED


def test_error_without_cancel_is_still_failed(manager, fake_ydl, tmp_path):
    fake_ydl.download_error = RuntimeError("HTTP Error 403")

    result = manager.download_video("https://youtu.be/abc", {"save_path": str(tmp_path)},
                                    cancel_event=threading.Event())

    assert result.status is ItemStatus.FAILED


# --- queue and window ----------------------------------------------------

ctk = pytest.importorskip("customtkinter")
pytest.importorskip("tkinter.messagebox")

import events  # noqa: E402
import ui  # noqa: E402

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


class SlowManager:
    """Each download waits for cancel (or a short timeout)."""

    def __init__(self, fail=(), block=True):
        self.fail = set(fail)
        self.block = block
        self.started = []

    def download_video(self, url, options, progress_hook=None, log_callback=None, title=None, cancel_event=None):
        self.started.append(url)
        if url in self.fail:
            return ItemResult(url, title, ItemStatus.FAILED, error="HTTP 403")
        if self.block and cancel_event is not None and cancel_event.wait(5):
            return ItemResult(url, title, ItemStatus.CANCELLED, error="Cancelled by user")
        return ItemResult(url, title, ItemStatus.COMPLETED, path=f"/out/{url}")


class Worker:
    run_queue = ui.App.run_queue
    progress_hook = ui.App.progress_hook
    log = ui.App.log

    def __init__(self, manager):
        self.manager = manager
        self.events = events.EventQueue()


def test_run_queue_marks_remaining_items_cancelled():
    manager = SlowManager()
    w = Worker(manager)
    ev = threading.Event()
    items = [{"url": u, "title": u.upper()} for u in ("a", "b", "c")]
    t = threading.Thread(target=w.run_queue, args=(items, {}, ev))
    t.start()
    while not manager.started:
        time.sleep(0.01)
    ev.set()
    t.join(5)

    assert manager.started == ["a"]
    summary = [e for e in list(w.events._queue.queue) if e.kind == events.JOB_DONE][0].payload["summary"]
    assert [r.status for r in summary.results] == [ItemStatus.CANCELLED] * 3
    assert summary.title() == "Download cancelled"


def pump(app, until, timeout=5):
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)
    return until()


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(ui.messagebox, "showwarning", lambda *a, **k: None)
    window = ui.App()
    yield window
    try:
        window.destroy()
    except Exception:
        pass


@needs_display
def test_cancel_button_stops_download(app):
    manager = SlowManager()
    app.manager = manager
    app.set_queue([{"url": "a", "title": "A"}, {"url": "b", "title": "B"}])
    app.start_download_queue()
    assert app.btn_cancel.cget("state") == "normal"

    app.cancel_job()

    assert pump(app, lambda: not app.is_busy())
    assert app.last_summary.headline() == "2 cancelled"
    assert app.btn_cancel.cget("state") == "disabled"


@needs_display
def test_retry_failed_requeues_only_failed_items(app):
    manager = SlowManager(fail={"b"}, block=False)
    app.manager = manager
    app.set_queue([{"url": "a", "title": "A"}, {"url": "b", "title": "B"}])
    app.start_download_queue()
    assert pump(app, lambda: not app.is_busy())
    assert app.btn_retry.cget("text") == "RETRY FAILED (1)"

    manager.started.clear()
    manager.fail.clear()
    app.retry_failed()
    assert pump(app, lambda: not app.is_busy())

    assert manager.started == ["b"]
    assert app.btn_retry.cget("state") == "disabled"


@needs_display
def test_close_during_download_cancels_and_waits(app, monkeypatch):
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: True)
    destroyed = []
    real_destroy = app.destroy
    monkeypatch.setattr(app, "destroy", lambda: (destroyed.append(app._job_thread.is_alive()), real_destroy()))
    app.manager = SlowManager()
    app.set_queue([{"url": "a", "title": "A"}])
    app.start_download_queue()

    app.on_close()

    assert app._cancel_event.is_set()
    assert pump(app, lambda: destroyed)
    assert destroyed == [False]


@needs_display
def test_close_is_aborted_when_user_says_no(app, monkeypatch):
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: False)
    app.manager = SlowManager()
    app.set_queue([{"url": "a", "title": "A"}])
    app.start_download_queue()

    app.on_close()

    assert not app._cancel_event.is_set()
    assert app.is_busy()
    app.cancel_job()
    assert pump(app, lambda: not app.is_busy())
