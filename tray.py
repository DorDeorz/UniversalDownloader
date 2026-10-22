"""Orbida's icon in the Windows notification area (the "tray").

With the setting on, closing the window keeps Orbida running there: a
download goes on, the clipboard is still watched and links from the browser
extension still arrive. Clicking the icon shows the window again; its menu
also quits.

pystray runs the icon's message loop on a thread of its own, so the menu's
actions must not touch Tk: they are handed to the caller's callbacks, which
post them to the UI thread (events.EventQueue). Elsewhere than Windows, or
when pystray cannot start, :meth:`Tray.start` returns False and the window
closes as before.
"""

import logging
import sys
import threading

from utils import resource_path

_log = logging.getLogger(__name__)


def supported():
    return sys.platform == "win32"


class Tray:
    """The tray icon. ``on_show``/``on_quit`` run on pystray's thread; ``label(key)`` names the menu items."""

    def __init__(self, title, on_show, on_quit, label, backend=None):
        self.title = title
        self.on_show = on_show
        self.on_quit = on_quit
        self.label = label
        self.backend = backend  # pystray's module (tests pass one with the dummy backend)
        self.icon = None
        self._thread = None

    @property
    def running(self):
        return self.icon is not None

    def start(self):
        """Show the icon; False when it cannot be shown here."""
        if self.icon is not None:
            return True
        try:
            pystray = self.backend
            if pystray is None:
                if not supported():
                    return False
                import pystray
            from PIL import Image
            image = Image.open(resource_path("app.ico"))
            menu = pystray.Menu(
                pystray.MenuItem(lambda _item: self.label("tray.show"), lambda: self.on_show(), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(lambda _item: self.label("tray.quit"), lambda: self.on_quit()),
            )
            self.icon = pystray.Icon("Orbida", image, self.title, menu)
        except Exception as e:  # no pystray or Pillow, a broken icon file
            _log.warning("Tray icon unavailable: %s", e)
            self.icon = None
            return False
        self._thread = threading.Thread(target=self._run, name="orbida-tray", daemon=True)
        self._thread.start()
        return True

    def _run(self):
        icon = self.icon
        try:
            if icon is not None:
                icon.run()
        except Exception as e:
            _log.warning("Tray icon stopped: %s", e)

    def set_title(self, text):
        """The tooltip (download progress while the window is hidden)."""
        self.title = text
        if self.icon is not None:
            try:
                self.icon.title = text
            except Exception as e:
                _log.warning("Tray title: %s", e)

    def notify(self, title, text):
        """A Windows notification from the tray icon (no PowerShell); False when it cannot be shown."""
        icon = self.icon
        if icon is None:
            return False
        try:
            icon.notify(text, title)
            return True
        except Exception as e:
            _log.warning("Tray notification: %s", e)
            return False

    def stop(self):
        icon, self.icon = self.icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception as e:
                _log.warning("Tray icon stop: %s", e)


# How long a notification's own icon stays (the notification goes with it).
NOTIFY_SECONDS = 10


def show_notification(title, text, tray=None, backend=None, keep=NOTIFY_SECONDS):
    """Show a Windows notification without starting PowerShell.

    The tray icon shows it when Orbida has one running; otherwise a hidden
    icon of Orbida's is added for ``keep`` seconds to carry it. False when
    neither works (then app_setup.notify falls back to PowerShell).
    """
    if tray is not None and tray.notify(title, text):
        return True
    try:
        pystray = backend
        if pystray is None:
            if not supported():
                return False
            import pystray
        from PIL import Image
        icon = pystray.Icon("Orbida-notification", Image.open(resource_path("app.ico")), "Orbida")

        def setup(icon):  # on a thread of pystray's while the icon's loop runs
            try:
                icon.visible = True
                icon.notify(text, title)
                threading.Event().wait(keep)
            except Exception as e:
                _log.warning("Notification failed: %s", e)
            finally:
                icon.stop()
        threading.Thread(target=lambda: icon.run(setup), name="orbida-notification", daemon=True).start()
        return True
    except Exception as e:
        _log.warning("Notification icon unavailable: %s", e)
        return False

