"""Build the Windows EXE from UniversalDownloader.spec (ISSUES.md #48, #61-#66, #72, #77).

Refuses to build when an input is missing or broken, so a bad EXE is never
produced: FFmpeg/ffprobe must be real programs (not Git LFS pointers) that
run, and app.ico must be a real .ico file. After the build it writes
SHA256SUMS.txt and build-info.json next to the EXE.

Usage (in a clean virtual environment with requirements-dev.txt):
    python build_app.py            one portable EXE
    python build_app.py --onedir   a folder, for the installer (installer/)

With --onedir, bin\deno.exe is bundled when present (--require-deno makes
it mandatory) so YouTube's JavaScript challenges work out of the box.
"""

import argparse

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


def check_deno(path, run=subprocess.run):
    """Error text if ``path`` is not a Deno that runs."""
    if not os.path.isfile(path):
        return f"{path} not found"
    try:
        result = run([path, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return f"{path} does not run: {e}"
    if result.returncode != 0 or result.stdout.split()[:1] != ["deno"]:
        return f"{path} does not answer --version like Deno"
    return None


def check_impersonation(available=None):
    """Error text when yt-dlp cannot impersonate a browser (no curl_cffi)."""
    if available is None:
        from logic import impersonation_available
        available = impersonation_available()
    if not available:
        return "curl_cffi is not installed; TikTok downloads would fail (pip install -r requirements.txt)"
    return None


def preflight(root=ROOT, run=subprocess.run, require_windows=True, require_deno=False, impersonation=None):
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
    impersonate = check_impersonation(impersonation)
    if impersonate:
        problems.append(impersonate)
    if require_deno:
        deno = check_deno(os.path.join(bin_dir, "deno.exe"), run)
        if deno:
            problems.append(deno)
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
    deno = os.path.join(root, "bin", "deno.exe")
    if os.path.isfile(deno):
        files.append(deno)
    sums = {os.path.basename(p): sha256(p) for p in files}
    with open(os.path.join(dist, "SHA256SUMS.txt"), "w", encoding="utf-8") as f:
        for name, digest in sums.items():
            f.write(f"{digest}  {name}\n")
    packages = {}
    for name in ("customtkinter", "yt-dlp", "yt-dlp-ejs", "curl-cffi", "mutagen", "certifi", "pyinstaller"):
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


def output_exe(onedir, dist=DIST):
    if onedir:
        return os.path.join(dist, APP_NAME, f"{APP_NAME}.exe")
    return os.path.join(dist, f"{APP_NAME}-{__version__}.exe")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--onedir", action="store_true", help="build a folder for the installer")
    parser.add_argument("--require-deno", action="store_true", help="fail unless bin\\deno.exe works")
    args = parser.parse_args(argv)
    problems = preflight(require_deno=args.require_deno)
    if problems:
        print("Cannot build:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    import PyInstaller.__main__
    print(f"Building {APP_NAME} {__version__} ({'folder' if args.onedir else 'single EXE'}) ...")
    os.environ["UVD_ONEDIR"] = "1" if args.onedir else "0"
    PyInstaller.__main__.run([SPEC, "--clean", "--noconfirm", f"--distpath={DIST}"])
    exe_path = output_exe(args.onedir)
    if not os.path.isfile(exe_path):
        print(f"Build finished but {exe_path} is missing")
        return 1
    info = write_manifest(exe_path)
    print(f"Done: {exe_path}")
    print(f"sha256 {info['sha256'][os.path.basename(exe_path)]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
