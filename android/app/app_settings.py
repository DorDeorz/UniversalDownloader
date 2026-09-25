"""Settings of the Android app, stored as JSON in the app's private folder.

Unknown keys are dropped and invalid values fall back to the defaults, so a
settings file from an older or newer version never stops the app.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, fields

import i18n
import worker

_log = logging.getLogger(__name__)

THEMES = ("system", "light", "dark")
ACCENTS = ("Blue", "Teal", "Green", "Purple", "Pink", "Red", "Orange", "Indigo")
MODES = ("video", "audio")
VIDEO_CONTAINERS = worker.MODE_FORMATS[worker.VIDEO_AUDIO]      # mp4, mkv
AUDIO_FORMATS = worker.MODE_FORMATS[worker.AUDIO_ONLY]          # mp3, m4a, flac, wav
AUDIO_QUALITIES = tuple(worker.AUDIO_QUALITIES)                 # Best, 320 kbps, ...
FRAGMENTS_MIN, FRAGMENTS_MAX = 1, 16


@dataclass
class AppSettings:
    # Appearance
    theme: str = "system"
    dynamic_color: bool = True        # Material You colours from the wallpaper (Android 12+)
    accent: str = "Blue"              # used when dynamic_color is off or unavailable
    language: str = "auto"
    # Downloads
    default_mode: str = "video"
    video_quality: str = "Best"
    video_container: str = "mp4"
    audio_format: str = "mp3"
    audio_quality: str = "Best"
    fragments: int = 4                # parallel fragment downloads (HLS/DASH)
    # Behaviour
    auto_paste: bool = True           # take a link from the clipboard when the app opens
    auto_analyze_shared: bool = True  # analyze links shared from other apps at once
    keep_screen_on: bool = True       # while a download runs
    save_history: bool = True

    def normalized(self):
        """A copy with every invalid value replaced by its default."""
        default = AppSettings()
        allowed = {
            "theme": THEMES,
            "accent": ACCENTS,
            "language": (i18n.AUTO, *i18n.LANGUAGES),
            "default_mode": MODES,
            "video_quality": tuple(worker.VIDEO_QUALITIES),
            "video_container": VIDEO_CONTAINERS,
            "audio_format": AUDIO_FORMATS,
            "audio_quality": AUDIO_QUALITIES,
        }
        values = {}
        for f in fields(self):
            value = getattr(self, f.name)
            fallback = getattr(default, f.name)
            if isinstance(fallback, bool):
                ok = isinstance(value, bool)
            elif isinstance(fallback, int):
                ok = isinstance(value, int) and not isinstance(value, bool)
            else:
                ok = isinstance(value, str) and (f.name not in allowed or value in allowed[f.name])
            values[f.name] = value if ok else fallback
        values["fragments"] = min(max(values["fragments"], FRAGMENTS_MIN), FRAGMENTS_MAX)
        return AppSettings(**values)


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return AppSettings()
    except (OSError, ValueError) as e:
        _log.warning("Cannot read settings %s: %s", path, e)
        return AppSettings()
    if not isinstance(data, dict):
        return AppSettings()
    known = {f.name for f in fields(AppSettings)}
    return AppSettings(**{k: v for k, v in data.items() if k in known}).normalized()


def save(path, settings):
    """Write atomically, so a crash never leaves half a file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(asdict(settings.normalized()), f, indent=2)
    os.replace(temp, path)


def download_speed_options(settings):
    """yt-dlp options that make downloads faster.

    Segmented streams (HLS/DASH, used by Instagram, X, many live and news
    sites) download several fragments at once. Plain HTTP files are fetched
    in 10 MB ranges, which keeps servers that slow down long single
    requests from throttling the transfer.
    """
    return {
        "concurrent_fragment_downloads": settings.fragments,
        "http_chunk_size": 10 * 1024 * 1024,
    }
