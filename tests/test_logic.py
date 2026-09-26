import os

import pytest
import yt_dlp

import logic
from logic import DownloadManager
from results import ItemStatus
from conftest import FAKE_TOOLS


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
    fake_ydl.info = {"id": "abc", "title": "clip", "ext": "mp4", "extractor_key": "Youtube"}
    _download(manager, {"save_path": str(tmp_path)})

    opts = fake_ydl.instances[-1].opts
    assert opts["outtmpl"] == os.path.join(str(tmp_path), "YouTube", "clip") + ".%(ext)s"
    assert opts["windowsfilenames"] is True
    assert opts["overwrites"] is False


def test_successful_download_is_completed_with_real_path(manager, fake_ydl, tmp_path):
    result = _download(manager, {"save_path": str(tmp_path)})

    probe, download = fake_ydl.instances[0], fake_ydl.instances[-1]
    assert probe.extract_calls == [("https://youtu.be/abc", False)]
    assert probe.process_calls == []
    assert len(download.process_calls) == 1
    assert result.status is ItemStatus.COMPLETED
    assert result.path == os.path.join(str(tmp_path), "Other", "clip.mp4")
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


def test_manager_passes_tools_folder_to_yt_dlp(manager, fake_ydl, tmp_path):
    _download(manager, {"save_path": str(tmp_path)})

    assert fake_ydl.instances[-1].opts["ffmpeg_location"] == "/fake/ffmpeg/bin"


def test_missing_ffmpeg_fails_item_with_clear_error(fake_ydl, tmp_path):
    tools = logic.media_tools.ToolStatus(False, error="bin/ffmpeg.exe is a Git LFS pointer")
    result = DownloadManager(tools=tools).download_video("https://youtu.be/abc", {"save_path": str(tmp_path)})

    assert result.status is ItemStatus.FAILED
    assert result.error == "bin/ffmpeg.exe is a Git LFS pointer"
    assert fake_ydl.instances == []


def test_tools_are_detected_once_on_first_use(fake_ydl, tmp_path, monkeypatch):
    calls = []
    status = logic.media_tools.ToolStatus(True, directory=str(tmp_path))
    monkeypatch.setattr(logic.media_tools, "find_tools", lambda: calls.append(1) or status)
    monkeypatch.setattr(logic.media_tools, "activate", lambda s: None)
    manager = DownloadManager()

    manager.download_video("https://youtu.be/a", {"save_path": str(tmp_path)})
    manager.download_video("https://youtu.be/b", {"save_path": str(tmp_path)})

    assert calls == [1]


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


# --- YouTube bot check ------------------------------------------------------------

BOT_ERROR = ("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. "
             "Use --cookies-from-browser or --cookies for the authentication.")


def _clients(instance):
    return instance.opts.get("extractor_args", {}).get("youtube", {}).get("player_client")


@pytest.fixture
def bot_check(fake_ydl, monkeypatch):
    """YouTube refuses every player client except the ones in ``allowed``."""
    allowed = {"clients": ("tv",)}
    real_extract = fake_ydl.extract_info

    def extract_info(self, url, download=False):
        clients = _clients(self)
        if not clients or tuple(clients) != allowed["clients"]:
            self.extract_calls.append((url, download))
            raise yt_dlp.utils.DownloadError(BOT_ERROR)
        return real_extract(self, url, download)

    monkeypatch.setattr(fake_ydl, "extract_info", extract_info)
    return allowed


def test_is_bot_check_matches_youtube_refusal():
    assert logic.is_bot_check(BOT_ERROR)
    assert logic.is_bot_check("Sign in to confirm you're not a bot")
    assert not logic.is_bot_check("Video unavailable")
    assert not logic.is_bot_check(None)


def test_bot_check_is_not_retried_by_default(manager, fake_ydl, bot_check):
    info = manager.fetch_info("https://youtu.be/abc")
    assert "not a bot" in info["error"]
    assert len(fake_ydl.instances) == 1


def test_fetch_info_retries_bot_check_with_other_clients(fake_ydl, bot_check):
    manager = DownloadManager(tools=FAKE_TOOLS, bot_check_clients=logic.BOT_CHECK_CLIENTS)
    lines = []
    info = manager.fetch_info("https://youtu.be/abc", log_callback=lines.append)
    assert info["title"] == "clip"
    assert [_clients(i) for i in fake_ydl.instances] == [None, ["tv"]]
    assert any("not a bot" in line for line in lines)


def test_fetch_info_reports_bot_check_when_every_client_is_refused(fake_ydl, bot_check):
    bot_check["clients"] = ("nothing",)
    manager = DownloadManager(tools=FAKE_TOOLS, bot_check_clients=logic.BOT_CHECK_CLIENTS)
    info = manager.fetch_info("https://youtu.be/abc")
    assert "not a bot" in info["error"]
    assert len(fake_ydl.instances) == 1 + len(logic.BOT_CHECK_CLIENTS)


def test_clients_that_passed_are_tried_first_next_time(fake_ydl, bot_check, tmp_path):
    manager = DownloadManager(tools=FAKE_TOOLS, bot_check_clients=logic.BOT_CHECK_CLIENTS)
    manager.fetch_info("https://youtu.be/abc")
    fake_ydl.instances = []
    result = manager.download_video("https://youtu.be/abc", {"save_path": str(tmp_path)})
    assert result.status is ItemStatus.COMPLETED
    assert _clients(fake_ydl.instances[0]) == ["tv"]


def test_download_retries_bot_check(fake_ydl, bot_check, tmp_path):
    manager = DownloadManager(tools=FAKE_TOOLS, bot_check_clients=logic.BOT_CHECK_CLIENTS)
    result = manager.download_video("https://youtu.be/abc", {"save_path": str(tmp_path)})
    assert result.status is ItemStatus.COMPLETED
    assert [_clients(i) for i in fake_ydl.instances[:2]] == [None, ["tv"]]


def test_player_clients_keep_other_extractor_args():
    options = {"extractor_args": {"youtube": {"lang": ["en"]}, "tiktok": {"x": ["1"]}}}
    changed = logic.with_player_clients(options, ("tv",))
    assert changed["extractor_args"] == {"youtube": {"lang": ["en"], "player_client": ["tv"]},
                                         "tiktok": {"x": ["1"]}}
    assert options["extractor_args"]["youtube"] == {"lang": ["en"]}
    assert logic.with_player_clients(options, None) is options


# --- Reusing the analysis ---------------------------------------------------------

def test_download_reuses_analysed_info_without_asking_again(manager, fake_ydl, tmp_path):
    info = manager.fetch_info("https://example.com/v")
    fake_ydl.instances = []
    result = manager.download_video("https://example.com/v", {"save_path": str(tmp_path)}, info=info)
    assert result.status is ItemStatus.COMPLETED
    assert not any(i.extract_calls for i in fake_ydl.instances)


def test_reusable_info_drops_earlier_format_selection():
    info = {"id": "x", "formats": [{"format_id": "a"}], "requested_formats": [{"format_id": "a"}],
            "requested_downloads": [{}], "_filename": "x.mp4"}
    copy_ = logic.reusable_info(info)
    assert copy_ == {"id": "x", "formats": [{"format_id": "a"}]}
    assert "requested_formats" in info  # the cached original is left alone
    copy_["formats"][0]["format_id"] = "b"
    assert info["formats"][0]["format_id"] == "a"


def test_real_yt_dlp_selects_again_from_reused_info():
    """yt-dlp keeps the old merge in 'requested_formats' unless it is dropped."""
    raw = {"id": "x", "title": "t", "extractor": "generic", "extractor_key": "Generic",
           "webpage_url": "http://e/x", "formats": [
               {"format_id": "v", "url": "http://e/v.mp4", "ext": "mp4", "vcodec": "avc1", "acodec": "none"},
               {"format_id": "a", "url": "http://e/a.m4a", "ext": "m4a", "vcodec": "none", "acodec": "mp4a"}]}
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        analysed = ydl.process_ie_result(raw, download=False)
    assert analysed["format_id"] == "v+a"
    with yt_dlp.YoutubeDL({"quiet": True, "format": "ba"}) as ydl:
        again = ydl.process_ie_result(logic.reusable_info(analysed), download=False)
    assert again["format_id"] == "a"
    assert "requested_formats" not in again
