"""Remember the user's choices between runs (ISSUES.md #20, #43).

Stored as JSON in the per-user data folder. Unknown or invalid values fall
back to defaults, and a damaged file never stops the app from starting.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, fields

import formats

_log = logging.getLogger(__name__)

THEMES = ("System", "Dark", "Light")


@dataclass
class Settings:
    download_folder: str = ""
    mode: str = formats.VIDEO_AUDIO
    format: str = "mp4"
    quality: str = "Best"
    theme: str = "System"

    def normalized(self, default_folder):
        """A copy with every value valid for the current version."""
        mode = self.mode if self.mode in formats.MODES else formats.VIDEO_AUDIO
        fmt = self.format if self.format in formats.formats_for_mode(mode) else formats.formats_for_mode(mode)[0]
        quality = self.quality if self.quality in formats.qualities_for_mode(mode) else "Best"
        theme = self.theme if self.theme in THEMES else "System"
        folder = self.download_folder if isinstance(self.download_folder, str) and self.download_folder else \
            default_folder
        return Settings(folder, mode, fmt, quality, theme)


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
    known = {f.name for f in fields(Settings)}
    values = {k: v for k, v in raw.items() if k in known and isinstance(v, str)}
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
