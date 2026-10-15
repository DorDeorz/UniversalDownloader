"""Download history of the Android app (JSON in the app's private folder)."""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass

_log = logging.getLogger(__name__)
LIMIT = 300


@dataclass
class Entry:
    title: str
    path: str
    url: str = ""
    kind: str = "video"      # "video" or "audio"
    time: float = 0.0        # seconds since the epoch


class History:
    def __init__(self, path):
        self.path = path
        self.entries = self._load()

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
                entries.append(Entry(**{k: item[k] for k in ("title", "path", "url", "kind", "time") if k in item}))
            except (TypeError, KeyError):
                continue
        return entries[:LIMIT]

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self.entries], f, ensure_ascii=False)
        os.replace(temp, self.path)

    def add(self, title, path, url="", kind="video", now=None):
        """Newest first; a file downloaded again moves to the top."""
        self.entries = [e for e in self.entries if e.path != path]
        self.entries.insert(0, Entry(title, path, url, kind, time.time() if now is None else now))
        del self.entries[LIMIT:]
        self.save()

    def remove(self, path):
        self.entries = [e for e in self.entries if e.path != path]
        self.save()

    def clear(self):
        self.entries = []
        self.save()

    def recent(self, days=7, now=None):
        """(files, bytes) downloaded in the last ``days`` days whose files are still there."""
        since = (time.time() if now is None else now) - days * 86400
        files = size = 0
        for entry in self.entries:
            if entry.time < since:
                continue
            try:
                size += os.path.getsize(entry.path)
            except OSError:
                continue
            files += 1
        return files, size

    def existing(self):
        """Entries whose file is still on the device."""
        return [e for e in self.entries if os.path.exists(e.path)]


def format_size(size):
    """Bytes as a short text: 0 MB, 820 MB, 1.4 GB."""
    if size >= 1000 ** 3:
        return f"{size / 1000 ** 3:.1f} GB"
    return f"{size / 1000 ** 2:.0f} MB"
