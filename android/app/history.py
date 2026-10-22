"""Download history of the Android app (JSON in the app's private folder)."""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass

_log = logging.getLogger(__name__)
LIMIT = 300
SAVE_EVERY = 25   # entries added with save=False before the file is written anyway


@dataclass
class Entry:
    title: str
    path: str
    url: str = ""
    kind: str = "video"      # "video" or "audio"
    time: float = 0.0        # seconds since the epoch
    size: int = -1           # bytes when it was downloaded; -1 when not known (older entries)


class History:
    def __init__(self, path):
        self.path = path
        self.entries = self._load()
        self.unsaved = 0  # entries added since the last save (add(save=False))

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            _log.warning("Cannot read history %s: %s", self.path, e)
            return []
        entries = []
        for item in data if isinstance(data, list) else []:
            try:
                entries.append(Entry(**{k: item[k] for k in ("title", "path", "url", "kind", "time", "size")
                                        if k in item}))
            except (TypeError, KeyError):
                continue
        return entries[:LIMIT]

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self.entries], f, ensure_ascii=False)
        os.replace(temp, self.path)
        self.unsaved = 0

    def add(self, title, path, url="", kind="video", now=None, save=True):
        """Newest first; a file downloaded again moves to the top.

        ``save=False`` (a playlist's videos, one after another) leaves the
        writing to flush() at the end of the job; the file is still written
        every SAVE_EVERY entries, so a crash loses little.
        """
        try:
            size = os.path.getsize(path)
        except OSError:
            size = -1
        self.entries = [e for e in self.entries if e.path != path]
        entry = Entry(title, path, url, kind, time.time() if now is None else now, size)
        self.entries.insert(0, entry)
        del self.entries[LIMIT:]
        self.unsaved += 1
        if save or self.unsaved >= SAVE_EVERY:
            self.save()
        return entry

    def flush(self):
        """Write entries added with save=False."""
        if self.unsaved:
            self.save()

    def remove(self, path):
        """Take the entry for ``path`` off the list; returns (entry, index) for restore(), or None."""
        for index, entry in enumerate(self.entries):
            if entry.path == path:
                del self.entries[index]
                self.save()
                return entry, index
        return None

    def restore(self, entry, index=0):
        """Put a removed ``entry`` back at ``index`` (History › Undo)."""
        self.entries = [e for e in self.entries if e.path != entry.path]
        self.entries.insert(min(max(0, index), len(self.entries)), entry)
        del self.entries[LIMIT:]
        self.save()

    def clear(self):
        self.entries = []
        self.save()

    def recent(self, days=7, now=None):
        """(files, bytes) downloaded in the last ``days`` days.

        Uses the size saved with each entry; only older entries saved
        without one ask the file system, once.
        """
        since = (time.time() if now is None else now) - days * 86400
        files = size = 0
        for entry in self.entries:
            if entry.time < since:
                continue
            if entry.size < 0:
                try:
                    entry.size = os.path.getsize(entry.path)
                except OSError:
                    continue
            size += entry.size
            files += 1
        return files, size

    def existing(self):
        """Entries whose file is still on the device."""
        return [e for e in self.entries if os.path.exists(e.path)]

    def search(self, text):
        """Entries whose title, file name or link contains every word of ``text``."""
        words = (text or "").casefold().split()
        if not words:
            return list(self.entries)
        return [e for e in self.entries
                if all(w in f"{e.title} {os.path.basename(e.path)} {e.url}".casefold() for w in words)]


def format_size(size):
    """Bytes as a short text: 0 MB, 820 MB, 1.4 GB."""
    if size >= 1000 ** 3:
        return f"{size / 1000 ** 3:.1f} GB"
    return f"{size / 1000 ** 2:.0f} MB"
