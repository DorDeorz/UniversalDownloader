"""Links downloaded before, kept apart from the History list.

A playlist opened again starts with the videos downloaded before unticked
("only new"). The History page keeps at most a few hundred entries and can
be cleared, so that alone would forget older downloads; this archive keeps
one line per video (playlist.url_key) in the per-user data folder, for good,
until the user clears it in Settings.

Lines are only ever appended, so a crash costs at most the last line.
"""

import logging
import os

import playlist

_log = logging.getLogger(__name__)


class Archive:
    def __init__(self, path, seed=()):
        """``seed``: links to start with when the file does not exist yet (the History's)."""
        self.path = path
        self.keys = set()
        try:
            with open(path, encoding="utf-8") as f:
                self.keys = {line.strip() for line in f if line.strip()}
        except FileNotFoundError:
            seeded = [url for url in seed if url]
            if seeded:
                self.add_many(seeded)
        except OSError as e:
            _log.warning("Cannot read the download archive %s: %s", path, e)

    def __contains__(self, url):
        return bool(url) and playlist.url_key(url) in self.keys

    def __len__(self):
        return len(self.keys)

    def add(self, url):
        self.add_many([url])

    def add_many(self, urls):
        new = []
        for url in urls:
            key = playlist.url_key(url) if url else ""
            if key and key not in self.keys:
                self.keys.add(key)
                new.append(key)
        if not new:
            return
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write("".join(key + "\n" for key in new))
        except OSError as e:
            _log.warning("Could not write the download archive %s: %s", self.path, e)

    def clear(self):
        """Forget every link. The file stays (empty), so it is not filled from the History again."""
        self.keys = set()
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8"):
                pass
        except OSError as e:
            _log.warning("Could not clear the download archive %s: %s", self.path, e)
