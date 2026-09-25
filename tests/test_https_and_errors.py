"""HTTPS verification and error visibility for yt-dlp options (MVP step 4).

Covers ISSUES.md #2 (certificate verification disabled), #5 (errors
silenced by ignoreerrors/quiet/no_warnings) and #26 (error type lost).
yt_dlp.YoutubeDL is replaced with a fake, so no network is used.
"""
import pytest
import yt_dlp

import logic
from results import ItemStatus

SILENCING_KEYS = ("nocheckcertificate", "quiet", "no_warnings")


def run_download(manager, options=None, log=None, tmp=None):
    return manager.download_video(
        "https://www.youtube.com/watch?v=x",
        options or {"save_path": str(tmp or "/out")},
        lambda d: None,
        log_callback=log,
    )


def test_download_keeps_certificate_verification_and_does_not_silence(fake_ydl, manager):
    run_download(manager)
    opts = fake_ydl.instances[-1].opts
    for key in SILENCING_KEYS:
        assert key not in opts
    assert "ignoreerrors" not in opts
    assert isinstance(opts["logger"], logic.YtDlpLogger)


@pytest.mark.parametrize("mode", ["Video + Audio", "Audio Only", "Video Only"])
def test_every_mode_keeps_verification(fake_ydl, manager, mode):
    run_download(manager, {"save_path": "/out", "mode": mode, "format": "mp3"})
    assert "nocheckcertificate" not in fake_ydl.instances[-1].opts


def test_fetch_info_keeps_certificate_verification(fake_ydl, manager):
    manager.fetch_info("https://www.youtube.com/playlist?list=x")
    opts = fake_ydl.instances[-1].opts
    for key in SILENCING_KEYS:
        assert key not in opts
    assert isinstance(opts["logger"], logic.YtDlpLogger)


def test_download_error_is_a_failed_result(fake_ydl, manager):
    fake_ydl.error = yt_dlp.utils.DownloadError("ERROR: [youtube] x: Video unavailable")
    result = run_download(manager)
    assert result.status is ItemStatus.FAILED
    assert result.error == "[youtube] x: Video unavailable"


def test_certificate_error_is_reported(fake_ydl, manager):
    fake_ydl.error = yt_dlp.utils.DownloadError(
        "ERROR: Unable to download webpage: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
    )
    result = run_download(manager)
    assert result.status is ItemStatus.FAILED
    assert "CERTIFICATE_VERIFY_FAILED" in result.error


def test_no_info_is_a_failure_not_success(fake_ydl, manager):
    fake_ydl.info = None
    result = run_download(manager)
    assert result.status is ItemStatus.FAILED
    assert result.error == "No media information returned"


def test_success_is_completed(fake_ydl, manager, tmp_path):
    result = run_download(manager, tmp=tmp_path)
    assert result.status is ItemStatus.COMPLETED
    assert result.path.endswith("clip.mp4")


def test_warnings_reach_log_callback(fake_ydl, manager):
    fake_ydl.warning = "Requested format is not available"
    lines = []
    run_download(manager, log=lines.append)
    assert lines == ["Warning: Requested format is not available"]


def test_fetch_info_error_keeps_type(fake_ydl, manager):
    fake_ydl.error = yt_dlp.utils.DownloadError("ERROR: Unsupported URL: https://example.com")
    result = manager.fetch_info("https://example.com")
    assert result == {"error": "Unsupported URL: https://example.com", "error_type": "DownloadError"}


def test_logger_without_callback_does_not_fail():
    logger = logic.YtDlpLogger()
    logger.debug("d")
    logger.info("i")
    logger.warning("w")
    logger.error("e")


def test_real_youtubedl_accepts_options(manager):
    """The real YoutubeDL verifies certificates with these options."""
    opts = logic.base_ydl_options()
    with yt_dlp.YoutubeDL(opts) as ydl:
        assert not ydl.params.get("nocheckcertificate")


def test_fetch_info_keeps_reason_when_ignoreerrors_returns_none(fake_ydl, manager, monkeypatch):
    def extract_info(self, url, download=False):
        self.opts["logger"].error("ERROR: [generic] x: Unable to download webpage: certificate verify failed")
        return None

    monkeypatch.setattr(fake_ydl, "extract_info", extract_info)
    result = manager.fetch_info("https://example.com")
    assert result == {
        "error": "[generic] x: Unable to download webpage: certificate verify failed",
        "error_type": "DownloadError",
    }
