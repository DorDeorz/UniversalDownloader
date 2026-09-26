"""Keeps a record of crashes so the next start can show what went wrong.

Three kinds of failure are recorded:

* a Python error in a button handler or other main-loop code; the app
  logs it to ``crash.txt`` and keeps running instead of closing;
* a crash in native code (FFmpeg bindings, curl_cffi, SDL), where Python
  cannot recover. :mod:`faulthandler` writes the Python stack of every
  thread to ``crash-native.txt`` just before the process dies;
* on Android, a Java exception or fatal signal, which Android writes to
  its crash log; :func:`new_log_lines` picks out what was not shown yet.

On the next start :meth:`CrashReport.take_previous` returns the records
(and removes the files), so the app can show them and the user can copy them.
"""

import faulthandler
import os
import time
import traceback

PYTHON_FILE = "crash.txt"
NATIVE_FILE = "crash-native.txt"
SEEN_FILE = "crash-log-seen.txt"
LIMIT = 20000  # characters kept from each record


class CrashReport:
    def __init__(self, folder):
        self.folder = folder
        self._native = None

    def _path(self, name):
        return os.path.join(self.folder, name)

    def take_previous(self, extra=""):
        """The records the last run left behind (plus ``extra``), or "" when it ended cleanly."""
        parts = [extra.strip()] if extra.strip() else []
        for name in (PYTHON_FILE, NATIVE_FILE):
            path = self._path(name)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read().strip()
                os.remove(path)
            except OSError:
                continue
            if text:
                parts.append(text[-LIMIT:])
        return "\n\n".join(parts)

    def new_system_crashes(self, crash_log):
        """The part of Android's crash log (for this app) not reported before."""
        path = self._path(SEEN_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                seen = f.read().strip()
        except OSError:
            seen = ""
        new, last = new_log_lines(crash_log, seen)
        if last and last != seen:
            try:
                os.makedirs(self.folder, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(last)
            except OSError:
                pass
        return new

    def watch_native(self):
        """Have faulthandler write every thread's stack if the process crashes."""
        os.makedirs(self.folder, exist_ok=True)
        self._native = open(self._path(NATIVE_FILE), "w", encoding="utf-8")
        faulthandler.enable(file=self._native, all_threads=True)

    def record(self, error, where=""):
        """Append a Python error to the record; returns the text written."""
        stack = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        text = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {where}\n{stack}".strip()
        try:
            os.makedirs(self.folder, exist_ok=True)
            with open(self._path(PYTHON_FILE), "a", encoding="utf-8") as f:
                f.write(text + "\n\n")
        except OSError:
            pass
        return text


def new_log_lines(log, seen):
    """Lines of ``log`` after the line ``seen``; all of them if it is not there.

    Returns (the new lines as text, the last line) so the caller can remember
    where it stopped.
    """
    lines = [line for line in log.splitlines()
             if line.strip() and not line.startswith("--------- beginning of") and not _minidump(line)]
    if not lines:
        return "", seen
    if seen in lines:
        lines_after = lines[len(lines) - 1 - lines[::-1].index(seen) + 1:]
    else:
        lines_after = lines
    return "\n".join(lines_after), lines[-1]


def _minidump(line):
    """A line of the encoded minidump the WebView's crashpad logs when the process dies.

    It runs to hundreds of lines and would push the actual crash out of the report.
    """
    return " crashpad: " in line and "CRASHPAD MINIDUMP" not in line


def tail(text, count):
    """The last ``count`` lines of ``text``."""
    return "\n".join(text.splitlines()[-count:])


# Log lines that only say the app unpacked a file on its first start.
_NOISE = (" V python  : extracting ", " V python  : Checking pattern ", " V python  : Unpacking ")


def diagnostics(version, app_log, android_log, lines=400):
    """The text "Copy diagnostic log" puts on the clipboard.

    The app's own log (what the Details panel shows) comes first, then the
    end of Android's log without the thousands of unpacking lines of a first
    start, so a paste into a chat still holds what matters.
    """
    useful = [line for line in android_log.splitlines() if not any(n in line for n in _NOISE)]
    return (f"UniversalDownloader {version}\n\nApp log:\n" + "\n".join(app_log)
            + "\n\nAndroid log:\n" + "\n".join(useful[-lines:]))
