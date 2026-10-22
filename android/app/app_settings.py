"""Settings of the Android app, stored as JSON in the app's private folder.

Unknown keys are dropped and invalid values fall back to the defaults, so a
settings file from an older or newer version never stops the app.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, fields

import formats
import i18n
import urls
import worker

_log = logging.getLogger(__name__)

THEMES = ("system", "light", "dark")
ACCENTS = ("Blue", "Teal", "Green", "Purple", "Pink", "Red", "Orange", "Indigo")
MODES = ("video", "audio")
VIDEO_CONTAINERS = worker.MODE_FORMATS[worker.VIDEO_AUDIO]      # mp4, mkv
AUDIO_FORMATS = worker.MODE_FORMATS[worker.AUDIO_ONLY]          # mp3, m4a, flac, wav
AUDIO_QUALITIES = tuple(worker.AUDIO_QUALITIES)                 # Best, 320 kbps, ...
FRAGMENTS_MIN, FRAGMENTS_MAX = 1, 16
SPEED_LIMITS = (0, 1, 2, 5, 10, 20)   # MB/s; 0 means no limit
UPDATE_CHANNELS = ("stable", "beta")
PLAYLIST_CHOICES_KEPT = 50            # playlists whose selection is remembered


@dataclass
class AppSettings:
    # Appearance
    theme: str = "system"
    dynamic_color: bool = True        # Material You colours from the wallpaper (Android 12+)
    pure_black: bool = False          # AMOLED: black background in the dark theme
    accent: str = "Blue"              # used when dynamic_color is off or unavailable
    language: str = "auto"
    # Downloads
    default_mode: str = "video"
    video_quality: str = "Best"
    video_container: str = "mp4"
    audio_format: str = "mp3"
    audio_quality: str = "Best"
    fragments: int = 4                # parallel fragment downloads (HLS/DASH)
    subtitles: bool = False           # save a video's subtitles as .srt files next to it
    subtitle_langs: str = ""          # "en, tr"; empty: the app's language, then English
    subtitle_embed: bool = False      # put the subtitles into the video instead of next to it
    sponsorblock: bool = False        # cut SponsorBlock segments (sponsors, intros) from YouTube videos
    sponsorblock_categories: str = ",".join(formats.SPONSORBLOCK_CATEGORIES)  # the segments cut
    speed_limit: int = 0              # MB/s, one of SPEED_LIMITS
    proxy: str = ""                   # urls.proxy_url address; empty for a direct connection
    # Behaviour
    auto_paste: bool = True           # take a link from the clipboard when the app opens
    auto_analyze_shared: bool = True  # analyze links shared from other apps at once
    keep_screen_on: bool = True       # while a download runs
    wifi_only: bool = False           # ask before downloading on mobile data; pause until Wi-Fi is back
    save_history: bool = True
    check_updates: bool = True        # look for a new version on GitHub at start-up
    update_channel: str = "stable"    # one of UPDATE_CHANNELS; beta also offers pre-releases
    skipped_version: str = ""         # "Skip this version" in the update dialog
    # Remembered screen state
    show_options: bool = False        # Download tab: the "More options" part is open

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
            "update_channel": UPDATE_CHANNELS,
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
        if values["speed_limit"] not in SPEED_LIMITS:
            values["speed_limit"] = 0
        try:
            values["proxy"] = urls.proxy_url(values["proxy"])
        except ValueError:
            values["proxy"] = ""
        values["sponsorblock_categories"] = ",".join(formats.sponsorblock_categories(values["sponsorblock_categories"]))
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
    requests from throttling the transfer. A speed limit caps the whole
    transfer.
    """
    options = {
        "concurrent_fragment_downloads": settings.fragments,
        "http_chunk_size": 10 * 1024 * 1024,
    }
    if settings.speed_limit:
        options["ratelimit"] = settings.speed_limit * 1024 * 1024
    return options


def load_playlist_choices(path):
    """{playlist link: {"known": [entry links], "chosen": [entry links]}} saved by save_playlist_choice."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_playlist_choice(path, playlist_url, known, chosen):
    """Remember which entries of a playlist the user ticked (the newest PLAYLIST_CHOICES_KEPT playlists)."""
    data = load_playlist_choices(path)
    data.pop(playlist_url, None)
    data[playlist_url] = {"known": list(known), "chosen": list(chosen)}
    for old in list(data)[:-PLAYLIST_CHOICES_KEPT]:
        del data[old]
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(temp, path)
    except OSError as e:
        _log.warning("Cannot save the playlist selection: %s", e)


def remembered_choice(saved, items, downloaded_before=()):
    """The entries of ``items`` to tick, from a remembered selection.

    Entries the user saw last time keep their tick; new entries are
    ticked unless they were downloaded before. Returns None when this
    playlist has no remembered selection.
    """
    if not isinstance(saved, dict):
        return None
    known, chosen = set(saved.get("known") or ()), set(saved.get("chosen") or ())
    before = {id(item) for item in downloaded_before}
    return [item for item in items
            if (item.url in chosen if item.url in known else id(item) not in before)]
