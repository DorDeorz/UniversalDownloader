import os
import sys

# Make the top-level modules (events, logic, ui, utils) importable from tests.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

import logic  # noqa: E402


class FakeYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL so tests never touch the network.

    Records the options each instance was built with; tests set
    ``info`` or ``error`` on the class to control what extract_info does.
    """

    instances = []
    info = {"title": "clip", "ext": "mp4"}
    error = None

    def __init__(self, opts):
        self.opts = opts
        self.extract_calls = []
        FakeYoutubeDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        self.extract_calls.append((url, download))
        if FakeYoutubeDL.error is not None:
            raise FakeYoutubeDL.error
        return FakeYoutubeDL.info

    def prepare_filename(self, info):
        folder = os.path.dirname(self.opts["outtmpl"])
        return os.path.join(folder, f"{info['title']}.{info['ext']}")


@pytest.fixture
def fake_ydl(monkeypatch):
    FakeYoutubeDL.instances = []
    FakeYoutubeDL.info = {"title": "clip", "ext": "mp4"}
    FakeYoutubeDL.error = None
    monkeypatch.setattr(logic.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    return FakeYoutubeDL


@pytest.fixture
def manager():
    return logic.DownloadManager()
