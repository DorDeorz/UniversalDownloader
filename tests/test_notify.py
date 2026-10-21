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
