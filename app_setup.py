"""Process-level setup done once at startup: logging, taskbar id, single instance."""

import logging
import logging.handlers
import os
import shutil
import sys

from version import APP_NAME, APP_USER_MODEL_ID, LEGACY_APP_NAME, __version__

_log = logging.getLogger(__name__)


def _data_base():
    return os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")


def data_dir():
    """Per-user folder for logs, settings and history (%LOCALAPPDATA%\\Orbida)."""
    return os.path.join(_data_base(), APP_NAME)


# Files carried over from the folder the app used before it was renamed.
MIGRATED_FILES = ("settings.json", "history.json")


def migrate_legacy_data(base=None):
    """Copy settings from %LOCALAPPDATA%\\UniversalDownloader on the first start as Orbida.

    Only runs while the new folder has no settings yet, so it happens once;
    the old folder is left alone (an older version may still be installed).
    Returns the names of the files copied.
    """
    base = base or _data_base()
    old, new = os.path.join(base, LEGACY_APP_NAME), os.path.join(base, APP_NAME)
    if os.path.exists(os.path.join(new, "settings.json")) or not os.path.isdir(old):
        return []
    copied = []
    for name in MIGRATED_FILES:
        source = os.path.join(old, name)
        if not os.path.isfile(source):
            continue
        try:
            os.makedirs(new, exist_ok=True)
            shutil.copy2(source, os.path.join(new, name))
            copied.append(name)
        except OSError as e:
            _log.warning("Could not copy %s from %s: %s", name, old, e)
    if copied:
        _log.info("Moved %s from %s", ", ".join(copied), old)
    return copied


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


# SetThreadExecutionState flags (winbase.h).
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake(on):
    """Keep Windows from sleeping while ``on`` (a download runs); a no-op elsewhere.

    The display may still turn off. The request belongs to the calling
    thread, so call it from the long-lived UI thread. Returns True when
    Windows accepted the request.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if on else 0)
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
    except (AttributeError, OSError):
        return False


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
