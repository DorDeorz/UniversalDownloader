"""yt-dlp updates without a new Orbida release.

Sites change often, and a broken site waits for a yt-dlp release, not for
an Orbida one. Settings can download yt-dlp's latest release into the
user's data folder; from the next start that copy is imported instead of
the bundled one.

What is downloaded is yt-dlp's own "zipimport" build (the release asset
named ``yt-dlp``, which also holds yt-dlp-ejs). It is checked against the
release's SHA2-256SUMS and must contain ``yt_dlp/version.py``. At start,
:func:`activate` puts it in front of the bundled packages, but only when
it is newer than the bundled yt-dlp: an Orbida update with a newer yt-dlp
replaces an older download (which is then deleted).

This module must not import yt_dlp at module level: :func:`activate`
has to run before anything imports it.
"""

import hashlib
import importlib.abc
import logging
import os
import re
import sys
import zipfile
import zipimport

_log = logging.getLogger(__name__)

# The yt-dlp in requirements.txt and android/buildozer.spec (tests check this).
BUNDLED_VERSION = "2026.08.19"
RELEASES = "https://github.com/yt-dlp/yt-dlp/releases"
LATEST_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
DOWNLOAD = RELEASES + "/download/{version}/{name}"
ASSET = "yt-dlp"
SUMS = "SHA2-256SUMS"
FILE_NAME = "yt-dlp.zip"
PACKAGES = ("yt_dlp", "yt_dlp_ejs")
MAX_BYTES = 64 * 1024 * 1024


class UpdateError(Exception):
    """yt-dlp could not be checked or downloaded; the message says why."""


def parse_version(text):
    """(2026, 8, 19) from '2026.08.19' (or '2026.8.19', 'tag/2026.08.19.123'); None if not a version."""
    match = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.(\d+))?", str(text or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def zip_version(path):
    """The yt-dlp version in the zip at ``path``, or None if it is not a usable yt-dlp build."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "yt_dlp/__init__.py" not in names or "yt_dlp/version.py" not in names:
                return None
            source = archive.read("yt_dlp/version.py").decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", source, re.M)
    return match.group(1) if match and parse_version(match.group(1)) else None


class _ZipFinder(importlib.abc.MetaPathFinder):
    """Imports yt_dlp (and yt_dlp_ejs) from the downloaded zip.

    It sits first in sys.meta_path, so it wins over the bundled copy, also
    in the PyInstaller build whose own importer would otherwise answer.
    """

    def __init__(self, path, packages):
        self.path = path
        self.packages = packages

    def find_spec(self, fullname, path=None, target=None):
        parts = fullname.split(".")
        if parts[0] not in self.packages:
            return None
        try:
            # zipimporter finds the last name part inside the folder it is given.
            return zipimport.zipimporter(os.path.join(self.path, *parts[:-1])).find_spec(fullname)
        except (zipimport.ZipImportError, OSError):
            return None


_active = None  # (finder, version) while the downloaded yt-dlp is in use


def zip_path(folder):
    return os.path.join(folder, FILE_NAME)


def activate(folder, bundled=BUNDLED_VERSION):
    """Use the yt-dlp downloaded into ``folder`` when it is newer than ``bundled``.

    Call before anything imports yt_dlp. Returns the version now in use
    from the download, or None for the bundled one. A download that is not
    newer (Orbida was updated since) or not usable is deleted.
    """
    global _active
    if not folder or "yt_dlp" in sys.modules:
        return None
    path = zip_path(folder)
    if not os.path.isfile(path):
        return None
    version = zip_version(path)
    if version is None or parse_version(version) <= parse_version(bundled):
        _log.info("Removing the downloaded yt-dlp %s (bundled: %s)", version, bundled)
        _remove(path)
        return None
    with zipfile.ZipFile(path) as archive:
        packages = tuple(p for p in PACKAGES if f"{p}/__init__.py" in archive.namelist())
    finder = _ZipFinder(path, packages)
    sys.meta_path.insert(0, finder)
    _active = (finder, version)
    _log.info("Using the downloaded yt-dlp %s from %s", version, path)
    return version


def deactivate(folder=None, remove=True):
    """Stop using the downloaded yt-dlp (it failed to import); optionally delete it."""
    global _active
    if _active is not None:
        finder, _version = _active
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        for name in list(sys.modules):
            if name.split(".")[0] in PACKAGES:
                del sys.modules[name]
        _active = None
    if remove and folder:
        _remove(zip_path(folder))


def active_version():
    """The downloaded yt-dlp version in use, or None when the bundled one is."""
    return _active[1] if _active else None


def running_version():
    """The version of the yt-dlp this process imported."""
    from yt_dlp.version import __version__
    return __version__


def latest_version(opener):
    """The version of yt-dlp's latest stable release (GitHub's API).

    ``opener(url)`` returns a response: a context manager with ``read``.
    """
    import json
    try:
        with opener(LATEST_API) as response:
            tag = json.loads(response.read(1024 * 1024).decode("utf-8")).get("tag_name")
    except Exception as e:
        raise UpdateError(f"Could not check yt-dlp's releases: {e}") from e
    if parse_version(tag) is None:
        raise UpdateError(f"Unexpected tag for yt-dlp's latest release: {tag!r}")
    return tag


def is_newer(candidate, current):
    return (parse_version(candidate) or ()) > (parse_version(current) or ())


def download(version, folder, opener, progress=None, cancelled=None):
    """Download yt-dlp ``version`` into ``folder`` and check it; returns its path.

    The file only gets its final name once its SHA-256 matches the
    release's SHA2-256SUMS and it holds that very version. It is used from
    the next start.
    """
    try:
        with opener(DOWNLOAD.format(version=version, name=SUMS)) as response:
            sums = response.read(1024 * 1024).decode("utf-8", "replace")
    except Exception as e:
        raise UpdateError(f"Could not read {SUMS}: {e}") from e
    expected = None
    for line in sums.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == ASSET and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            expected = parts[0].lower()
    if not expected:
        raise UpdateError(f"{SUMS} does not list {ASSET}")
    os.makedirs(folder, exist_ok=True)
    path = zip_path(folder)
    partial = path + ".part"
    digest = hashlib.sha256()
    done = 0
    try:
        with opener(DOWNLOAD.format(version=version, name=ASSET)) as response, open(partial, "wb") as out:
            headers = getattr(response, "headers", None)
            total = int(headers.get("Content-Length") or 0) if headers else 0
            while True:
                if cancelled and cancelled():
                    raise UpdateError("Cancelled")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_BYTES:
                    raise UpdateError(f"{ASSET} is larger than expected")
                out.write(chunk)
                digest.update(chunk)
                if progress:
                    progress(done, total)
        if digest.hexdigest() != expected:
            raise UpdateError(f"{ASSET} does not match its checksum; it was not installed")
        found = zip_version(partial)
        if found is None or parse_version(found) != parse_version(version):
            raise UpdateError(f"{ASSET} is not yt-dlp {version}")
        os.replace(partial, path)
    except UpdateError:
        _remove(partial)
        raise
    except Exception as e:
        _remove(partial)
        raise UpdateError(f"Could not download yt-dlp: {e}") from e
    _log.info("Downloaded yt-dlp %s to %s", version, path)
    return path


def update(folder, opener, cancelled=None):
    """Download yt-dlp's latest release into ``folder`` when it is newer than
    the one running and than one downloaded before. Returns its version, or
    None when there is nothing newer. Raises :class:`UpdateError`."""
    latest = latest_version(opener)
    pending = zip_version(zip_path(folder))  # downloaded, not started yet
    if not is_newer(latest, running_version()) or (pending and not is_newer(latest, pending)):
        return None
    download(latest, folder, opener, cancelled=cancelled)
    return latest


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
