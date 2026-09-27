"""Recent downloads, shown on the History page (JSON in the per-user data folder).

The same idea as the Android app's history: newest first, at most
``LIMIT`` entries, a damaged file never stops the app, and each save is
atomic so a crash cannot leave half a file.
"""

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
    mode: str = ""           # formats.MODES value the file was downloaded with
    time: float = 0.0        # seconds since the epoch

    @classmethod
    def from_dict(cls, item):
        """An entry from saved JSON, or None when the item is not a valid entry."""
        if not isinstance(item, dict):
            return None
        title, path = item.get("title"), item.get("path")
        if not isinstance(title, str) or not isinstance(path, str) or not path:
            return None
        url = item.get("url") if isinstance(item.get("url"), str) else ""
        mode = item.get("mode") if isinstance(item.get("mode"), str) else ""
        stamp = item.get("time")
        stamp = float(stamp) if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else 0.0
        return cls(title, path, url, mode, stamp)


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
        entries = [Entry.from_dict(item) for item in data] if isinstance(data, list) else []
        return [e for e in entries if e is not None][:LIMIT]

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            temp = self.path + ".tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump([asdict(e) for e in self.entries], f, ensure_ascii=False, indent=1)
            os.replace(temp, self.path)
        except OSError as e:
            _log.warning("Could not save history to %s: %s", self.path, e)

    def add(self, title, path, url="", mode="", now=None):
        """Newest first; a file downloaded again moves to the top."""
        self.entries = [e for e in self.entries if e.path != path]
        self.entries.insert(0, Entry(title, path, url, mode, time.time() if now is None else now))
        del self.entries[LIMIT:]
        self.save()

    def remove(self, path):
        self.entries = [e for e in self.entries if e.path != path]
        self.save()

    def clear(self):
        self.entries = []
        self.save()
