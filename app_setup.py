"""Process-level setup done once at startup: logging, taskbar id, single instance."""

import logging
import logging.handlers
import os
import sys

from version import APP_NAME, APP_USER_MODEL_ID, __version__

_log = logging.getLogger(__name__)


def data_dir():
    """Per-user folder for logs and settings (%LOCALAPPDATA%\\UniversalDownloader)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_NAME)


def configure_logging(folder=None):
    """Rotating log file (1 MB x 3) so problems can be diagnosed after the fact (ISSUES.md #81).

    Returns the log file path, or None if the folder is not writable.
    """
    folder = folder or os.path.join(data_dir(), "logs")
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "app.log")
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    _log.info("%s %s starting (Python %s)", APP_NAME, __version__, sys.version.split()[0])
    return path


def set_app_user_model_id():
    """Group the taskbar icon correctly on Windows; a no-op elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


class SingleInstance:
    """Named mutex so a second copy of the app is not started (ISSUES.md #46).

    Two copies downloading into the same folder could pick the same file
    names. Windows only; elsewhere every instance is allowed.
    """

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name=APP_USER_MODEL_ID):
        self.handle = None
        self.already_running = False
        if sys.platform != "win32":
            return
        import ctypes
        kernel32 = ctypes.windll.kernel32
        self.handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
        self.already_running = kernel32.GetLastError() == self.ERROR_ALREADY_EXISTS

    def release(self):
        if self.handle:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None
