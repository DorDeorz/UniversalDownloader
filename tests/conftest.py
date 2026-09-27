import os
import sys

# Make the top-level modules (events, logic, ui, utils) importable from tests.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

import yt_dlp  # noqa: E402
from yt_dlp.postprocessor.ffmpeg import ACODECS  # noqa: E402

import logic  # noqa: E402
import media_tools  # noqa: E402

_RealYoutubeDL = yt_dlp.YoutubeDL


class FakeYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL so tests never touch the network.

    Records the options each instance was built with. Class attributes
    control behaviour (reset by the ``fake_ydl`` fixture):

    - ``info``: what extract_info returns (a copy), or None.
    - ``error``: raised by extract_info.
    - ``download_error``: raised by process_ie_result (the download step).
    - ``write_file``: when False, the "download" produces no output file.
    - ``warning``: sent to the yt-dlp logger during extract_info.

    process_ie_result simulates a download: it calls the progress hooks and
    writes a small file at the name the real yt-dlp would prepare (with the
    extension changed when an audio extraction postprocessor is set).
    """

    instances = []
    info = {"id": "abc", "title": "clip", "ext": "mp4"}
    error = None
    download_error = None
    write_file = True
    warning = None

    def __init__(self, opts):
        self.opts = opts
        self.params = dict(opts)
        self.extract_calls = []
        self.process_calls = []
        self.added_pps = []
        FakeYoutubeDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def report_warning(self, *args, **kwargs):
        pass

    def write_debug(self, *args, **kwargs):
        pass

    def add_post_processor(self, pp, when="post_process"):
        self.added_pps.append((pp, when))

    def extract_info(self, url, download=False):
        self.extract_calls.append((url, download))
        if FakeYoutubeDL.warning and self.params.get("logger"):
            self.params["logger"].warning(FakeYoutubeDL.warning)
        if FakeYoutubeDL.error is not None:
            raise FakeYoutubeDL.error
        if FakeYoutubeDL.info is None:
            return None
        info = dict(FakeYoutubeDL.info)
        if download:
            return self.process_ie_result(info, download=True)
        return info

    def process_ie_result(self, info, download=True):
        self.process_calls.append(info)
        if not download:
            return dict(info)
        for hook in self.params.get("progress_hooks") or []:
            hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
        if FakeYoutubeDL.download_error is not None:
            raise FakeYoutubeDL.download_error
        path = self.prepare_filename(info)
        for pp in self.params.get("postprocessors") or []:
            if pp.get("key") == "FFmpegExtractAudio":
                ext = ACODECS[pp["preferredcodec"]][0]
                path = os.path.splitext(path)[0] + "." + ext
            elif pp.get("key") in ("FFmpegVideoRemuxer", "FFmpegVideoConvertor"):
                path = os.path.splitext(path)[0] + "." + pp["preferedformat"]
        if FakeYoutubeDL.write_file:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"media")
        for hook in self.params.get("progress_hooks") or []:
            hook({"status": "finished", "filename": path})
        info = dict(info)
        info["requested_downloads"] = [{"filepath": path}]
        return info

    def prepare_filename(self, info):
        real = _RealYoutubeDL({"outtmpl": self.params["outtmpl"], "quiet": True})
        return real.prepare_filename({"ext": "mp4", **info})


@pytest.fixture
def fake_ydl(monkeypatch):
    FakeYoutubeDL.instances = []
    FakeYoutubeDL.info = {"id": "abc", "title": "clip", "ext": "mp4"}
    FakeYoutubeDL.error = None
    FakeYoutubeDL.download_error = None
    FakeYoutubeDL.write_file = True
    FakeYoutubeDL.warning = None
    monkeypatch.setattr(logic.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    return FakeYoutubeDL


FAKE_TOOLS = media_tools.ToolStatus(True, directory="/fake/ffmpeg/bin", version="7.1", source="bundled")


@pytest.fixture
def manager():
    return logic.DownloadManager(tools=FAKE_TOOLS)


@pytest.fixture(autouse=True)
def english_ui(monkeypatch):
    """Tests check English texts, so 'System language' means English here."""
    import i18n
    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    i18n.set_language("en")
    yield
    i18n.set_language("en")
