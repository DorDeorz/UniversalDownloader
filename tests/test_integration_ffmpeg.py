"""End-to-end downloads with real yt-dlp and real FFmpeg, no internet.

Test media is generated with FFmpeg and served from a local HTTP server, so
format selection, merging, conversion, trimming, audio stripping, file
naming and cancellation all run for real. Skipped when FFmpeg/ffprobe are
not available (bundled or on PATH).
"""

import functools
import http.server
import json
import os
import subprocess
import threading
import time

import pytest

import logic
import media_tools
from results import ItemStatus

TOOLS = media_tools.find_tools()
pytestmark = pytest.mark.skipif(not TOOLS.ok, reason=f"needs FFmpeg: {TOOLS.error}")


class _Handler(http.server.SimpleHTTPRequestHandler):
    throttle = 0.0

    def log_message(self, *args):
        pass

    def copyfile(self, source, outputfile):
        while chunk := source.read(64 * 1024):
            try:
                outputfile.write(chunk)
            except OSError:
                return
            if self.throttle:
                time.sleep(self.throttle)


class _Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # clients (yt-dlp, a cancel) may close connections early


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    folder = tmp_path_factory.mktemp("media")
    ff = TOOLS.ffmpeg

    def make(name, *args):
        subprocess.run([ff, "-loglevel", "error", "-y", *args, str(folder / name)], check=True)

    make("clip.mp4", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
         "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac")
    (folder / "big.bin").write_bytes(os.urandom(4 * 1024 * 1024))
    return folder


@pytest.fixture(scope="module")
def server(media):
    handler = functools.partial(_Handler, directory=str(media))
    srv = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def manager():
    media_tools.activate(TOOLS)
    return logic.DownloadManager(tools=TOOLS)


def probe(path):
    out = subprocess.run([TOOLS.ffprobe, "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,height:stream_disposition=attached_pic:format=duration",
                          "-of", "json", path], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    streams = [(s["codec_type"], s["codec_name"]) for s in data["streams"]
               if not s.get("disposition", {}).get("attached_pic")]
    return streams, float(data["format"]["duration"])


def download(manager, server, tmp_path, **options):
    options.setdefault("save_path", str(tmp_path))
    return manager.download_video(f"{server}/{options.pop('src', 'clip.mp4')}", options)


def test_video_and_audio_to_mkv(manager, server, tmp_path):
    result = download(manager, server, tmp_path, mode="Video + Audio", format="mkv", quality="Best")
    assert result.status is ItemStatus.COMPLETED, result.error
    assert result.path.endswith(".mkv")
    streams, duration = probe(result.path)
    assert streams == [("video", "h264"), ("audio", "aac")]
    assert duration == pytest.approx(6, abs=0.5)


def test_h264_to_webm_is_re_encoded(manager, server, tmp_path):
    result = download(manager, server, tmp_path, mode="Video + Audio", format="webm", quality="Best")
    assert result.status is ItemStatus.COMPLETED, result.error
    assert probe(result.path)[0] == [("video", "vp9"), ("audio", "opus")]


def test_video_only_has_no_audio(manager, server, tmp_path):
    result = download(manager, server, tmp_path, mode="Video Only", format="mp4", quality="Best")
    assert result.status is ItemStatus.COMPLETED, result.error
    assert probe(result.path)[0] == [("video", "h264")]


@pytest.mark.parametrize("fmt, codec", [("mp3", "mp3"), ("m4a", "aac"), ("opus", "opus"), ("flac", "flac")])
def test_audio_only_codecs(manager, server, tmp_path, fmt, codec):
    result = download(manager, server, tmp_path, mode="Audio Only", format=fmt, quality="Best")
    assert result.status is ItemStatus.COMPLETED, result.error
    assert result.path.endswith("." + fmt)
    assert probe(result.path)[0] == [("audio", codec)]


def test_trim_cuts_the_requested_range(manager, server, tmp_path):
    result = download(manager, server, tmp_path, mode="Video + Audio", format="mp4", quality="Best",
                      trim_start="1", trim_end="3")
    assert result.status is ItemStatus.COMPLETED, result.error
    assert probe(result.path)[1] == pytest.approx(2, abs=0.3)


def test_trim_with_unknown_length_warns_and_stops_at_the_end(manager, server, tmp_path):
    # A direct file link reports no duration, so an end past the real end
    # cannot be rejected up front; the cut simply stops at the end.
    lines = []
    result = manager.download_video(f"{server}/clip.mp4", {"save_path": str(tmp_path), "trim_start": "2",
                                                           "trim_end": "30"}, log_callback=lines.append)
    assert result.status is ItemStatus.COMPLETED, result.error
    assert probe(result.path)[1] == pytest.approx(4, abs=0.5)
    assert any("does not report its length" in line for line in lines)


def test_second_download_gets_suffix(manager, server, tmp_path):
    first = download(manager, server, tmp_path, mode="Video + Audio", format="mp4", quality="Best")
    second = download(manager, server, tmp_path, mode="Audio Only", format="mp3", quality="Best",
                      trim_start="0", trim_end="2")
    assert first.path.endswith("clip.mp4")
    assert second.path.endswith("clip (2).mp3")
    assert probe(second.path)[1] == pytest.approx(2, abs=0.3)
    assert probe(first.path)[1] == pytest.approx(6, abs=0.5)


def test_cancel_stops_and_cleans_up(manager, server, tmp_path, monkeypatch):
    monkeypatch.setattr(_Handler, "throttle", 0.05)
    cancel = threading.Event()
    updates = []

    def hook(d):
        updates.append(d)
        if len(updates) == 3:
            cancel.set()

    result = manager.download_video(f"{server}/big.bin", {"save_path": str(tmp_path), "format": "mkv"},
                                    progress_hook=hook, cancel_event=cancel)

    assert result.status is ItemStatus.CANCELLED
    assert [f for _, _, files in os.walk(tmp_path) for f in files] == []
