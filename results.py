"""Per-item download results and the end-of-job summary.

A download job reports one :class:`ItemResult` per queued item, so the UI can
say exactly which items completed, failed, were skipped or were cancelled
instead of an unconditional "Finished!".
"""

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum

_log = logging.getLogger(__name__)


class ItemStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class ItemResult:
    url: str
    title: str
    status: ItemStatus
    path: str | None = None
    error: str | None = None
    # The queue item this result is for, so failed items can be retried
    # with the same playlist position and folder.
    source: dict | None = field(default=None, compare=False, repr=False)

    @property
    def ok(self):
        return self.status is ItemStatus.COMPLETED

    def describe(self):
        """One log line for this item."""
        if self.status is ItemStatus.COMPLETED:
            return f"Saved: {self.path}"
        label = self.status.value.capitalize()
        return f"{label}: {self.title}" + (f" ({self.error})" if self.error else "")


@dataclass
class JobSummary:
    results: list = field(default_factory=list)

    def add(self, result):
        self.results.append(result)

    def with_status(self, status):
        return [r for r in self.results if r.status is status]

    def counts(self):
        return {status: len(self.with_status(status)) for status in ItemStatus}

    @property
    def all_ok(self):
        return bool(self.results) and all(r.ok for r in self.results)

    @property
    def no_problems(self):
        """True when nothing failed or was cancelled (skipped items are fine)."""
        counts = self.counts()
        return not counts[ItemStatus.FAILED] and not counts[ItemStatus.CANCELLED]

    def headline(self, label=None, nothing="Nothing to download"):
        """Short text such as '2 completed, 1 failed'.

        ``label`` turns a status into its (translated) word; English by default.
        """
        label = label or (lambda status: status.value)
        parts = [f"{n} {label(status)}" for status, n in self.counts().items() if n]
        return ", ".join(parts) if parts else nothing

    _TITLES = {
        "summary.complete": "Download complete",
        "summary.cancelled": "Download cancelled",
        "summary.partial": "Download partly failed",
        "summary.failed": "Download failed",
        "summary.skipped": "Nothing downloaded",
    }

    def title_key(self):
        """Message key of the dialog title matching the outcome.

        Skipped items (private or deleted videos) are not failures: a job
        that only skipped some is complete, one that skipped all of them
        downloaded nothing.
        """
        counts = self.counts()
        if self.all_ok:
            return "summary.complete"
        if counts[ItemStatus.CANCELLED]:
            return "summary.cancelled"
        if self.no_problems:
            return "summary.complete" if counts[ItemStatus.COMPLETED] else "summary.skipped"
        if counts[ItemStatus.COMPLETED]:
            return "summary.partial"
        return "summary.failed"

    def title(self):
        """Dialog title matching the outcome (English)."""
        return self._TITLES[self.title_key()]

    def report(self, limit=10, label=None, nothing="Nothing to download", more="... and {count} more"):
        """Headline plus the items that did not complete (for the final dialog)."""
        label = label or (lambda status: status.value)
        lines = [self.headline(label, nothing)]
        problems = [r for r in self.results if not r.ok]
        for r in problems[:limit]:
            lines.append(f"- {label(r.status)}: {r.title}" + (f": {r.error}" if r.error else ""))
        if len(problems) > limit:
            lines.append(more.format(count=len(problems) - limit))
        return "\n".join(lines)


def verify_output(path):
    """Error text if ``path`` is missing or empty, else None (ISSUES.md #52)."""
    if not path:
        return "yt-dlp did not report an output file"
    if not os.path.isfile(path):
        return f"Output file was not created: {path}"
    if os.path.getsize(path) == 0:
        return f"Output file is empty: {path}"
    return None


PROBE_TIMEOUT = 60
DAMAGED = "The downloaded file is damaged or incomplete"
NO_VIDEO_TRACK = "The downloaded file has no video track"
NO_AUDIO_TRACK = "The downloaded file has no audio track"


def probe_output(path, ffprobe, need_video=False, need_audio=False, run=subprocess.run):
    """Error text when ffprobe cannot read the finished file or misses a track, else None.

    A file that ffprobe cannot open, or that has no streams at all, is
    damaged (a cut-off download that looked finished). ``need_video`` and
    ``need_audio`` ask for a video track (a cover image does not count) and
    an audio track. Without ffprobe, or when it does not answer, the file is
    taken as it is.
    """
    if not ffprobe:
        return None
    command = [ffprobe, "-v", "error", "-show_entries", "stream=codec_type:stream_disposition=attached_pic",
               "-of", "json", path]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = run(command, capture_output=True, text=True, timeout=PROBE_TIMEOUT, creationflags=flags)
    except (OSError, subprocess.SubprocessError) as e:
        _log.warning("Could not check %s with ffprobe: %s", path, e)
        return None
    try:
        streams = json.loads(proc.stdout or "{}").get("streams") or []
    except ValueError:
        streams = []
    if proc.returncode != 0 or not streams:
        _log.warning("ffprobe cannot read %s: %s", path, (proc.stderr or "").strip()[:500])
        return DAMAGED
    kinds = {s.get("codec_type") for s in streams if not (s.get("disposition") or {}).get("attached_pic")}
    if need_video and "video" not in kinds:
        return NO_VIDEO_TRACK
    if need_audio and "audio" not in kinds:
        return NO_AUDIO_TRACK
    return None
