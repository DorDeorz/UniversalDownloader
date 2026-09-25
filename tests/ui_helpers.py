"""Helpers for tests that drive a real App window (need Tk and a display)."""

import time

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


def make_app(monkeypatch, tools=OK_TOOLS):
    """App with the FFmpeg check stubbed and finished, dialogs silenced."""
    monkeypatch.setattr(ui, "DownloadManager", lambda: ToolsOnlyManager(tools))
    for name in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(ui.messagebox, name, lambda *a, **k: None)
    app = ui.App()
    pump(app, lambda: app.tools is not None)
    return app
