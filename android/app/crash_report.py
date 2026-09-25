"""Keeps a record of crashes so the next start can show what went wrong.

Two kinds of failure are recorded in the app's own folder:

* a Python error in a button handler or other main-loop code; the app
  logs it to ``crash.txt`` and keeps running instead of closing;
* a crash in native code (FFmpeg bindings, curl_cffi, SDL), where Python
  cannot recover. :mod:`faulthandler` writes the Python stack of every
  thread to ``crash-native.txt`` just before the process dies.

On the next start :meth:`CrashReport.take_previous` returns both records
(and removes them), so the app can show them and the user can copy them.
"""

import faulthandler
import os
import time
import traceback

PYTHON_FILE = "crash.txt"
NATIVE_FILE = "crash-native.txt"
LIMIT = 20000  # characters kept from each record


class CrashReport:
    def __init__(self, folder):
        self.folder = folder
        self._native = None

    def _path(self, name):
        return os.path.join(self.folder, name)

    def take_previous(self):
        """The records the last run left behind, or "" when it ended cleanly."""
        parts = []
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
