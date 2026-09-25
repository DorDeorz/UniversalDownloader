"""Download modes and the yt-dlp options each one needs.

Each mode has its own contract (ISSUES.md #6-#12, #53, #54, #90):

- ``Video + Audio``: best video and audio at or below the chosen height,
  merged into the chosen container.
- ``Video Only``: a video stream at or below the chosen height, with any
  audio track removed.
- ``Audio Only``: the audio track converted to a real audio codec at the
  chosen bitrate.

The height limit is a hard cap: there is no fallback to an unrestricted
``best`` format, so choosing 720p never produces a 1080p file.
"""

from dataclasses import dataclass

VIDEO_AUDIO = "Video + Audio"
VIDEO_ONLY = "Video Only"
AUDIO_ONLY = "Audio Only"
MODES = (VIDEO_AUDIO, VIDEO_ONLY, AUDIO_ONLY)

# Containers offered for video. Each entry is the format sort: resolution
# first, then the codecs that fit the container without re-encoding.
VIDEO_CONTAINERS = {
    "mp4": ["res", "vcodec:h264", "acodec:aac"],
    "mkv": [],
    "webm": ["res", "vcodec:vp9", "acodec:opus"],
}

# Audio formats: user choice -> (yt-dlp preferredcodec, file extension).
AUDIO_FORMATS = {
    "mp3": ("mp3", "mp3"),
    "m4a": ("m4a", "m4a"),
    "opus": ("opus", "opus"),
    "flac": ("flac", "flac"),
    "wav": ("wav", "wav"),
}
LOSSLESS_AUDIO = {"flac", "wav"}

VIDEO_QUALITIES = {
    "Best": None,
    "2160p (4K)": 2160,
    "1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}
# Older settings used "4K".
_QUALITY_ALIASES = {"4K": "2160p (4K)"}

# Audio quality -> yt-dlp preferredquality ('0' = best VBR, else kbps).
AUDIO_QUALITIES = {
    "Best": "0",
    "320 kbps": "320",
    "192 kbps": "192",
    "128 kbps": "128",
}

# Containers yt-dlp can embed a thumbnail into.
_THUMBNAIL_EXTS = {"mp3", "mkv", "m4a", "mp4", "opus", "flac"}


class FormatError(ValueError):
    """The mode, format or quality combination is not supported."""


def formats_for_mode(mode):
    """Format choices for the UI, default first."""
    if mode == AUDIO_ONLY:
        return list(AUDIO_FORMATS)
    return list(VIDEO_CONTAINERS)


def qualities_for_mode(mode):
    """Quality choices for the UI, default first."""
    if mode == AUDIO_ONLY:
        return list(AUDIO_QUALITIES)
    return list(VIDEO_QUALITIES)


@dataclass(frozen=True)
class FormatPlan:
    """yt-dlp options for one mode plus what the result should look like."""

    mode: str
    ext: str
    options: dict
    needs_audio: bool
    strip_audio: bool


def build_format_plan(mode, fmt, quality):
    """Validate the choice and return a :class:`FormatPlan`.

    Raises :class:`FormatError` for combinations that cannot work, such as a
    video container in Audio Only mode.
    """
    if mode not in MODES:
        raise FormatError(f"Unknown mode '{mode}'")

    if mode == AUDIO_ONLY:
        if fmt not in AUDIO_FORMATS:
            raise FormatError(f"'{fmt}' is not an audio format; choose one of {', '.join(AUDIO_FORMATS)}")
        quality = quality if quality in AUDIO_QUALITIES else "Best"
        codec, ext = AUDIO_FORMATS[fmt]
        extract = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        if fmt not in LOSSLESS_AUDIO:
            extract["preferredquality"] = AUDIO_QUALITIES[quality]
        postprocessors = [extract, {"key": "FFmpegMetadata"}]
        if ext in _THUMBNAIL_EXTS:
            postprocessors.append({"key": "EmbedThumbnail"})
        options = {
            # An audio-only stream, else the audio of a combined stream.
            "format": "bestaudio/best[acodec!=?none]",
            "postprocessors": postprocessors,
            "writethumbnail": ext in _THUMBNAIL_EXTS,
        }
        return FormatPlan(mode, ext, options, needs_audio=True, strip_audio=False)

    if fmt not in VIDEO_CONTAINERS:
        raise FormatError(f"'{fmt}' is not a video container; choose one of {', '.join(VIDEO_CONTAINERS)}")
    quality = _QUALITY_ALIASES.get(quality, quality)
    if quality not in VIDEO_QUALITIES:
        raise FormatError(f"Unknown quality '{quality}'")
    height = VIDEO_QUALITIES[quality]
    cap = f"[height<={height}]" if height else ""
    # Last resort for sites that do not report a height at all; formats
    # known to be taller than the cap are still excluded.
    unknown = f"/b[height<=?{height}]" if height else ""

    if mode == VIDEO_AUDIO:
        selector = f"bv*{cap}+ba/b{cap}{unknown}"
    else:
        # A pure video stream; sites that only offer muxed files fall back
        # to one, and the audio track is stripped afterwards.
        selector = f"bv{cap}/b{cap}{unknown}"

    options = {
        "format": selector,
        "format_sort": list(VIDEO_CONTAINERS[fmt]),
        "merge_output_format": fmt,
        "postprocessors": _video_postprocessors(fmt, "FFmpegVideoRemuxer"),
        "writethumbnail": fmt in _THUMBNAIL_EXTS,
    }
    return FormatPlan(mode, fmt, options, needs_audio=mode == VIDEO_AUDIO, strip_audio=mode == VIDEO_ONLY)


# Codecs each container holds without re-encoding (prefix match).
_CONTAINER_CODECS = {
    "mp4": (("avc", "h264", "hev", "hvc", "h265", "av01", "vp09", "vp9"), ("mp4a", "aac", "mp3", "opus", "flac", "ac-3", "ec-3")),
    "webm": (("vp8", "vp09", "vp9", "av01"), ("opus", "vorbis")),
}


def _video_postprocessors(fmt, container_pp):
    postprocessors = [
        # Guarantees the container even when a single pre-muxed file was
        # picked (merge_output_format only applies to merges).
        {"key": container_pp, "preferedformat": fmt},
        {"key": "FFmpegMetadata"},
    ]
    if fmt in _THUMBNAIL_EXTS:
        postprocessors.append({"key": "EmbedThumbnail"})
    return postprocessors


def fits_container(fmt, info):
    """False when a selected codec is known not to fit ``fmt`` without re-encoding."""
    if fmt not in _CONTAINER_CODECS:
        return True
    video_ok, audio_ok = _CONTAINER_CODECS[fmt]
    for f in selected_formats(info):
        vcodec, acodec = f.get("vcodec"), f.get("acodec")
        if not vcodec and not acodec:
            # Codecs unknown (e.g. a direct file link): only trust a file
            # that already has the target extension.
            if f.get("ext") != fmt:
                return False
            continue
        if vcodec and vcodec != "none" and not str(vcodec).lower().startswith(video_ok):
            return False
        if acodec and acodec != "none" and not str(acodec).lower().startswith(audio_ok):
            return False
    return True


def postprocessors_for(plan, info):
    """The plan's postprocessors, re-encoding instead of remuxing when needed."""
    if plan.mode == AUDIO_ONLY or fits_container(plan.ext, info):
        return list(plan.options["postprocessors"])
    return _video_postprocessors(plan.ext, "FFmpegVideoConvertor")


def height_unknown(info):
    """True when no selected video stream reports a height."""
    videos = [f for f in selected_formats(info) if f.get("vcodec") != "none"]
    return bool(videos) and not any(f.get("height") for f in videos)


def selected_formats(info):
    """Formats yt-dlp picked for ``info`` (one, or the merged pair)."""
    return info.get("requested_formats") or [info]


def has_audio(info):
    """False only when yt-dlp knows every selected format has no audio."""
    return any(f.get("acodec") != "none" for f in selected_formats(info))


def describe_selection(info):
    """Short text of what was picked, e.g. '1920x1080 avc1 + mp4a'."""
    parts = []
    for f in selected_formats(info):
        bits = []
        if f.get("width") and f.get("height"):
            bits.append(f"{f['width']}x{f['height']}")
        elif f.get("height"):
            bits.append(f"{f['height']}p")
        if f.get("vcodec") not in (None, "none"):
            bits.append(str(f["vcodec"]).split(".")[0])
        if f.get("acodec") not in (None, "none"):
            bits.append(str(f["acodec"]).split(".")[0])
        if bits:
            parts.append(" ".join(bits))
    return " + ".join(parts) or "unknown format"
