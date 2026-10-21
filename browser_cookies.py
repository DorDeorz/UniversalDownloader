"""Use the Reddit sign-in of the user's Firefox-based browser (opt-in).

Reddit shows NSFW posts only to signed-in accounts; without one yt-dlp
fails with "Account authentication is required". When the user turns this
on, downloads carry the reddit.com cookies of their Firefox, Zen,
LibreWolf, Floorp or Waterfox profile, so Orbida never sees a password.

yt-dlp can read Firefox cookies itself, but it only looks in Firefox's own
folders and copies the main database file without its write-ahead log,
where a recent sign-in may still be. So this module copies the most
recently used profile's ``cookies.sqlite`` (with the log) into a private
folder, deletes every cookie that is not Reddit's, and hands that folder to
yt-dlp. No other site ever receives the browser's cookies.
"""

import glob
import logging
import os
import shutil
import sys
import threading
import time

_log = logging.getLogger(__name__)

DATABASE = "cookies.sqlite"
# The cookie Reddit sets for a signed-in session.
SESSION_COOKIE = "reddit_session"
# A copy is reused this long before the browser's database is read again.
REFRESH_SECONDS = 60

# Statuses of a refresh.
SIGNED_IN, SIGNED_OUT, NO_BROWSER, FAILED = "signed_in", "signed_out", "no_browser", "failed"

# Folder names of Firefox-based browsers, as in the user's application data.
_BROWSERS = ("Mozilla/Firefox", "zen", "librewolf", "Floorp", "Waterfox")


def profile_roots():
    """Folders that hold Firefox-family profiles on this system."""
    if sys.platform in ("win32", "cygwin"):
        appdata = os.environ.get("APPDATA", "")
        local = os.environ.get("LOCALAPPDATA", "")
        roots = [os.path.join(appdata, *name.split("/"), "Profiles") for name in _BROWSERS]
        # Firefox from the Microsoft Store.
        roots.append(os.path.join(local, "Packages", "Mozilla.Firefox_n80bbvh6b1yt2", "LocalCache",
                                  "Roaming", "Mozilla", "Firefox", "Profiles"))
        return [root for root in roots if os.path.isabs(root)]
    if sys.platform == "darwin":
        support = os.path.expanduser("~/Library/Application Support")
        return [os.path.join(support, *name.split("/"), "Profiles") for name in _BROWSERS]
    home = os.path.expanduser("~")
    return [os.path.join(home, ".mozilla", "firefox"), os.path.join(home, ".config", "mozilla", "firefox"),
            os.path.join(home, ".zen"), os.path.join(home, ".librewolf"), os.path.join(home, ".floorp"),
            os.path.join(home, ".waterfox")]


def _last_used(database):
    """When the browser last wrote ``database`` or its write-ahead log."""
    times = []
    for path in (database, database + "-wal"):
        try:
            times.append(os.path.getmtime(path))
        except OSError:
            pass
    return max(times, default=0)


def browser_name(database):
    """The browser a profile's ``database`` belongs to, for messages ("Zen", "Firefox")."""
    path = (database or "").replace("\\", "/").lower()
    for name, shown in (("zen", "Zen"), ("librewolf", "LibreWolf"), ("floorp", "Floorp"),
                        ("waterfox", "Waterfox")):
        if f"/{name}/" in path or f"/.{name}/" in path:
            return shown
    return "Firefox"


def newest_database(roots=None):
    """The cookie database of the most recently used profile, or None."""
    found = []
    for root in roots if roots is not None else profile_roots():
        found.extend(glob.glob(os.path.join(glob.escape(root), "*", DATABASE)))
    return max(found, key=_last_used, default=None)


def copy_reddit_cookies(database, folder):
    """Copy ``database`` into ``folder`` keeping only Reddit's cookies.

    Returns True when the copy holds a signed-in Reddit session.
    """
    import sqlite3  # not in every Python build (Android); only needed here

    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, DATABASE)
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(target + suffix)
        except FileNotFoundError:
            pass
    shutil.copyfile(database, target)
    if os.path.exists(database + "-wal"):
        shutil.copyfile(database + "-wal", target + "-wal")
    connection = sqlite3.connect(target)
    try:
        connection.execute("DELETE FROM moz_cookies WHERE NOT (host = 'reddit.com' OR host LIKE '%.reddit.com')")
        connection.commit()
        signed_in = connection.execute(
            "SELECT 1 FROM moz_cookies WHERE name = ? AND value != ''", (SESSION_COOKIE,)).fetchone() is not None
        # Fold the copied log into the database file, which is all yt-dlp copies.
        connection.execute("PRAGMA journal_mode=DELETE")
    finally:
        connection.close()
    return signed_in


class RedditSignIn:
    """yt-dlp options that send the browser's Reddit cookies, refreshed as they change."""

    def __init__(self, folder, roots=None, clock=time.monotonic):
        self.folder = folder
        self.roots = roots
        self.clock = clock
        self.status = None
        self.browser_database = None
        self._read_at = None
        self._lock = threading.Lock()

    def refresh(self):
        """Copy the browser's Reddit cookies again; returns the new status."""
        database = newest_database(self.roots)
        if database is None:
            status = NO_BROWSER
        else:
            try:
                status = SIGNED_IN if copy_reddit_cookies(database, self.folder) else SIGNED_OUT
            except Exception as e:  # OSError, sqlite3.Error, no sqlite3 module
                _log.warning("Could not read the browser's cookies from %s: %s", database, e)
                status = FAILED
        if (status, database) != (self.status, self.browser_database):
            _log.info("Reddit sign-in from the browser: %s (%s)", status, database or "no Firefox-based browser")
        self.status, self.browser_database = status, database
        self._read_at = self.clock()
        return status

    def ydl_options(self):
        """``cookiesfrombrowser`` for the Reddit-only copy; empty when there is nothing to send."""
        with self._lock:
            if self._read_at is None or self.clock() - self._read_at >= REFRESH_SECONDS:
                self.refresh()
            if self.status not in (SIGNED_IN, SIGNED_OUT):
                return {}
        return {"cookiesfrombrowser": ("firefox", self.folder, None, None)}

    def remove_copy(self):
        """Delete the copied cookies (when the user turns the option off)."""
        with self._lock:
            shutil.rmtree(self.folder, ignore_errors=True)
            self.status = self._read_at = None


class AppSignIn:
    """A Reddit sign-in the app keeps itself (Android's WebView); its cookies
    reach yt-dlp through the app's cookie file, so no options are added."""

    status = SIGNED_IN

    @staticmethod
    def ydl_options():
        return {}
