"""Keep running in the tray when the window is closed (tray.py, Windows)."""

import os
import sys
import threading

import pytest

import events
import tray


class FakePystray:
    """pystray's interface, recording the icon instead of showing one."""

    class Menu:
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    class MenuItem:
        def __init__(self, text, action, default=False):
            self.text, self.action, self.default = text, action, default

    class Icon:
        made = []

        def __init__(self, name, image, title, menu):
            self.name, self.image, self.title, self.menu = name, image, title, menu
            self.running = threading.Event()
            self.stopped = threading.Event()
            FakePystray.Icon.made.append(self)

        def run(self):
            self.running.set()
            self.stopped.wait(5)

        def stop(self):
            self.stopped.set()


def items(icon):
    return [i for i in icon.menu.items if i is not FakePystray.Menu.SEPARATOR]


def test_the_icon_has_show_and_quit_and_follows_the_progress():
    pytest.importorskip("PIL")
    calls = []
    icon = tray.Tray("Orbida", lambda: calls.append("show"), lambda: calls.append("quit"),
                     lambda key: key.upper(), backend=FakePystray)
    assert icon.start() and icon.running
    made = FakePystray.Icon.made[-1]
    assert made.running.wait(5)
    assert made.image.size[0] > 0 and made.title == "Orbida"
    show, quit_ = items(made)
    assert show.default and show.text(show) == "TRAY.SHOW" and quit_.text(quit_) == "TRAY.QUIT"
    show.action()
    quit_.action()
    assert calls == ["show", "quit"]
    icon.set_title("Orbida · 42%")
    assert made.title == "Orbida · 42%"
    icon.stop()
    assert made.stopped.is_set() and not icon.running


def test_no_tray_off_windows_or_without_pystray(monkeypatch):
    monkeypatch.setattr(tray, "supported", lambda: False)
    assert not tray.Tray("Orbida", None, None, str).start()

    class Broken:
        def Menu(self, *a):
            raise ImportError("no pystray")
    assert not tray.Tray("Orbida", None, None, str, backend=Broken()).start()


# --- the window ---------------------------------------------------------------------

ctk = pytest.importorskip("customtkinter")
needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


class RecordingTray:
    made = []

    def __init__(self, title, on_show, on_quit, label):
        self.on_show, self.on_quit, self.title = on_show, on_quit, title
        self.stopped = False
        RecordingTray.made.append(self)

    def start(self):
        return True

    def set_title(self, text):
        self.title = text

    def stop(self):
        self.stopped = True


@needs_display
def test_closing_hides_to_the_tray_and_the_menu_brings_it_back(monkeypatch):
    import ui
    from ui_helpers import make_app, pump
    monkeypatch.setattr(ui.tray, "Tray", RecordingTray)
    notes = []
    monkeypatch.setattr(ui.app_setup, "notify", lambda title, text, window=None: notes.append(title))
    app = make_app(monkeypatch)
    destroyed = []
    real_destroy = app.destroy
    monkeypatch.setattr(app, "destroy", lambda: (destroyed.append(True), real_destroy()))
    try:
        assert app.tray is None  # off by default
        app._on_setting_changed("close_to_tray", True)
        icon = RecordingTray.made[-1]
        assert app.tray is icon

        app.on_close()
        pump(app, timeout=0.2)
        assert app.state() == "withdrawn" and not destroyed
        assert notes == [ui.tr("tray.hidden_title")]
        app._show_progress(0.42, "42%")
        assert icon.title == "Orbida · 42%"
        app.on_close()
        assert notes == [ui.tr("tray.hidden_title")]  # told once

        icon.on_show()  # pystray's thread posts; the window thread shows
        assert app.state() == "withdrawn"
        app.events.dispatch_pending()
        assert app.state() == "normal" and icon.title == "Orbida"

        app._on_setting_changed("close_to_tray", False)
        assert icon.stopped and app.tray is None
        app._on_setting_changed("close_to_tray", True)
        icon = RecordingTray.made[-1]
        app.withdraw()
        icon.on_quit()
        app.events.dispatch_pending()
        assert destroyed and icon.stopped
    finally:
        if not destroyed:
            real_destroy()


def test_tray_events_exist():
    assert events.TRAY_SHOW != events.TRAY_QUIT


@needs_display
def test_starting_orbida_again_brings_the_hidden_window_back(monkeypatch):
    from ui_helpers import make_app, pump
    app = make_app(monkeypatch)
    try:
        app.withdraw()
        pump(app, timeout=0.1)
        app.open_link("")  # main.py sends an empty link when Orbida is started again
        assert app.state() == "normal" and not app.is_busy()
    finally:
        app.destroy()
