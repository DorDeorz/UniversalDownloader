import os

import pytest

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

    opts = fake_ydl.instances[0].opts
    assert opts["outtmpl"] == os.path.join(str(tmp_path), "YouTube", "%(title)s.%(ext)s")
    assert opts["ffmpeg_location"] == manager.ffmpeg_path


def test_successful_download_is_completed_with_real_path(manager, fake_ydl, tmp_path):
    result = _download(manager, {"save_path": str(tmp_path)})

    ydl = fake_ydl.instances[0]
    assert ydl.extract_calls == [("https://youtu.be/abc", False)]
    assert len(ydl.process_calls) == 1
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

    assert "download_ranges" not in fake_ydl.instances[0].params


def test_manager_uses_bundled_ffmpeg_paths():
    manager = DownloadManager()

    assert manager.ffmpeg_path.endswith(os.path.join("bin", "ffmpeg.exe"))
    assert manager.ffprobe_path.endswith(os.path.join("bin", "ffprobe.exe"))
