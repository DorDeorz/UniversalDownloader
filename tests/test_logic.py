import os

import pytest

from logic import DownloadManager


# --- platform detection -------------------------------------------------

@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.youtube.com/watch?v=abc", "YouTube"),
        ("https://youtu.be/abc", "YouTube"),
        ("https://www.tiktok.com/@u/video/1", "TikTok"),
        ("https://www.instagram.com/p/abc/", "Instagram"),
        ("https://twitter.com/u/status/1", "X_Twitter"),
        ("https://x.com/u/status/1", "X_Twitter"),
        ("https://vimeo.com/123", "Other"),
    ],
)
def test_get_platform_name(manager, url, expected):
    assert manager.get_platform_name(url) == expected


# --- fetch_info ---------------------------------------------------------

def test_fetch_info_returns_info_without_downloading(manager, fake_ydl):
    fake_ydl.info = {"title": "clip", "entries": None}

    assert manager.fetch_info("https://youtu.be/abc") == {"title": "clip", "entries": None}
    ydl = fake_ydl.instances[0]
    assert ydl.extract_calls == [("https://youtu.be/abc", False)]
    assert ydl.opts["extract_flat"] is True


def test_fetch_info_reports_unavailable_content_as_error(manager, fake_ydl):
    fake_ydl.info = None

    assert manager.fetch_info("https://youtu.be/abc") == {"error": "Content is private or unavailable"}


def test_fetch_info_turns_exceptions_into_error_dict(manager, fake_ydl):
    fake_ydl.error = RuntimeError("boom")

    assert manager.fetch_info("https://youtu.be/abc") == {"error": "boom"}


# --- download_video -----------------------------------------------------

def _download(manager, options, url="https://youtu.be/abc"):
    results = {"done": [], "errors": []}
    manager.download_video(
        url,
        options,
        progress_hook=lambda d: None,
        complete_callback=results["done"].append,
        error_callback=results["errors"].append,
    )
    return results


def test_download_writes_into_platform_subfolder(manager, fake_ydl, tmp_path):
    _download(manager, {"save_path": str(tmp_path)})

    opts = fake_ydl.instances[0].opts
    assert opts["outtmpl"] == os.path.join(str(tmp_path), "YouTube", "%(title)s.%(ext)s")
    assert opts["ffmpeg_location"] == manager.ffmpeg_path


@pytest.mark.parametrize(
    "quality, expected_format",
    [
        ("Best", "bestvideo+bestaudio/best"),
        ("4K", "bestvideo[height<=2160]+bestaudio/best"),
        ("1080p", "bestvideo[height<=1080]+bestaudio/best"),
        ("720p", "bestvideo[height<=720]+bestaudio/best"),
    ],
)
def test_video_quality_maps_to_format_selector(manager, fake_ydl, tmp_path, quality, expected_format):
    _download(manager, {"save_path": str(tmp_path), "mode": "Video + Audio", "format": "mkv", "quality": quality})

    opts = fake_ydl.instances[0].opts
    assert opts["format"] == expected_format
    assert opts["merge_output_format"] == "mkv"


def test_audio_only_extracts_audio_with_requested_codec(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"title": "song", "ext": "webm"}

    results = _download(manager, {"save_path": str(tmp_path), "mode": "Audio Only", "format": "mp3"})

    opts = fake_ydl.instances[0].opts
    assert opts["format"] == "bestaudio/best"
    extract = opts["postprocessors"][0]
    assert extract["key"] == "FFmpegExtractAudio"
    assert extract["preferredcodec"] == "mp3"
    assert results["done"] == [os.path.join(str(tmp_path), "YouTube", "song.mp3")]


def test_successful_download_calls_complete_callback(manager, fake_ydl, tmp_path):
    results = _download(manager, {"save_path": str(tmp_path)})

    assert fake_ydl.instances[0].extract_calls == [("https://youtu.be/abc", True)]
    assert results == {"done": [os.path.join(str(tmp_path), "YouTube", "clip.mp4")], "errors": []}


def test_failed_download_calls_error_callback(manager, fake_ydl, tmp_path):
    fake_ydl.error = RuntimeError("network down")

    results = _download(manager, {"save_path": str(tmp_path)})

    assert results == {"done": [], "errors": ["network down"]}


def test_no_trim_means_no_download_ranges(manager, fake_ydl, tmp_path):
    _download(manager, {"save_path": str(tmp_path)})

    assert "download_ranges" not in fake_ydl.instances[0].opts


@pytest.mark.xfail(reason="ISSUES.md #1: trim passes a string range to download_range_func; fixed in MVP step 7")
def test_trim_range_is_usable_by_yt_dlp(manager, fake_ydl, tmp_path):
    _download(manager, {"save_path": str(tmp_path), "trim_start": "10", "trim_end": "20"})

    ranges = fake_ydl.instances[0].opts["download_ranges"]
    sections = list(ranges({"duration": 60}, None))
    assert sections == [{"start_time": 10.0, "end_time": 20.0}]


def test_manager_uses_bundled_ffmpeg_paths():
    manager = DownloadManager()

    assert manager.ffmpeg_path.endswith(os.path.join("bin", "ffmpeg.exe"))
    assert manager.ffprobe_path.endswith(os.path.join("bin", "ffprobe.exe"))
