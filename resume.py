"""Continue a download that failed half way, from its ``.part`` file.

A download that fails after data arrived keeps its partial files and a
marker next to them, ``<name>.orbida-resume``. The marker records what was
being downloaded: the site's id of the video, the formats picked and the
file type. The next download of the same video with the same choices finds
the marker and uses the same name, so yt-dlp continues the ``.part`` file
(an HTTP range request) or the stream's fragments where they stopped.

A partial file is only ever continued by the download it was made for: a
different video, another format or another quality has another identity
and gets a new name (filenames.unique_base). Markers older than
``KEEP_DAYS`` are removed with their partial files at the next download
into the folder, so failed downloads do not fill the disk for good.
"""

import json
import logging
import os
import time

_log = logging.getLogger(__name__)

SUFFIX = ".orbida-resume"
KEEP_DAYS = 7


def identity(info, ext, mode):
    """What a partial file is a part of: one video, its formats and the file type made from them.

    None when the site gives no id for the video; such a download is never continued.
    """
    video_id = info.get("id")
    if not video_id:
        return None
    return {
        "video": f"{info.get('extractor_key') or info.get('extractor') or ''}:{video_id}",
        "formats": str(info.get("format_id") or ""),
        "ext": ext,
        "mode": mode,
    }


def marker_path(base):
    return base + SUFFIX


def _files_of(base):
    """Names in the folder that belong to ``base`` (start with "base."), case ignored."""
    folder, prefix = os.path.dirname(base) or ".", os.path.basename(base).casefold() + "."
    try:
        return [name for name in os.listdir(folder) if name.casefold().startswith(prefix)]
    except OSError:
        return []


def has_partial_data(base):
    """True when a file of ``base`` other than its marker holds data."""
    folder = os.path.dirname(base) or "."
    for name in _files_of(base):
        if name.endswith(SUFFIX):
            continue
        try:
            if os.path.getsize(os.path.join(folder, name)) > 0:
                return True
        except OSError:
            pass
    return False


def save(base, ident):
    """Write the marker that lets the download of ``base`` be continued."""
    try:
        with open(marker_path(base), "w", encoding="utf-8") as f:
            json.dump(ident, f)
        return True
    except OSError as e:
        _log.warning("Could not write %s: %s", marker_path(base), e)
        return False


def forget(base):
    """Remove the marker of ``base`` (its download finished or was thrown away)."""
    try:
        os.remove(marker_path(base))
    except OSError:
        pass


def _discard(base, ext):
    """Remove the marker and the partial files of ``base``: its .part and
    fragment files, format parts (".f137.mp4") and thumbnail. A finished
    "base.<ext>" is kept."""
    folder = os.path.dirname(base) or "."
    finished = f"{os.path.basename(base)}.{ext}".casefold()
    for name in _files_of(base):
        if name.casefold() != finished:
            try:
                os.remove(os.path.join(folder, name))
            except OSError as e:
                _log.warning("Could not remove %s: %s", name, e)


def find(folder, ident, now=None):
    """The base name of an unfinished download of ``ident`` in ``folder``, or None.

    Old markers are cleared on the way, with their partial files, as are
    markers whose partial files are gone.
    """
    now = time.time() if now is None else now
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    found = None
    for name in names:
        if not name.endswith(SUFFIX):
            continue
        path = os.path.join(folder, name)
        base = path[:-len(SUFFIX)]
        try:
            age = now - os.path.getmtime(path)
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            continue
        if age > KEEP_DAYS * 86400:
            _log.info("Removing the partial download %s (older than %d days)", base, KEEP_DAYS)
            _discard(base, saved.get("ext") if isinstance(saved, dict) else None)
            continue
        if not has_partial_data(base):
            forget(base)
            continue
        if ident is not None and found is None and saved == ident:
            found = base
    return found
