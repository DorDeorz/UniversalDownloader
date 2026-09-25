import os

import pytest

import yt_dlp

import logic
from logic import DownloadManager
from results import ItemStatus


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

    assert manager.fetch_info("https://youtu.be/abc") == {"error": "Content is private or unavailable", "error_type": "DownloadError"}


def test_fetch_info_turns_exceptions_into_error_dict(manager, fake_ydl):
    fake_ydl.error = RuntimeError("boom")

    assert manager.fetch_info("https://youtu.be/abc") == {"error": "boom", "error_type": "RuntimeError"}


# --- download_video -----------------------------------------------------

def _download(manager, options, url="https://youtu.be/abc"):
    return manager.download_video(url, options, progress_hook=lambda d: None)


def test_download_writes_into_platform_subfolder(manager, fake_ydl, tmp_path):
    _download(manager, {"save_path": str(tmp_path)})

    opts = fake_ydl.instances[-1].opts
    assert opts["outtmpl"] == os.path.join(str(tmp_path), "YouTube", "%(title)s.%(ext)s")
    assert opts["ffmpeg_location"] == manager.ffmpeg_path


def test_successful_download_is_completed_with_real_path(manager, fake_ydl, tmp_path):
    result = _download(manager, {"save_path": str(tmp_path)})

    probe, download = fake_ydl.instances
    assert probe.extract_calls == [("https://youtu.be/abc", False)]
    assert probe.process_calls == []
    assert len(download.process_calls) == 1
    assert result.status is ItemStatus.COMPLETED
    assert result.path == os.path.join(str(tmp_path), "YouTube", "clip.mp4")
    assert result.title == "clip"
    assert result.error is None


def test_failed_download_is_failed_not_completed(manager, fake_ydl, tmp_path):
    fake_ydl.download_error = RuntimeError("network down")

    result = _download(manager, {"save_path": str(tmp_path)})

    assert result.status is ItemStatus.FAILED
    assert result.error == "network down"
    assert result.path is None


def test_metadata_error_is_failed(manager, fake_ydl, tmp_path):
    fake_ydl.error = RuntimeError("private video")

    result = _download(manager, {"save_path": str(tmp_path)})

    assert result.status is ItemStatus.FAILED
    assert result.error == "private video"
    assert fake_ydl.instances[0].process_calls == []


def test_missing_output_file_is_failed(manager, fake_ydl, tmp_path):
    fake_ydl.write_file = False

    result = _download(manager, {"save_path": str(tmp_path)})

    assert result.status is ItemStatus.FAILED
    assert "was not created" in result.error


def test_empty_output_file_is_failed(manager, fake_ydl, tmp_path, monkeypatch):
    real_process = fake_ydl.process_ie_result

    def process_empty(self, info, download=True):
        out = real_process(self, info, download)
        open(out["requested_downloads"][0]["filepath"], "wb").close()
        return out

    monkeypatch.setattr(fake_ydl, "process_ie_result", process_empty)

    result = _download(manager, {"save_path": str(tmp_path)})

    assert result.status is ItemStatus.FAILED
    assert "empty" in result.error


def test_title_falls_back_to_given_title(manager, fake_ydl, tmp_path):
    fake_ydl.error = RuntimeError("boom")

    result = manager.download_video("https://youtu.be/abc", {"save_path": str(tmp_path)}, title="Queued title")

    assert result.title == "Queued title"


def test_no_trim_means_no_download_ranges(manager, fake_ydl, tmp_path):
    _download(manager, {"save_path": str(tmp_path)})

    assert "download_ranges" not in fake_ydl.instances[-1].params


def test_manager_uses_bundled_ffmpeg_paths():
    manager = DownloadManager()

    assert manager.ffmpeg_path.endswith(os.path.join("bin", "ffmpeg.exe"))
    assert manager.ffprobe_path.endswith(os.path.join("bin", "ffprobe.exe"))


# --- format handling in download_video ----------------------------------

def test_invalid_format_fails_before_network(manager, fake_ydl, tmp_path):
    result = _download(manager, {"save_path": str(tmp_path), "mode": "Audio Only", "format": "mp4"})

    assert result.status is ItemStatus.FAILED
    assert "not an audio format" in result.error
    assert fake_ydl.instances == []


def test_audio_only_output_has_codec_extension(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"id": "abc", "title": "song", "ext": "webm", "acodec": "opus"}

    result = _download(manager, {"save_path": str(tmp_path), "mode": "Audio Only", "format": "m4a"})

    assert result.status is ItemStatus.COMPLETED
    assert result.path.endswith("song.m4a")


def test_audio_only_without_audio_is_failed(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"id": "abc", "title": "silent", "ext": "mp4", "vcodec": "avc1", "acodec": "none"}

    result = _download(manager, {"save_path": str(tmp_path), "mode": "Audio Only", "format": "mp3"})

    assert result.status is ItemStatus.FAILED
    assert result.error == "This media has no audio track"


def test_video_only_adds_audio_stripper(manager, fake_ydl, tmp_path):
    _download(manager, {"save_path": str(tmp_path), "mode": "Video Only", "format": "mp4"})

    (pp, when), = fake_ydl.instances[-1].added_pps
    assert isinstance(pp, logic.StripAudioPP)
    assert when == "post_process"


def test_unavailable_quality_gets_clear_error(manager, fake_ydl, tmp_path):
    fake_ydl.error = yt_dlp.utils.DownloadError("ERROR: [youtube] x: Requested format is not available.")

    result = _download(manager, {"save_path": str(tmp_path), "quality": "720p"})

    assert result.error == "No 720p or lower version of this video is available; try a higher quality"


def test_incompatible_container_is_re_encoded(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"id": "abc", "title": "clip", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a"}

    result = _download(manager, {"save_path": str(tmp_path), "format": "webm"})

    pps = fake_ydl.instances[-1].opts["postprocessors"]
    assert pps[0] == {"key": "FFmpegVideoConvertor", "preferedformat": "webm"}
    assert result.path.endswith("clip.webm")


def test_format_is_logged(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"id": "abc", "title": "clip", "ext": "mp4", "vcodec": "avc1.64", "acodec": "mp4a.40.2",
                     "width": 1280, "height": 720}
    lines = []

    manager.download_video("https://youtu.be/abc", {"save_path": str(tmp_path)}, log_callback=lines.append)

    assert "Format: 1280x720 avc1 mp4a -> mp4" in lines
