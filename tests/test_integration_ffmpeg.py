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
    """Static files with byte-range support, like a real media server.

    FFmpeg seeks with Range requests when it reads a URL directly (trimmed
    downloads); without them some FFmpeg versions stop after the headers.
    """

    throttle = 0.0
    drop_after = None  # bytes after which the next response is cut off once (a dropped connection)
    # "cut": the second response (the download; the first is yt-dlp's look
    # at the link) stops after 64 KB and the server is then "down" (503)
    # until the test sets it back to None.
    outage = None
    ranges = []  # the Range header of each request

    def log_message(self, *args):
        pass

    def send_head(self):
        self._range = None
        header = self.headers.get("Range", "")
        path = self.translate_path(self.path)
        _Handler.ranges.append(header)
        if _Handler.outage == "down":
            self.send_error(503)
            return None
        self._cut = _Handler.outage == "cut" and len(_Handler.ranges) == 2
        if not header.startswith("bytes=") or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        first, _, last = header[len("bytes="):].split(",")[0].partition("-")
        if first:
            start, end = int(first), int(last) if last else size - 1
        else:
            start, end = max(size - int(last), 0), size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        f = open(path, "rb")
        f.seek(start)
        self._range = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._range))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        remaining = self._range
        drop_after, sent = _Handler.drop_after, 0
        while chunk := source.read(64 * 1024 if remaining is None else min(64 * 1024, remaining)):
            if drop_after is not None and sent >= drop_after:
                _Handler.drop_after = None
                self.close_connection = True
                return
            if getattr(self, "_cut", False) and sent >= 64 * 1024:
                _Handler.outage = "down"
                self.close_connection = True
                return
            sent += len(chunk)
            if remaining is not None:
                remaining -= len(chunk)
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
    # HLS whose segments are byte ranges of one file, as Reddit serves video.
    subprocess.run([ff, "-loglevel", "error", "-y", "-i", str(folder / "clip.mp4"), "-c:a", "copy", "-c:v", "libx264", "-g", "25", "-f", "hls",
                    "-hls_time", "1", "-hls_playlist_type", "vod", "-hls_flags", "single_file",
                    str(folder / "ranges.m3u8")], check=True)
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


def test_byte_range_segments_with_speed_settings(manager, server, media, tmp_path):
    # The app's speed settings set http_chunk_size; yt-dlp then mistook each
    # byte-range segment for an unfinished chunk of the whole file and gave up
    # with "Conflicting range" (Reddit videos failed this way).
    assert (media / "ranges.m3u8").read_text().count("#EXT-X-BYTERANGE") > 1
    result = download(manager, server, tmp_path, src="ranges.m3u8", mode="Video + Audio", format="mp4",
                      quality="Best", concurrent_fragment_downloads=4, http_chunk_size=10 * 1024 * 1024)
    assert result.status is ItemStatus.COMPLETED, result.error
    assert probe(result.path)[1] == pytest.approx(6, abs=0.5)


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


@pytest.mark.parametrize("dropped", [False, True])
def test_pause_holds_the_download_and_resume_finishes_it(manager, server, media, tmp_path, monkeypatch, dropped):
    # While paused, the site may drop the idle connection; yt-dlp then asks for the rest.
    monkeypatch.setattr(_Handler, "throttle", 0.02)
    monkeypatch.setattr(_Handler, "drop_after", 32 * 1024 if dropped else None)
    monkeypatch.setattr(logic, "PAUSE_POLL_SECONDS", 0.05)
    pause = threading.Event()
    times = []

    def hook(d):
        if d.get("status") != "downloading":
            return
        times.append(time.monotonic())
        if len(times) == 2:
            pause.set()
            threading.Timer(1.0, pause.clear).start()

    result = manager.download_video(f"{server}/clip.mp4", {"save_path": str(tmp_path), "format": "mp4"},
                                    progress_hook=hook, pause_event=pause)

    assert result.status is ItemStatus.COMPLETED, result.error
    assert max(b - a for a, b in zip(times, times[1:])) >= 0.9  # nothing moved while paused
    assert probe(result.path)[1] == pytest.approx(6, abs=0.5)
    assert _Handler.drop_after is None  # the connection was dropped (when asked to)


def test_cancel_works_while_paused(manager, server, tmp_path, monkeypatch):
    monkeypatch.setattr(_Handler, "throttle", 0.02)
    monkeypatch.setattr(logic, "PAUSE_POLL_SECONDS", 0.05)
    pause, cancel = threading.Event(), threading.Event()

    def hook(d):
        if d.get("status") == "downloading" and not pause.is_set():
            pause.set()
            threading.Timer(0.3, cancel.set).start()

    started = time.monotonic()
    result = manager.download_video(f"{server}/clip.mp4", {"save_path": str(tmp_path), "format": "mp4"},
                                    progress_hook=hook, cancel_event=cancel, pause_event=pause)
    assert result.status is ItemStatus.CANCELLED and time.monotonic() - started < 10
    assert [f for _, _, files in os.walk(tmp_path) for f in files] == []


def test_cancel_removes_the_thumbnail_and_new_folders(manager, server, media, tmp_path, monkeypatch):
    # A web page with a video and a thumbnail: yt-dlp writes the thumbnail
    # before the video, so a cancel used to leave it behind.
    subprocess.run([TOOLS.ffmpeg, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=red:s=64x36",
                    "-frames:v", "1", str(media / "thumb.webp")], check=True)
    (media / "page.html").write_text(
        f'<html><head><title>Page clip</title><meta property="og:image" content="{server}/thumb.webp">'
        f'</head><body><video src="{server}/clip.mp4"></video></body></html>')
    monkeypatch.setattr(_Handler, "throttle", 0.05)
    cancel = threading.Event()

    def hook(d):
        if d.get("status") == "downloading":
            cancel.set()

    result = manager.download_video(f"{server}/page.html", {"save_path": str(tmp_path), "format": "mkv"},
                                    progress_hook=hook, cancel_event=cancel)

    assert result.status is ItemStatus.CANCELLED
    assert list(tmp_path.iterdir()) == []


def _sponsor_segments(monkeypatch, segments):
    # The test clip comes from the generic extractor; SponsorBlock only knows YouTube.
    monkeypatch.setattr(logic.QuietSponsorBlockPP, "EXTRACTORS", {"Generic": "YouTube"})
    monkeypatch.setattr(logic.QuietSponsorBlockPP, "_get_sponsor_segments", lambda self, video_id, service: segments())


def test_sponsorblock_cuts_the_segments(manager, server, tmp_path, monkeypatch):
    _sponsor_segments(monkeypatch, lambda: [{"segment": [2, 4], "category": "sponsor", "actionType": "skip",
                                             "videoDuration": 0, "description": ""}])
    for mode, fmt in (("Video + Audio", "mp4"), ("Audio Only", "mp3")):
        result = download(manager, server, tmp_path, mode=mode, format=fmt, quality="Best", sponsorblock=True)
        assert result.status is ItemStatus.COMPLETED, result.error
        assert probe(result.path)[1] == pytest.approx(4, abs=0.5)


def test_sponsorblock_unavailable_keeps_the_whole_video(manager, server, tmp_path, monkeypatch):
    def offline():
        raise logic.yt_dlp.utils.PostProcessingError("Unable to communicate with SponsorBlock API")
    _sponsor_segments(monkeypatch, offline)
    result = download(manager, server, tmp_path, mode="Video + Audio", format="mp4", quality="Best",
                      sponsorblock=True)
    assert result.status is ItemStatus.COMPLETED, result.error
    assert probe(result.path)[1] == pytest.approx(6, abs=0.5)


def test_sponsorblock_is_skipped_for_a_trimmed_download(manager, server, tmp_path, monkeypatch):
    _sponsor_segments(monkeypatch, lambda: pytest.fail("SponsorBlock asked for a trimmed download"))
    lines = []
    result = manager.download_video(f"{server}/clip.mp4", {"save_path": str(tmp_path), "trim_start": "1",
                                                           "trim_end": "5", "sponsorblock": True},
                                    log_callback=lines.append)
    assert result.status is ItemStatus.COMPLETED, result.error
    assert probe(result.path)[1] == pytest.approx(4, abs=0.3)
    assert "SponsorBlock: skipped for a trimmed download" in lines


def test_a_failed_download_is_continued_from_its_part_file(manager, server, media, tmp_path, monkeypatch):
    subprocess.run([TOOLS.ffmpeg, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "20", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(media / "long.mp4")], check=True)
    assert (media / "long.mp4").stat().st_size > 300 * 1024
    monkeypatch.setattr(_Handler, "ranges", [])
    monkeypatch.setattr(_Handler, "outage", "cut")
    lines = []
    options = {"save_path": str(tmp_path), "mode": "Video + Audio", "format": "mp4", "quality": "Best"}

    first = manager.download_video(f"{server}/long.mp4", dict(options), log_callback=lines.append)
    assert first.status is ItemStatus.FAILED
    kept = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())
    assert any(name.endswith(".part") for name in kept) and any(name.endswith(".orbida-resume") for name in kept)
    assert any("Kept the partial download" in line for line in lines)

    monkeypatch.setattr(_Handler, "outage", None)
    _Handler.ranges.clear()
    second = manager.download_video(f"{server}/long.mp4", dict(options), log_callback=lines.append)
    assert second.status is ItemStatus.COMPLETED, second.error
    assert os.path.basename(second.path) == "long.mp4"  # the same name, not "long (2).mp4"
    assert any(r.startswith("bytes=") and int(r[6:].split("-")[0]) > 32 * 1024 for r in _Handler.ranges)
    assert any("Continuing the unfinished download" in line for line in lines)
    assert probe(second.path)[1] == pytest.approx(20, abs=0.5)
    assert sorted(p.name for p in second_folder_files(second.path)) == ["long.mp4"]


def second_folder_files(path):
    return [p for p in __import__("pathlib").Path(path).parent.iterdir() if p.is_file()]


def test_another_video_never_continues_a_part_file(manager, server, tmp_path, monkeypatch):
    # A partial file of one video, under the name another video would get.
    monkeypatch.setattr(_Handler, "ranges", [])
    folder = tmp_path / "Other"
    folder.mkdir()
    (folder / "clip.mp4.part").write_bytes(b"x" * 100_000)
    (folder / "clip.orbida-resume").write_text(json.dumps(
        {"video": "Generic:something-else", "formats": "mp4", "ext": "mp4", "mode": "Video + Audio"}))
    result = download(manager, server, tmp_path, mode="Video + Audio", format="mp4", quality="Best")
    assert result.status is ItemStatus.COMPLETED, result.error
    assert os.path.basename(result.path) == "clip (2).mp4"
    assert probe(result.path)[1] == pytest.approx(6, abs=0.5)
    assert not any(r.startswith("bytes=100000") for r in _Handler.ranges)


def test_a_video_download_without_a_video_track_fails(manager, server, media, tmp_path):
    # An audio file opened in Video + Audio mode used to be saved as a "video"
    # that only holds sound; ffprobe now finds the missing video track.
    subprocess.run([TOOLS.ffmpeg, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3",
                    "-c:a", "aac", str(media / "sound.m4a")], check=True)
    result = manager.download_video(f"{server}/sound.m4a", {"save_path": str(tmp_path), "mode": "Video + Audio",
                                                            "format": "mkv", "quality": "Best"})
    assert result.status is ItemStatus.FAILED
    assert result.error == "The downloaded file has no video track"
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []
