"""Remember the user's choices between runs (ISSUES.md #20, #43).

Stored as JSON in the per-user data folder. Unknown or invalid values fall
back to defaults, and a damaged file never stops the app from starting.
"""

import json
import logging
import os
from dataclasses import MISSING, asdict, dataclass, fields, replace

import formats
import i18n

_log = logging.getLogger(__name__)

THEMES = ("System", "Dark", "Light")
# Accent colour names, as on Android; ui.ACCENTS holds their colours.
ACCENTS = ("Indigo", "Blue", "Teal", "Green", "Purple", "Pink", "Red", "Orange")
# Parallel fragment downloads for segmented (HLS/DASH) streams.
FRAGMENTS_MIN, FRAGMENTS_MAX = 1, 16
# Text size choice -> CustomTkinter widget scaling.
TEXT_SIZES = {"Normal": 1.0, "Large": 1.15, "Larger": 1.3}


@dataclass
class Settings:
    download_folder: str = ""
    mode: str = formats.VIDEO_AUDIO
    format: str = "mp4"
    quality: str = "Best"
    theme: str = "System"
    text_size: str = "Normal"
    open_folder_when_done: bool = False
    show_summary: bool = True
    language: str = i18n.AUTO  # a code from i18n.LANGUAGES, or follow the system
    accent: str = "Indigo"
    fragments: int = 4           # parallel connections for streamed videos
    auto_paste: bool = True      # take a link from the clipboard when the app opens
    keep_awake: bool = True      # keep the PC from sleeping while a download runs
    save_history: bool = True
    check_updates: bool = True   # look for a new version at start
    last_version: str = ""       # version that ran last; "what's new" shows after an update

    def normalized(self, default_folder):
        """A copy with every value valid for the current version."""
        mode = self.mode if self.mode in formats.MODES else formats.VIDEO_AUDIO
        fmt = self.format if self.format in formats.formats_for_mode(mode) else formats.formats_for_mode(mode)[0]
        quality = self.quality if self.quality in formats.qualities_for_mode(mode) else "Best"
        theme = self.theme if self.theme in THEMES else "System"
        folder = self.download_folder if isinstance(self.download_folder, str) and self.download_folder else \
            default_folder
        text_size = self.text_size if self.text_size in TEXT_SIZES else "Normal"
        language = self.language if self.language in i18n.LANGUAGES else i18n.AUTO
        accent = self.accent if self.accent in ACCENTS else "Indigo"
        fragments = min(max(self.fragments, FRAGMENTS_MIN), FRAGMENTS_MAX)
        return replace(self, download_folder=folder, mode=mode, format=fmt, quality=quality, theme=theme,
                       text_size=text_size, language=language, accent=accent, fragments=fragments)


def load(path, default_folder):
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("not a JSON object")
    except FileNotFoundError:
        raw = {}
    except (OSError, ValueError) as e:
        _log.warning("Ignoring unreadable settings %s: %s", path, e)
        raw = {}
    # Keep only known keys whose value has the default's type.
    types = {f.name: type(f.default) for f in fields(Settings) if f.default is not MISSING}
    values = {k: v for k, v in raw.items() if k in types and type(v) is types[k]}
    return Settings(**values).normalized(default_folder)


def save(path, settings):
    """Write atomically so a crash mid-write cannot corrupt the file."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        _log.warning("Could not save settings to %s: %s", path, e)


def download_speed_options(settings):
    """yt-dlp options that make downloads faster (the Android app uses the same).

    Segmented streams (HLS/DASH, used by Instagram, X, many live and news
    sites) download several fragments at once. Plain HTTP files are fetched
    in 10 MB ranges, which keeps servers that slow down long single
    requests from throttling the transfer.
    """
    return {
        "concurrent_fragment_downloads": settings.fragments,
        "http_chunk_size": 10 * 1024 * 1024,
    }
