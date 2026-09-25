"""Build the Windows EXE from UniversalDownloader.spec (ISSUES.md #48, #61-#66, #72, #77).

Refuses to build when an input is missing or broken, so a bad EXE is never
produced: FFmpeg/ffprobe must be real programs (not Git LFS pointers) that
run, and app.ico must be a real .ico file. After the build it writes
SHA256SUMS.txt and build-info.json next to the EXE.

Usage (in a clean virtual environment with requirements-dev.txt):
    python build_app.py
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata

import media_tools
from version import APP_NAME, __version__

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(ROOT, "UniversalDownloader.spec")
DIST = os.path.join(ROOT, "dist")
ICO_MAGIC = b"\x00\x00\x01\x00"


def check_icon(path):
    """Error text if ``path`` is not a real Windows .ico file."""
    try:
        with open(path, "rb") as f:
            header = f.read(4)
    except OSError:
        return f"{path} not found"
    if header != ICO_MAGIC:
        return f"{path} is not a real .ico file (a renamed PNG does not work as a window icon)"
    return None


def check_virtualenv():
    """Error text when building outside a virtual environment (global packages leak in)."""
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        return "Build inside a virtual environment so only the pinned packages are bundled"
    return None


def preflight(root=ROOT, run=subprocess.run, require_windows=True):
    """All problems that must be fixed before building."""
    problems = []
    if require_windows and sys.platform != "win32":
        problems.append("The EXE can only be built on Windows")
    venv = check_virtualenv()
    if venv:
        problems.append(venv)
    bin_dir = os.path.join(root, "bin")
    tools = media_tools.check_pair(os.path.join(bin_dir, "ffmpeg.exe"), os.path.join(bin_dir, "ffprobe.exe"),
                                   "bundled", run)
    if not tools.ok:
        problems.append(tools.error)
    icon = check_icon(os.path.join(root, "app.ico"))
    if icon:
        problems.append(icon)
    for name in ("app.png", "THIRD_PARTY_NOTICES.md"):
        if not os.path.isfile(os.path.join(root, name)):
            problems.append(f"{name} not found")
    return problems


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit(root=ROOT):
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                                check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True,
                               check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return commit + ("-dirty" if dirty else "")


def write_manifest(exe_path, dist=DIST, root=ROOT):
    """SHA256SUMS.txt and build-info.json tie the EXE to its source and inputs."""
    files = [exe_path, os.path.join(root, "bin", "ffmpeg.exe"), os.path.join(root, "bin", "ffprobe.exe")]
    sums = {os.path.basename(p): sha256(p) for p in files}
    with open(os.path.join(dist, "SHA256SUMS.txt"), "w", encoding="utf-8") as f:
        for name, digest in sums.items():
            f.write(f"{digest}  {name}\n")
    packages = {}
    for name in ("customtkinter", "yt-dlp", "yt-dlp-ejs", "mutagen", "certifi", "pyinstaller"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    info = {
        "app": APP_NAME,
        "version": __version__,
        "git_commit": git_commit(root),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
        "sha256": sums,
    }
    with open(os.path.join(dist, "build-info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    return info


def main():
    problems = preflight()
    if problems:
        print("Cannot build:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    import PyInstaller.__main__
    print(f"Building {APP_NAME} {__version__} ...")
    PyInstaller.__main__.run([SPEC, "--clean", "--noconfirm", f"--distpath={DIST}"])
    exe_path = os.path.join(DIST, f"{APP_NAME}-{__version__}.exe")
    if not os.path.isfile(exe_path):
        print(f"Build finished but {exe_path} is missing")
        return 1
    info = write_manifest(exe_path)
    print(f"Done: {exe_path}")
    print(f"sha256 {info['sha256'][os.path.basename(exe_path)]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
