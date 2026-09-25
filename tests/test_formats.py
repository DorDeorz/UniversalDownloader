"""Per-mode format contracts (ISSUES.md #6-#12, #53, #54, #90).

The selection tests run the real yt-dlp format selector on a synthetic
format list, so they check what would actually be downloaded.
"""

import pytest
import yt_dlp

import formats
from formats import AUDIO_ONLY, VIDEO_AUDIO, VIDEO_ONLY, FormatError, build_format_plan

SELECTION_ERRORS = (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError)

YOUTUBE_LIKE = [
    {"format_id": "18", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "height": 360, "width": 640},
    {"format_id": "136", "ext": "mp4", "vcodec": "avc1.4d401f", "acodec": "none", "height": 720, "width": 1280},
    {"format_id": "137", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "width": 1920},
    {"format_id": "248", "ext": "webm", "vcodec": "vp9", "acodec": "none", "height": 1080, "width": 1920},
    {"format_id": "313", "ext": "webm", "vcodec": "vp9", "acodec": "none", "height": 2160, "width": 3840},
    {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 129},
    {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "abr": 160},
]


def select(mode, fmt, quality, available=YOUTUBE_LIKE):
    plan = build_format_plan(mode, fmt, quality)
    opts = {k: plan.options[k] for k in ("format", "format_sort", "merge_output_format") if k in plan.options}
    opts["quiet"] = True
    fmts = [dict(f, url=f"http://example.invalid/{f['format_id']}") for f in available]
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.process_ie_result(
            {"id": "x", "title": "t", "formats": fmts, "extractor": "t", "extractor_key": "T",
             "webpage_url": "http://example.invalid"},
            download=False)
    return info


@pytest.mark.parametrize("mode, fmt, quality, expected", [
    (VIDEO_AUDIO, "mp4", "Best", "313+140"),
    (VIDEO_AUDIO, "mp4", "1080p", "137+140"),
    (VIDEO_AUDIO, "mp4", "720p", "136+140"),
    (VIDEO_AUDIO, "mp4", "360p", "18"),
    (VIDEO_AUDIO, "webm", "1080p", "248+251"),
    (VIDEO_AUDIO, "mkv", "2160p (4K)", "313+251"),
    (VIDEO_ONLY, "mp4", "1080p", "137"),
    (VIDEO_ONLY, "webm", "Best", "313"),
    (AUDIO_ONLY, "mp3", "Best", "251"),
    (AUDIO_ONLY, "m4a", "128 kbps", "251"),
])
def test_real_selection(mode, fmt, quality, expected):
    assert select(mode, fmt, quality)["format_id"] == expected


@pytest.mark.parametrize("quality, limit", [("720p", 720), ("1080p", 1080), ("360p", 360)])
def test_quality_cap_is_never_exceeded(quality, limit):
    info = select(VIDEO_AUDIO, "mp4", quality)
    assert max(f.get("height") or 0 for f in formats.selected_formats(info)) <= limit


def test_cap_fails_instead_of_falling_back_to_bigger_format():
    only_1080 = [f for f in YOUTUBE_LIKE if f["format_id"] in ("137", "140")]
    with pytest.raises(SELECTION_ERRORS, match="Requested format is not available"):
        select(VIDEO_AUDIO, "mp4", "720p", only_1080)


def test_video_only_prefers_pure_video_streams():
    for quality in ("Best", "1080p", "720p"):
        info = select(VIDEO_ONLY, "mp4", quality)
        assert not formats.has_audio(info), quality


def test_video_only_falls_back_to_muxed_file_and_strips_audio():
    info = select(VIDEO_ONLY, "mp4", "480p")
    assert info["format_id"] == "18"
    assert build_format_plan(VIDEO_ONLY, "mp4", "480p").strip_audio


def test_audio_only_without_audio_track_fails():
    video_only = [f for f in YOUTUBE_LIKE if f["acodec"] == "none"]
    with pytest.raises(SELECTION_ERRORS):
        select(AUDIO_ONLY, "mp3", "Best", video_only)


def test_audio_plan_uses_real_codec_and_bitrate():
    plan = build_format_plan(AUDIO_ONLY, "mp3", "192 kbps")
    extract = plan.options["postprocessors"][0]
    assert extract == {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
    assert plan.ext == "mp3"


def test_lossless_audio_has_no_bitrate():
    plan = build_format_plan(AUDIO_ONLY, "flac", "320 kbps")
    assert "preferredquality" not in plan.options["postprocessors"][0]


def test_m4a_is_named_m4a():
    assert build_format_plan(AUDIO_ONLY, "m4a", "Best").ext == "m4a"


def test_wav_does_not_try_to_embed_thumbnail():
    plan = build_format_plan(AUDIO_ONLY, "wav", "Best")
    assert "EmbedThumbnail" not in [pp["key"] for pp in plan.options["postprocessors"]]
    assert plan.options["writethumbnail"] is False


@pytest.mark.parametrize("mode, fmt", [
    (AUDIO_ONLY, "mp4"), (AUDIO_ONLY, "mkv"), (AUDIO_ONLY, "avi"),
    (VIDEO_AUDIO, "mp3"), (VIDEO_ONLY, "wav"), (VIDEO_AUDIO, "avi"),
])
def test_invalid_format_for_mode_is_rejected(mode, fmt):
    with pytest.raises(FormatError):
        build_format_plan(mode, fmt, "Best")


def test_unknown_mode_is_rejected():
    with pytest.raises(FormatError):
        build_format_plan("Everything", "mp4", "Best")


def test_old_4k_label_still_works():
    assert build_format_plan(VIDEO_AUDIO, "mp4", "4K").options["format"].startswith("bv*[height<=2160]")


def test_video_plan_guarantees_container():
    plan = build_format_plan(VIDEO_AUDIO, "mkv", "Best")
    assert plan.options["merge_output_format"] == "mkv"
    assert {"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"} in plan.options["postprocessors"]


def test_ui_choices_match_mode():
    assert formats.formats_for_mode(AUDIO_ONLY) == ["mp3", "m4a", "opus", "flac", "wav"]
    assert formats.formats_for_mode(VIDEO_ONLY)[0] == "mp4"
    assert "320 kbps" in formats.qualities_for_mode(AUDIO_ONLY)
    assert "1080p" in formats.qualities_for_mode(VIDEO_AUDIO)
    for mode in formats.MODES:
        for fmt in formats.formats_for_mode(mode):
            for quality in formats.qualities_for_mode(mode):
                build_format_plan(mode, fmt, quality)


@pytest.mark.parametrize("fmt, codecs, fits", [
    ("mp4", ("avc1.64", "mp4a.40.2"), True),
    ("mp4", ("vp9", "opus"), True),
    ("webm", ("vp9", "opus"), True),
    ("webm", ("avc1.64", "mp4a.40.2"), False),
    ("webm", ("vp9", "mp4a.40.2"), False),
    ("mkv", ("avc1", "anything"), True),
])
def test_fits_container(fmt, codecs, fits):
    info = {"vcodec": codecs[0], "acodec": codecs[1]}
    assert formats.fits_container(fmt, info) is fits


def test_unknown_codecs_trust_matching_extension_only():
    assert formats.fits_container("mp4", {"ext": "mp4"})
    assert not formats.fits_container("webm", {"ext": "mp4"})


def test_incompatible_selection_is_re_encoded():
    plan = build_format_plan(VIDEO_AUDIO, "webm", "Best")
    pps = formats.postprocessors_for(plan, {"requested_formats": [{"vcodec": "avc1", "acodec": "none"},
                                                                  {"vcodec": "none", "acodec": "mp4a"}]})
    assert pps[0] == {"key": "FFmpegVideoConvertor", "preferedformat": "webm"}


def test_has_audio_treats_unknown_as_possible_audio():
    assert formats.has_audio({"acodec": None})
    assert not formats.has_audio({"acodec": "none"})


def test_describe_selection():
    info = {"requested_formats": [YOUTUBE_LIKE[2], YOUTUBE_LIKE[5]]}
    assert formats.describe_selection(info) == "1920x1080 avc1 + mp4a"
    assert formats.height_unknown({"vcodec": None})
    assert not formats.height_unknown({"vcodec": "avc1", "height": 720})
