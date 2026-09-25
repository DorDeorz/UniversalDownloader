"""Find and verify FFmpeg and ffprobe (ISSUES.md #47-#49).

The app ships ``bin/ffmpeg.exe`` and ``bin/ffprobe.exe``. They are Git LFS
objects, so a clone without ``git lfs pull`` contains 134-byte pointer text
files instead of programs. :func:`find_tools` checks the bundled copies
first, then ``PATH``, runs ``-version`` on each and reports a clear reason
when they are missing or broken.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from utils import resource_path

LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/"
VERSION_TIMEOUT = 15


@dataclass
class ToolStatus:
    ok: bool
    directory: str | None = None   # folder holding both tools, for yt-dlp's ffmpeg_location
    ffmpeg: str | None = None
    ffprobe: str | None = None
    version: str | None = None
    source: str | None = None      # "bundled" or "PATH"
    error: str | None = None

    def summary(self):
        if self.ok:
            return f"FFmpeg {self.version} ({self.source}: {self.directory})"
        return f"FFmpeg problem: {self.error}"


def exe_name(tool):
    return tool + (".exe" if sys.platform == "win32" else "")


def bundled_dir():
    return resource_path("bin")


def is_lfs_pointer(path):
    try:
        with open(path, "rb") as f:
            return f.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX
    except OSError:
        return False


def _no_window_flags():
    # Don't flash a console window from the windowed EXE.
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def tool_version(path, run=subprocess.run):
    """First line of ``<tool> -version``, e.g. '7.1'; raises OSError on failure."""
    try:
        proc = run([path, "-version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT,
                   creationflags=_no_window_flags())
    except subprocess.TimeoutExpired as e:
        raise OSError(f"{os.path.basename(path)} did not answer within {VERSION_TIMEOUT}s") from e
    first = (proc.stdout or "").splitlines()[0] if proc.stdout else ""
    if proc.returncode != 0 or " version " not in first:
        raise OSError(f"{os.path.basename(path)} -version failed (exit code {proc.returncode})")
    return first.split(" version ", 1)[1].split()[0]


def check_pair(ffmpeg, ffprobe, source, run=subprocess.run):
    """Verify one ffmpeg/ffprobe pair; returns a ToolStatus."""
    for path in (ffmpeg, ffprobe):
        name = os.path.basename(path)
        if not os.path.isfile(path):
            return ToolStatus(False, source=source, error=f"{name} not found at {path}")
        if is_lfs_pointer(path):
            return ToolStatus(False, source=source, error=(
                f"{path} is a Git LFS pointer, not the program. Run 'git lfs pull' "
                "(or download FFmpeg) and try again."))
    try:
        version = tool_version(ffmpeg, run)
        tool_version(ffprobe, run)
    except OSError as e:
        return ToolStatus(False, source=source, error=str(e))
    return ToolStatus(True, directory=os.path.dirname(os.path.abspath(ffmpeg)), ffmpeg=ffmpeg,
                      ffprobe=ffprobe, version=version, source=source)


def find_tools(run=subprocess.run, which=shutil.which, bundled=None):
    """Bundled tools first, then PATH. The error names the bundled problem."""
    folder = bundled or bundled_dir()
    bundled_status = check_pair(os.path.join(folder, exe_name("ffmpeg")),
                                os.path.join(folder, exe_name("ffprobe")), "bundled", run)
    if bundled_status.ok:
        return bundled_status

    ffmpeg, ffprobe = which("ffmpeg"), which("ffprobe")
    if ffmpeg and ffprobe:
        path_status = check_pair(ffmpeg, ffprobe, "PATH", run)
        if path_status.ok:
            return path_status
    return ToolStatus(False, error=(
        f"{bundled_status.error} No working ffmpeg and ffprobe were found on PATH either. "
        "Downloads need FFmpeg."))


def activate(status):
    """Put the tools' folder first on PATH for this process.

    yt-dlp honours ``ffmpeg_location`` for merging and conversion, but its
    check for partial (trimmed) downloads only looks on PATH, so without this
    trimming fails with "ffmpeg is not installed" in the packaged app.
    """
    if not status.ok or not status.directory:
        return
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if status.directory not in parts:
        os.environ["PATH"] = os.pathsep.join([status.directory, *[p for p in parts if p]])
