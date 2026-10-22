"""Process-level setup done once at startup: logging, taskbar id, single instance."""

import base64
import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import threading

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


def ytdlp_dir():
    """Folder of the yt-dlp downloaded for use instead of the bundled one (ytdlp_updates)."""
    return os.path.join(data_dir(), "yt-dlp")


def use_downloaded_ytdlp():
    """Import the downloaded yt-dlp, when there is a newer one; call before anything imports yt_dlp.

    One that cannot be imported is deleted, and the bundled one is used.
    """
    import ytdlp_updates
    folder = ytdlp_dir()
    try:
        if ytdlp_updates.activate(folder):
            import yt_dlp  # noqa: F401  (proves the download works)
    except Exception:
        _log.exception("The downloaded yt-dlp does not work; using the bundled one")
        ytdlp_updates.deactivate(folder)
    return ytdlp_updates.active_version()


def log_dir():
    """Folder of the log files (Settings > Open log folder)."""
    return os.path.join(data_dir(), "logs")


def log_uncaught_errors():
    """Write errors nothing caught to the log, on any thread.

    The installed app has no console, so Python's default printout of
    them would be lost.
    """
    previous_hook = sys.excepthook

    def on_error(kind, value, tb):
        _log.critical("Uncaught error", exc_info=(kind, value, tb))
        if sys.stderr is not None:
            previous_hook(kind, value, tb)

    def on_thread_error(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        _log.critical("Uncaught error in thread %s", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = on_error
    threading.excepthook = on_thread_error


def configure_logging(folder=None):
    """Rotating log file (1 MB x 3) so problems can be diagnosed after the fact (ISSUES.md #81).

    Returns the log file path, or None if the folder is not writable.
    """
    folder = folder or log_dir()
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


# Shows a toast as Orbida (the Start menu shortcut carries the same id).
# The texts come in environment variables, so they need no quoting.
_TOAST_SCRIPT = """
$ErrorActionPreference = 'Stop'
$manager = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$xml = $manager::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$lines = $xml.GetElementsByTagName('text')
$lines.Item(0).AppendChild($xml.CreateTextNode($env:ORBIDA_TOAST_TITLE)) | Out-Null
$lines.Item(1).AppendChild($xml.CreateTextNode($env:ORBIDA_TOAST_TEXT)) | Out-Null
$manager::CreateToastNotifier($env:ORBIDA_TOAST_APP).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""
_CREATE_NO_WINDOW = 0x08000000
# FlashWindowEx flags (winuser.h): flash the caption and the taskbar button until the window is in front.
_FLASHW_ALL = 0x3
_FLASHW_TIMERNOFG = 0xC


def notify(title, text, window=None, popen=subprocess.Popen):
    """Tell the user on Windows that something finished while they looked elsewhere.

    Shows a notification (toast) and flashes ``window``'s taskbar button.
    Windows shows the toast only for an installed Orbida, whose Start menu
    shortcut carries APP_USER_MODEL_ID. A no-op elsewhere; never raises.
    """
    if sys.platform != "win32":
        return False
    if window is not None:
        _flash(window)
    script = base64.b64encode(_TOAST_SCRIPT.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ, ORBIDA_TOAST_TITLE=title, ORBIDA_TOAST_TEXT=text, ORBIDA_TOAST_APP=APP_USER_MODEL_ID)
    try:
        popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-EncodedCommand", script], env=env, creationflags=_CREATE_NO_WINDOW,
              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        _log.warning("Notification failed: %s", e)
        return False
    return True


def _flash(window):
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                        ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

        # Tk's toplevel frame sits inside the real window that has the taskbar button.
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, _FLASHW_ALL | _FLASHW_TIMERNOFG, 0, 0)
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception as e:  # cosmetic; never worth an error
        _log.warning("Taskbar flash failed: %s", e)


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
        self.name = name
        self.handle = None
        self.already_running = False
        self.acquire()

    def acquire(self):
        """Take the lock (again, after :meth:`release`)."""
        if sys.platform != "win32" or self.handle:
            return
        import ctypes
        kernel32 = ctypes.windll.kernel32
        self.handle = kernel32.CreateMutexW(None, False, f"Local\\{self.name}")
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


# --- The Firefox add-on ------------------------------------------------------------
#
# Firefox keeps only add-ons signed by Mozilla. The release workflow has the
# extension signed on addons.mozilla.org (unlisted: not shown in the store)
# and the installer ships the signed file as firefox\Orbida.xpi. Opening that
# file with Firefox (or Zen, LibreWolf, ...) shows the browser's own
# "Add Orbida?" prompt.

FIREFOX_XPI = os.path.join("firefox", "Orbida.xpi")


# Firefox and the browsers built on it, which take the same signed add-on:
# (program, folder under Program Files).
GECKO_BROWSERS = (("firefox.exe", "Mozilla Firefox"), ("zen.exe", "Zen Browser"), ("librewolf.exe", "LibreWolf"),
                  ("floorp.exe", "Ablaze Floorp"), ("waterfox.exe", "Waterfox"))


def _read_registry(root, subkey, name=None):
    """A string value from the Windows registry ("HKCU", "HKLM" or "HKCR"), or None."""
    import winreg
    hive = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKCR": winreg.HKEY_CLASSES_ROOT}[root]
    try:
        with winreg.OpenKey(hive, subkey) as key:
            return winreg.QueryValueEx(key, name)[0] if name else winreg.QueryValue(key, None)
    except OSError:
        return None


def _program(command):
    """The program in a registry command line ('"C:\\x\\zen.exe" -osint -url "%1"')."""
    command = (command or "").strip()
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    return command.split(" -", 1)[0].strip()


def firefox_path(registry=None):
    """Firefox, or a browser built on it, to open the add-on with; None if there is none.

    The default web browser comes first when it is one of GECKO_BROWSERS (so
    a Zen user gets Zen even with Firefox installed), then each of them as
    Windows records it (App Paths) or in its usual folder.
    """
    if registry is None:
        if sys.platform != "win32":
            return None
        registry = _read_registry
    names = {name for name, _folder in GECKO_BROWSERS}
    choice = registry("HKCU", r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
                      "ProgId")
    if choice:
        default = _program(registry("HKCR", choice + r"\shell\open\command"))
        if os.path.basename(default).lower() in names and os.path.isfile(default):
            return default
    for name, folder in GECKO_BROWSERS:
        for root in ("HKCU", "HKLM"):
            path = _program(registry(root, r"Software\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + name))
            if path and os.path.isfile(path):
                return path
        local = os.environ.get("LOCALAPPDATA")
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                     os.path.join(local, "Programs") if local else None):
            path = os.path.join(base, folder, name) if base else ""
            if path and os.path.isfile(path):
                return path
    return None


def open_in_firefox(xpi, firefox=None):
    """Open the add-on file in Firefox, which asks whether to add it; False without Firefox."""
    firefox = firefox or firefox_path()
    if not firefox:
        return False
    try:
        subprocess.Popen([firefox, os.path.abspath(xpi)])
        return True
    except OSError as e:
        _log.warning("Could not start Firefox: %s", e)
        return False
