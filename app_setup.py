"""Process-level setup done once at startup: logging, taskbar id, single instance."""

import json
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


# --- Links from the browser extension -------------------------------------------
#
# The extension opens "orbida://download?url=<link>". Windows starts Orbida.exe
# with that address (the installer registers the orbida: protocol). When Orbida
# already runs, the new process hands the link to it over a local socket and
# exits: the running app listens on 127.0.0.1 and writes its port and a random
# token to ipc.json in the user's data folder, which other users cannot read.

LINK_SCHEME = "orbida"
_IPC_FILE = "ipc.json"
_MAX_MESSAGE = 16 * 1024


def link_from_args(args):
    """The link in the command line (an orbida: address or a plain web link), or None."""
    from urllib.parse import parse_qs, urlsplit
    for arg in args:
        arg = (arg or "").strip()
        if arg.lower().startswith(LINK_SCHEME + ":"):
            parts = urlsplit(arg)
            url = parse_qs(parts.query).get("url", [None])[0]
            if url and url.lower().startswith(("http://", "https://")):
                return url
        elif arg.lower().startswith(("http://", "https://")):
            return arg
    return None


class LinkServer:
    """Receives links from later starts of the app (see send_link)."""

    def __init__(self, on_link, folder=None):
        import secrets
        import socket
        import threading
        self.on_link = on_link
        self.path = os.path.join(folder or data_dir(), _IPC_FILE)
        self.token = secrets.token_hex(16)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(4)
        self.port = self._socket.getsockname()[1]
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"port": self.port, "token": self.token, "pid": os.getpid()}, f)
        self._thread = threading.Thread(target=self._serve, name="link-server", daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                connection, _address = self._socket.accept()
            except OSError:
                return  # closed
            with connection:
                try:
                    connection.settimeout(5)
                    data = b""
                    while not data.endswith(b"\n") and len(data) < _MAX_MESSAGE:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    message = json.loads(data.decode("utf-8"))
                    url = message.get("url")
                    if message.get("token") != self.token or not isinstance(url, str):
                        continue
                    connection.sendall(b"ok\n")
                    self.on_link(url)
                except Exception as e:  # a bad message never stops the server
                    _log.warning("Ignoring a link message: %s", e)

    def close(self):
        try:
            self._socket.close()
        except OSError:
            pass
        try:
            with open(self.path, encoding="utf-8") as f:
                ours = json.load(f).get("token") == self.token
            if ours:  # removed after closing: Windows cannot delete an open file
                os.remove(self.path)
        except (OSError, ValueError):
            pass


def send_link(url, folder=None):
    """Hand ``url`` to the running app; True when it took it."""
    import socket
    try:
        with open(os.path.join(folder or data_dir(), _IPC_FILE), encoding="utf-8") as f:
            info = json.load(f)
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=5) as connection:
            connection.sendall(json.dumps({"token": info["token"], "url": url}).encode("utf-8") + b"\n")
            return connection.recv(16).startswith(b"ok")
    except (OSError, ValueError, KeyError, TypeError) as e:
        _log.warning("Could not hand the link to the running app: %s", e)
        return False
