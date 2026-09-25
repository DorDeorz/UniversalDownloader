"""Thread-safe event queue between worker threads and the Tk main thread.

Tkinter widgets may only be touched from the thread that runs ``mainloop()``.
Worker threads therefore never call widget methods; they ``post()`` events to
an :class:`EventQueue`, and the UI drains it on the main thread with
``after()`` and dispatches each event to a registered handler.

This module has no Tk dependency so it can be unit tested headless.
"""

import queue
import re
from dataclasses import dataclass, field

# Event kinds posted by workers.
LOG = "log"                      # payload: message
PROGRESS = "progress"            # payload: fraction (0..1), text
ANALYSIS_DONE = "analysis_done"  # payload: analysis (playlist.AnalysisResult), url
ANALYSIS_FAILED = "analysis_failed"  # payload: message
ITEM_DONE = "item_done"          # payload: result (results.ItemResult)
JOB_DONE = "job_done"            # payload: summary (results.JobSummary)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass(frozen=True)
class UIEvent:
    kind: str
    payload: dict = field(default_factory=dict)


class EventQueue:
    """FIFO of :class:`UIEvent` objects, safe to post to from any thread."""

    def __init__(self):
        self._queue = queue.Queue()
        self._handlers = {}

    def post(self, kind, **payload):
        self._queue.put(UIEvent(kind, payload))

    def register(self, kind, handler):
        self._handlers[kind] = handler

    def clear(self):
        """Drop all pending events without dispatching them."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def pending(self):
        return self._queue.qsize()

    def dispatch_pending(self, max_events=200):
        """Dispatch up to ``max_events`` queued events; call on the main thread.

        Returns the number of events dispatched. A failing handler is reported
        through the ``LOG`` handler (when that is not the one failing) and does
        not stop later events from being processed. Events with no registered
        handler are dropped.
        """
        count = 0
        while count < max_events:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            count += 1
            handler = self._handlers.get(event.kind)
            if handler is None:
                continue
            try:
                handler(**event.payload)
            except Exception as e:
                log_handler = self._handlers.get(LOG)
                if log_handler is not None and event.kind != LOG:
                    try:
                        log_handler(message=f"Internal UI error ({event.kind}): {e}")
                    except Exception:
                        pass
        return count


def progress_from_hook(d):
    """Turn a yt-dlp progress-hook dict into ``(fraction, text)`` or ``None``.

    Prefers the byte counters, falling back to ``_percent_str`` with ANSI
    colour codes removed. Returns ``None`` when no progress can be derived.
    """
    if d.get("status") == "finished":
        return 1.0, "100%"
    if d.get("status") != "downloading":
        return None

    downloaded = d.get("downloaded_bytes")
    total = d.get("total_bytes") or d.get("total_bytes_estimate")
    if isinstance(downloaded, (int, float)) and isinstance(total, (int, float)) and total > 0:
        fraction = downloaded / total
    else:
        text = _ANSI_RE.sub("", str(d.get("_percent_str") or "")).strip().rstrip("%").strip()
        try:
            fraction = float(text) / 100
        except ValueError:
            return None

    fraction = min(max(fraction, 0.0), 1.0)
    return fraction, f"{fraction * 100:.1f}%"
