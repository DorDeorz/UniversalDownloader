"""Per-item download results and the end-of-job summary.

A download job reports one :class:`ItemResult` per queued item, so the UI can
say exactly which items completed, failed, were skipped or were cancelled
instead of an unconditional "Finished!".
"""

import os
from dataclasses import dataclass, field
from enum import Enum


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
    }

    def title_key(self):
        """Message key of the dialog title matching the outcome."""
        counts = self.counts()
        if self.all_ok:
            return "summary.complete"
        if counts[ItemStatus.CANCELLED]:
            return "summary.cancelled"
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
