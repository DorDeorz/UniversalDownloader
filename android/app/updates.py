"""Finding and downloading new versions of the app on GitHub.

Each Orbida version is one GitHub release tagged ``orbida-v<X.Y.Z>`` that
holds the Windows installer and the Android APK. The app lists the
repository's releases, keeps published (not draft, not pre-release) ones
with such a tag and an APK asset, and offers the newest if it is newer than
the running version. Releases without an APK (older UniversalDownloader
releases, or a new release whose APK is still being built) are skipped.

Downloading checks the size and, when GitHub reports one, the SHA-256
digest of the file. Android then checks that the APK is signed with the
same key as the installed app before it replaces it, so only builds signed
with the project's key can update the app.

Installing is Android's job: see ``android/java/.../UpdateInstaller.java``.
"""

import hashlib
import json
import os
import re
import ssl
import urllib.request
from dataclasses import dataclass

RELEASES_URL = "https://api.github.com/repos/DorDeorz/UniversalDownloader/releases?per_page=30"
TAG = re.compile(r"^orbida-v(\d+)\.(\d+)\.(\d+)$")
APK_SUFFIX = "-android-arm64-v8a.apk"
USER_AGENT = "Orbida-updater"
CHUNK = 256 * 1024


class UpdateError(Exception):
    """The update could not be found or downloaded; the message says why."""


class Cancelled(UpdateError):
    pass


@dataclass
class Update:
    version: str       # "1.2.0"
    tag: str           # "orbida-v1.2.0"
    notes: str         # the release's description (Markdown)
    page: str          # the release's web page
    url: str           # the APK's download link
    size: int          # bytes, 0 if unknown
    sha256: str        # hex digest, "" if GitHub did not report one
    name: str          # the APK's file name


def parse_version(text):
    """(1, 2, 0) for "1.2.0" or "orbida-v1.2.0"; None for anything else."""
    text = (text or "").strip()
    match = TAG.match(text) or re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", text)
    return tuple(int(part) for part in match.groups()) if match else None


def pick(releases, current):
    """The newest release in the GitHub API's ``releases`` list that is newer
    than ``current`` and carries an APK, as an ``Update``; else None."""
    running = parse_version(current) or (0, 0, 0)
    best = None
    for release in releases or ():
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name") or ""
        if not TAG.match(tag):
            continue
        version = parse_version(tag)
        if version <= running or (best and version <= best[0]):
            continue
        apk = next((a for a in release.get("assets") or ()
                    if isinstance(a, dict) and (a.get("name") or "").endswith(APK_SUFFIX)), None)
        if apk is None or not apk.get("browser_download_url"):
            continue
        digest = apk.get("digest") or ""
        best = (version, Update(
            version=".".join(map(str, version)),
            tag=tag,
            notes=release.get("body") or "",
            page=release.get("html_url") or "",
            url=apk["browser_download_url"],
            size=int(apk.get("size") or 0),
            sha256=digest[len("sha256:"):].lower() if digest.startswith("sha256:") else "",
            name=apk.get("name") or "",
        ))
    return best[1] if best else None


def _context():
    # The app points SSL_CERT_FILE at certifi's bundle on Android (android_env).
    cafile = os.environ.get("SSL_CERT_FILE")
    if not cafile:
        try:
            import certifi
            cafile = certifi.where()
        except ImportError:
            pass
    return ssl.create_default_context(cafile=cafile)


def _open(url, timeout, accept=None):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if accept:
        request.add_header("Accept", accept)
    context = _context() if url.startswith("https:") else None
    return urllib.request.urlopen(request, timeout=timeout, context=context)


def fetch_releases(url=RELEASES_URL, timeout=15):
    """The repository's releases, as the GitHub API returns them."""
    try:
        with _open(url, timeout, accept="application/vnd.github+json") as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as e:
        raise UpdateError(f"Could not check for updates: {e}") from e


def check(current, url=RELEASES_URL, timeout=15):
    """The newest ``Update`` over ``current``, or None when it is up to date."""
    return pick(fetch_releases(url, timeout), current)


def download(update, folder, progress=None, cancelled=None, timeout=30):
    """Download the update's APK into ``folder`` and return its path.

    ``progress(done, total)`` is called as it arrives; ``cancelled()``
    returning True stops it. The file only gets its final name once its
    size and digest have been checked.
    """
    os.makedirs(folder, exist_ok=True)
    name = re.sub(r"[^\w.-]", "_", update.name or f"Orbida-{update.version}.apk")
    path = os.path.join(folder, name)
    partial = path + ".part"
    digest = hashlib.sha256()
    done = 0
    try:
        with _open(update.url, timeout) as response, open(partial, "wb") as out:
            total = update.size or int(response.headers.get("Content-Length") or 0)
            while True:
                if cancelled and cancelled():
                    raise Cancelled("Cancelled")
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if update.size and done != update.size:
            raise UpdateError(f"The download stopped early ({done} of {update.size} bytes)")
        if update.sha256 and digest.hexdigest() != update.sha256:
            raise UpdateError("The downloaded file does not match the release (SHA-256)")
        os.replace(partial, path)
        return path
    except OSError as e:
        raise UpdateError(f"Could not download the update: {e}") from e
    finally:
        if os.path.exists(partial):
            os.remove(partial)


def remove_old(folder, keep=None):
    """Delete downloaded APKs other than ``keep`` (a path)."""
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        path = os.path.join(folder, name)
        if path != keep and (name.endswith(".apk") or name.endswith(".part")):
            try:
                os.remove(path)
            except OSError:
                pass


def short_notes(markdown, limit=1200):
    """Release notes as plain text for a dialog: no Markdown marks, cut to ``limit``."""
    lines = []
    for line in (markdown or "").replace("\r", "").split("\n"):
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^\s*[-*]\s+", "•  ", line)
        line = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        lines.append(line.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n…"
