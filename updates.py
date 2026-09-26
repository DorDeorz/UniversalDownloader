"""Find, download and verify a newer Orbida release.

Releases are published on GitHub with one tag per version,
``orbida-v<major>.<minor>.<patch>``, holding the Windows installer
(``Orbida-Setup-<version>.exe``), the Android app (``Orbida-<version>.apk``)
and ``SHA256SUMS.txt`` for both. The updater reads the repository's latest
release (GitHub never returns drafts or pre-releases there) and ignores tags
in any other form, such as the ``v1.0.x`` releases of UniversalDownloader.

Nothing here touches the UI; it has no Tk import, so the Android app can
use it too. Network access verifies HTTPS certificates with certifi's CA
bundle, like the downloads themselves (ISSUES.md #1).
"""

import hashlib
import json
import logging
import os
import re
import ssl
import urllib.request
from dataclasses import dataclass

from version import GITHUB_REPO, __version__

_log = logging.getLogger(__name__)

TAG_PREFIX = "orbida-v"
LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
SUMS_NAME = "SHA256SUMS.txt"
TIMEOUT = 20
_TAG = re.compile(r"^" + re.escape(TAG_PREFIX) + r"(\d+)\.(\d+)\.(\d+)$")
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class UpdateError(Exception):
    """The release could not be read, downloaded or verified."""


def parse_version(text):
    """(major, minor, patch) from ``1.2.3``, or None."""
    match = _VERSION.match(str(text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def version_from_tag(tag):
    """``1.2.3`` from ``orbida-v1.2.3``; None for any other tag."""
    match = _TAG.match(str(tag or "").strip())
    return ".".join(match.groups()) if match else None


def is_newer(candidate, current=__version__):
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def installer_name(version):
    return f"Orbida-Setup-{version}.exe"


def apk_name(version):
    return f"Orbida-{version}.apk"


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    page: str          # the release's web page
    notes: str         # release notes (Markdown)
    assets: dict       # file name -> download URL

    def asset_url(self, name):
        return self.assets.get(name)


def parse_release(data):
    """A :class:`Release` from GitHub's release JSON, or None if it is not an Orbida release."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    version = version_from_tag(data.get("tag_name"))
    if version is None:
        return None
    assets = {}
    for asset in data.get("assets") or []:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str) \
                and isinstance(asset.get("browser_download_url"), str):
            assets[asset["name"]] = asset["browser_download_url"]
    return Release(version, data["tag_name"], data.get("html_url") or RELEASES_PAGE,
                   data.get("body") or "", assets)


def parse_sums(text):
    """File name -> lower-case SHA-256 from a ``sha256sum`` style listing."""
    sums = {}
    for line in str(text or "").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            sums[parts[1].lstrip("*").strip()] = parts[0].lower()
    return sums


def _context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover - certifi is a pinned dependency
        return ssl.create_default_context()


def _open(url, accept="application/octet-stream"):
    request = urllib.request.Request(url, headers={
        "Accept": accept, "User-Agent": f"Orbida/{__version__} (+https://github.com/{GITHUB_REPO})"})
    return urllib.request.urlopen(request, timeout=TIMEOUT, context=_context())


def fetch_latest(opener=None):
    """The latest Orbida release, or None when there is none.

    Raises :class:`UpdateError` when GitHub cannot be reached or answers
    with something unexpected.
    """
    opener = opener or _open
    try:
        with opener(LATEST_URL, "application/vnd.github+json") as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        if getattr(e, "code", None) == 404:
            return None  # no release published yet
        raise UpdateError(f"Could not check for updates: {e}") from e
    return parse_release(data)


def check(current=__version__, opener=None):
    """The latest release when it is newer than ``current``, else None."""
    release = fetch_latest(opener)
    if release is not None and is_newer(release.version, current):
        return release
    return None


def download_installer(release, folder, progress=None, cancel_event=None, opener=None):
    """Download the Windows installer of ``release`` into ``folder`` and verify it.

    ``progress(done_bytes, total_bytes)`` is called as data arrives (total
    may be 0 when unknown). Returns the installer's path. The file is only
    kept when its SHA-256 matches the release's SHA256SUMS.txt; any
    problem raises :class:`UpdateError` and removes the partial file.
    """
    opener = opener or _open
    name = installer_name(release.version)
    url, sums_url = release.asset_url(name), release.asset_url(SUMS_NAME)
    if not url:
        raise UpdateError(f"The release has no {name}")
    if not sums_url:
        raise UpdateError(f"The release has no {SUMS_NAME}, so {name} cannot be verified")
    try:
        with opener(sums_url) as response:
            expected = parse_sums(response.read(1024 * 1024).decode("utf-8", "replace")).get(name)
    except Exception as e:
        raise UpdateError(f"Could not read {SUMS_NAME}: {e}") from e
    if not expected:
        raise UpdateError(f"{SUMS_NAME} does not list {name}")

    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    partial = path + ".part"
    digest = hashlib.sha256()
    try:
        with opener(url) as response, open(partial, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0) if getattr(response, "headers", None) else 0
            done = 0
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise UpdateError("Cancelled")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if digest.hexdigest() != expected:
            raise UpdateError(f"{name} does not match its checksum; it was not installed")
        os.replace(partial, path)
    except UpdateError:
        _remove(partial)
        raise
    except Exception as e:
        _remove(partial)
        raise UpdateError(f"Could not download {name}: {e}") from e
    return path


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def installer_command(path):
    """Command line that updates in place: progress window only, then start the new version."""
    return [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"]


def notes_summary(notes, limit=900):
    """The release notes shortened for a dialog: Markdown marks removed, cut at ``limit``."""
    lines = []
    for line in str(notes or "").splitlines():
        line = re.sub(r"\*\*|__|`", "", line).rstrip()
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        lines.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n…"
