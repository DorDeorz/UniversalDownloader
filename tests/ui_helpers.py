"""Helpers for tests that drive a real App window (need Tk and a display)."""

import tempfile
import time
import tkinter

import media_tools
import ui

OK_TOOLS = media_tools.ToolStatus(True, directory="/fake/ffmpeg/bin", version="7.1", source="bundled")


class ToolsOnlyManager:
    """Stands in for DownloadManager until a test installs its own."""

    def __init__(self, tools=OK_TOOLS):
        self.tools = tools

    def ensure_tools(self):
        return self.tools


def pump(app, until=lambda: False, timeout=5):
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)
    return until()


def isolate_settings(monkeypatch):
    """Point the app's settings and logs at a fresh temp folder."""
    monkeypatch.setenv("LOCALAPPDATA", tempfile.mkdtemp(prefix="uvd-test-"))


def make_app(monkeypatch, tools=OK_TOOLS):
    """App with the FFmpeg check stubbed and finished, dialogs silenced."""
    isolate_settings(monkeypatch)
    monkeypatch.setattr(ui, "DownloadManager", lambda: ToolsOnlyManager(tools))
    for name in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(ui.messagebox, name, lambda *a, **k: None)
    app = new_app()
    pump(app, lambda: app.tools is not None)
    return app


def new_app():
    """ui.App(), retried once if Tk fails to initialise.

    Windows CI runners intermittently fail to read Tk's own library files
    ("Can't find a usable tk.tcl") when a process creates many Tk roots; a
    second attempt succeeds. Any other error is raised unchanged.
    """
    try:
        return ui.App()
    except tkinter.TclError as e:
        if "usable tk.tcl" not in str(e) and "usable init.tcl" not in str(e):
            raise
        time.sleep(0.5)
        return ui.App()
