"""Output folders and collision-safe file names (ISSUES.md #34-#38, #40, #41).

Policy: an existing file is never overwritten or reused. When any file
with the target name exists (whatever its extension), a numeric suffix is
added: ``Title.mp4``, ``Title (2).mp4``, ...
Playlist items go into a folder named after the playlist and start with
their playlist position, so the order is kept on disk.
"""

import os
import shutil
import tempfile

from yt_dlp.utils import sanitize_filename

# Keep full paths under the classic Windows MAX_PATH (260) with room for
# yt-dlp's temporary suffixes such as '.f137.mp4.part-Frag12'.
MAX_PATH = 230
MIN_TITLE_BYTES = 40
MAX_TITLE_BYTES = 150
LOW_DISK_BYTES = 1024 ** 3

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
    return name or fallback


def escape_template(text):
    """Make literal text safe inside a yt-dlp output template."""
    return text.replace("%", "%%")


def output_folder(base, info, playlist_title=None):
    parts = [base, platform_folder(info)]
    if playlist_title:
        parts.append(safe_name(playlist_title)[:80].rstrip(". "))
    return os.path.join(*parts)


def output_template(folder, playlist_index=None):
    """yt-dlp template for one item; the title is length-limited in bytes."""
    budget = MAX_PATH - len(folder) - len(" (99).webm") - 16
    title_bytes = max(MIN_TITLE_BYTES, min(MAX_TITLE_BYTES, budget))
    prefix = f"{int(playlist_index):03d} - " if playlist_index else ""
    return os.path.join(escape_template(folder), f"{prefix}%(title).{title_bytes}B.%(ext)s")


def _existing_names(folder):
    try:
        return set(os.listdir(folder))
    except OSError:
        return set()


def unique_base(prepared_path, final_ext=None):
    """Path without extension that no existing file in the folder starts with.

    Any extension counts, not only the final one: yt-dlp first downloads to
    the source extension (and converts afterwards), and it would reuse an
    existing ``Title.mp4`` as "already downloaded" when making ``Title.mp3``.
    """
    folder, name = os.path.split(os.path.splitext(prepared_path)[0])
    existing = _existing_names(folder)

    def taken(stem):
        prefix = stem + "."
        return any(n.startswith(prefix) for n in existing)

    stem, n = name, 2
    while taken(stem):
        stem = f"{name} ({n})"
        n += 1
    return os.path.join(folder, stem)


def check_folder(folder):
    """Create ``folder`` and prove it is writable.

    Returns ``(error, warning)``: an error text if files cannot be written
    there, and a warning text when free space is low.
    """
    try:
        os.makedirs(folder, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".uvd-write-test-", delete=True):
            pass
    except OSError as e:
        return f"Cannot write to {folder}: {e.strerror or e}", None
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return None, None
    if free < LOW_DISK_BYTES:
        return None, f"Only {free / 1024 ** 2:.0f} MB free in {folder}"
    return None, None
