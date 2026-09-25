"""Android glue: where files go and how the bundled programs are found.

Android does not let an app run programs from its writable storage. The
APK therefore ships FFmpeg, ffprobe and QuickJS as ``lib<name>.so`` files;
Android unpacks them into the app's native library folder, where running
them is allowed. yt-dlp looks for fixed names (``ffmpeg``, ``ffprobe``,
``qjs``), so :func:`link_tools` puts symlinks with those names in a folder
of their own.

The functions that talk to Android through pyjnius only run on a device;
the rest is plain Python and is unit tested on the desktop.
"""

import os

# Name yt-dlp expects -> file name in the APK's native library folder.
TOOLS = {
    "ffmpeg": "libffmpeg.so",
    "ffprobe": "libffprobe.so",
    "qjs": "libqjs.so",
}
DOWNLOAD_SUBFOLDER = "UniversalDownloader"


def on_android():
    return "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ


def link_tools(native_dir, link_dir):
    """Point ``link_dir/<name>`` at each bundled program that exists.

    The native library folder moves when the app is updated, so the links
    are rebuilt on every start. Returns ``{name: link path}`` for the
    programs found.
    """
    os.makedirs(link_dir, exist_ok=True)
    found = {}
    for name, lib in TOOLS.items():
        target = os.path.join(native_dir, lib)
        link = os.path.join(link_dir, name)
        if not os.path.isfile(target):
            _remove(link)
            continue
        temp = link + ".new"
        _remove(temp)
        os.symlink(target, temp)
        os.replace(temp, link)
        found[name] = link
    return found


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def js_runtime_options(links):
    """yt-dlp options that use the bundled QuickJS for YouTube, if present."""
    if "qjs" not in links:
        return {}
    return {"js_runtimes": {"quickjs": {"path": links["qjs"]}}}


def choose_download_dir(candidates, check):
    """First folder ``check`` accepts; ``check`` returns an error text or None.

    Returns ``(folder, errors)`` where ``errors`` lists why earlier
    candidates were refused, or ``(None, errors)`` when none works.
    """
    errors = []
    for folder in candidates:
        if not folder:
            continue
        error = check(folder)
        if error is None:
            return folder, errors
        errors.append(error)
    return None, errors


# --- Device-only helpers (pyjnius) -------------------------------------------------


def _activity():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity


def native_library_dir():
    return _activity().getApplicationInfo().nativeLibraryDir


def files_dir():
    return _activity().getFilesDir().getAbsolutePath()


def cache_dir():
    return _activity().getCacheDir().getAbsolutePath()


def public_downloads_dir():
    """``Download/UniversalDownloader`` on the shared storage."""
    from jnius import autoclass
    env = autoclass("android.os.Environment")
    base = env.getExternalStoragePublicDirectory(env.DIRECTORY_DOWNLOADS).getAbsolutePath()
    return os.path.join(base, DOWNLOAD_SUBFOLDER)


def app_downloads_dir():
    """The app's own folder on shared storage; always writable, removed on uninstall."""
    folder = _activity().getExternalFilesDir(None)
    return os.path.join(folder.getAbsolutePath(), "Downloads") if folder else None


def sdk_version():
    from jnius import autoclass
    return autoclass("android.os.Build$VERSION").SDK_INT


def request_storage_permission(callback=None):
    """Ask for storage access where Android still needs it (Android 10 and older)."""
    if sdk_version() > 29:
        if callback:
            callback(True)
        return
    from android.permissions import Permission, request_permissions

    def done(permissions, grants):
        if callback:
            callback(all(grants))

    request_permissions([Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE], done)


def scan_media(path):
    """Tell Android's media index about a new file so galleries and players see it."""
    from jnius import autoclass
    scanner = autoclass("android.media.MediaScannerConnection")
    scanner.scanFile(_activity(), [path], None, None)


def device_language():
    from jnius import autoclass
    return autoclass("java.util.Locale").getDefault().getLanguage()


def clipboard_text():
    """Text on the clipboard, or ''."""
    from kivy.core.clipboard import Clipboard
    return Clipboard.paste() or ""
