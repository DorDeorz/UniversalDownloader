"""Output folders and collision-safe file names (ISSUES.md #34-#38, #40, #41).

Policy: an existing file is never overwritten or reused. When any file
with the target name exists (whatever its extension), a numeric suffix is
added: ``Title.mp4``, ``Title (2).mp4``, ...
Playlist items go into a folder named after the playlist and start with
their playlist position, so the order is kept on disk.
"""

import os
import shutil
import sys
import tempfile
import time

from yt_dlp.utils import sanitize_filename

# Keep full paths under the classic Windows MAX_PATH (260) with room for
# yt-dlp's temporary suffixes such as '.f137.mp4.part-Frag12'.
MAX_PATH = 230
MIN_TITLE_BYTES = 40      # what a title keeps when the folder leaves room for it
SHORTEST_TITLE_BYTES = 16  # the least a title is cut to in a long folder
MAX_TITLE_BYTES = 150
# Room the platform folder ("X_Twitter"), the shortest playlist folder, the
# playlist number, the shortest title and yt-dlp's suffixes need after the
# chosen download folder. A longer download folder cannot stay under MAX_PATH.
_AFTER_FOLDER = len("\\X_Twitter\\") + 20 + len("\\001 - ") + SHORTEST_TITLE_BYTES + len(" (99).webm") + 16
LONGEST_FOLDER = MAX_PATH - _AFTER_FOLDER
LOW_DISK_BYTES = 1024 ** 3
# The message check_folder gives for a download folder too long for Windows
# (i18n.MESSAGE_TEMPLATES translates it).
FOLDER_TOO_LONG = ("The folder's path is {length} characters long; Windows allows at most {limit} here. "
                   "Choose a shorter folder")

# Names Windows reserves for devices: "CON.mp4" cannot be created or opened.
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                  *(f"COM{n}" for n in "123456789\u00b9\u00b2\u00b3"),
                  *(f"LPT{n}" for n in "123456789\u00b9\u00b2\u00b3")}

_PLATFORMS = {
    "youtube": "YouTube",
    "youtubetab": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "twitter": "X_Twitter",
    "generic": "Other",
}


def platform_folder(info):
    """Folder name from yt-dlp's extractor, not from URL text (#38)."""
    key = str(info.get("extractor_key") or info.get("ie_key") or "").strip()
    if not key:
        return "Other"
    return _PLATFORMS.get(key.lower(), safe_name(key))


def safe_name(text, fallback="Untitled"):
    """A single path component that is valid on Windows."""
    name = sanitize_filename(str(text or ""), restricted=False).strip().rstrip(". ")
    return avoid_reserved(name) if name else fallback


def is_reserved(name):
    """True for a name Windows keeps for a device: "CON", "nul.txt", "Com1.mp4"."""
    return name.split(".")[0].rstrip(" ").upper() in RESERVED_NAMES


def avoid_reserved(name):
    """``name``, with "_" in front when Windows reserves it (yt-dlp leaves "CON" as it is)."""
    return "_" + name if is_reserved(name) else name


def escape_template(text):
    """Make literal text safe inside a yt-dlp output template."""
    return text.replace("%", "%%")


def output_folder(base, info, playlist_title=None):
    parts = [base, platform_folder(info)]
    if playlist_title:
        # Shorter in a long download folder, so the titles keep some room.
        room = MAX_PATH - len(os.path.join(*parts)) - 1 - len("001 - ") - MIN_TITLE_BYTES - len(" (99).webm") - 16
        limit = min(80, max(20, room))
        parts.append(avoid_reserved(safe_name(playlist_title)[:limit].rstrip(". ")) or "Playlist")
    return os.path.join(*parts)


def output_template(folder, playlist_index=None):
    """yt-dlp template for one item; the title is length-limited in bytes.

    The title gets what the folder leaves of MAX_PATH, between
    SHORTEST_TITLE_BYTES and MAX_TITLE_BYTES. The byte limit also limits the
    characters, as every character takes at least one byte.
    """
    prefix = f"{int(playlist_index):03d} - " if playlist_index else ""
    budget = MAX_PATH - len(folder) - 1 - len(prefix) - len(" (99).webm") - 16
    title_bytes = max(SHORTEST_TITLE_BYTES, min(MAX_TITLE_BYTES, budget))
    return os.path.join(escape_template(folder), f"{prefix}%(title).{title_bytes}B.%(ext)s")


# folder -> (its modification time, the case-folded names in it). A folder's
# time changes whenever a file is added, renamed or removed in it, so a
# playlist does not list the same folder again for every item. Some drives
# (FAT32 sticks) keep the time in 2-second steps, so a folder changed in the
# last few seconds is always listed again.
_listings = {}
FRESH_SECONDS = 3


def _existing_names(folder):
    """The case-folded names in ``folder`` (a set; empty when it cannot be read)."""
    try:
        stamp = os.stat(folder).st_mtime_ns
        cached = _listings.get(folder)
        settled = time.time() - stamp / 1e9 > FRESH_SECONDS
        if cached is not None and cached[0] == stamp and settled:
            return cached[1]
        with os.scandir(folder) as found:
            names = {entry.name.casefold() for entry in found}
    except OSError:
        _listings.pop(folder, None)
        return set()
    if len(_listings) > 64:
        _listings.clear()
    _listings[folder] = (stamp, names)
    return names


def unique_base(prepared_path, final_ext=None):
    """Path without extension that no existing file in the folder starts with.

    Any extension counts, not only the final one: yt-dlp first downloads to
    the source extension (and converts afterwards), and it would reuse an
    existing ``Title.mp4`` as "already downloaded" when making ``Title.mp3``.
    Case is ignored, as Windows does, and a name Windows reserves ("CON")
    gets a "_" in front.
    """
    folder, name = os.path.split(os.path.splitext(prepared_path)[0])
    name = avoid_reserved(name)
    # Windows file names ignore case: "title.mp4" is taken for "Title".
    existing = _existing_names(folder)

    def taken(stem):
        prefix = stem.casefold() + "."
        return any(n.startswith(prefix) for n in existing)

    stem, n = name, 2
    while taken(stem):
        stem = f"{name} ({n})"
        n += 1
    return os.path.join(folder, stem)


def check_folder(folder, windows=None):
    """Create ``folder`` and prove it is writable.

    Returns ``(error, warning)``: an error text if files cannot be written
    there (or, on Windows, its path leaves no room for file names under
    MAX_PATH), and a warning text when free space is low.
    """
    windows = sys.platform == "win32" if windows is None else windows
    length = len(os.path.abspath(folder)) if windows else 0
    if length > LONGEST_FOLDER:
        return FOLDER_TOO_LONG.format(length=length, limit=LONGEST_FOLDER), None
    try:
        os.makedirs(folder, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".uvd-write-test-", delete=True):
            pass
    except OSError as e:
        return f"Cannot write to {folder}: {e.strerror or e}", None
    free = low_space_mb(folder)
    if free is not None:
        return None, f"Only {free} MB free in {folder}"
    return None, None


def low_space_mb(folder):
    """Free megabytes in ``folder`` when below LOW_DISK_BYTES, else None."""
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return None
    return round(free / 1024 ** 2) if free < LOW_DISK_BYTES else None
