"""The Windows notification shown when downloads finish in the background."""

import base64
import os
import subprocess
import sys

import app_setup
from version import APP_USER_MODEL_ID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_notify_shows_a_toast_as_orbida(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    calls = []
    assert app_setup.notify("Done", "2 completed; it's \"fine\"", popen=lambda args, **kw: calls.append((args, kw)))
    (args, kw), = calls
    assert args[0] == "powershell.exe" and args[-2] == "-EncodedCommand"
    script = base64.b64decode(args[-1]).decode("utf-16-le")
    assert "ToastNotificationManager" in script and "$env:ORBIDA_TOAST_TEXT" in script
    # The texts travel in the environment, never inside the script.
    assert kw["env"]["ORBIDA_TOAST_TITLE"] == "Done"
    assert kw["env"]["ORBIDA_TOAST_TEXT"] == "2 completed; it's \"fine\""
    assert kw["env"]["ORBIDA_TOAST_APP"] == APP_USER_MODEL_ID
    assert kw["stdout"] is subprocess.DEVNULL


def test_notify_survives_a_missing_powershell(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def missing(args, **kw):
        raise FileNotFoundError("powershell.exe")
    assert app_setup.notify("Done", "x", popen=missing) is False


def test_notify_is_a_no_op_elsewhere(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert app_setup.notify("Done", "x", popen=lambda *a, **k: 1 / 0) is False


def test_installer_shortcuts_carry_the_app_id():
    # Windows only shows the toast for an app whose Start menu shortcut has this id.
    with open(os.path.join(ROOT, "installer", "Orbida.iss"), encoding="utf-8") as f:
        text = f.read()
    assert f'#define AppUserModelID "{APP_USER_MODEL_ID}"' in text
    assert text.count('AppUserModelID: "{#AppUserModelID}"') == 2


def test_notify_uses_orbida_s_own_icon_before_powershell(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    shown, started = [], []
    assert app_setup.notify("Done", "x", popen=lambda *a, **k: started.append(a),
                            notifier=lambda title, text: shown.append((title, text)) or True)
    assert shown == [("Done", "x")] and started == []


def test_notify_falls_back_to_powershell(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    started = []

    def broken(title, text):
        raise OSError("no icon")
    assert app_setup.notify("Done", "x", popen=lambda *a, **k: started.append(a), notifier=broken)
    assert len(started) == 1


def test_a_running_tray_icon_shows_the_notification():
    import tray

    class Icon:
        notes = []

        def notify(self, message, title=None):
            self.notes.append((title, message))
    icon = tray.Tray("Orbida", None, None, str)
    icon.icon = Icon()
    assert tray.show_notification("Done", "2 completed", icon)
    assert Icon.notes == [("Done", "2 completed")]


def test_without_a_tray_a_short_lived_icon_carries_the_notification(monkeypatch):
    import threading
    import pytest
    pytest.importorskip("PIL")
    import tray
    done = threading.Event()

    class Backend:
        class Icon:
            def __init__(self, name, image, title):
                self.visible, self.notes = False, []

            def notify(self, message, title=None):
                self.notes.append((title, message))

            def run(self, setup):
                setup(self)
                done.set()

            def stop(self):
                self.stopped = True
    assert tray.show_notification("Done", "x", None, Backend, keep=0)
    assert done.wait(5)
