import os
import sys

# Directory the app's resources are resolved against when not frozen.
# Anchored on this file, not the current working directory, so running
# the app from another folder still finds bin/ and app.ico.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    base_path = getattr(sys, "_MEIPASS", _BASE_DIR)
    return os.path.join(base_path, relative_path)

def get_ffmpeg_path():
    """ Returns path to bundled ffmpeg """
    return resource_path(os.path.join("bin", "ffmpeg.exe"))

def get_ffprobe_path():
    """ Returns path to bundled ffprobe """
    return resource_path(os.path.join("bin", "ffprobe.exe"))


# FOLDERID_Downloads, see KNOWNFOLDERID in the Windows SDK.
_FOLDERID_DOWNLOADS = "{374DE290-123F-4565-9164-39C4925E467B}"


def _windows_downloads_dir():
    """The user's real Downloads folder (follows OneDrive/moved folders)."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

    guid = GUID()
    ctypes.oledll.ole32.CLSIDFromString(_FOLDERID_DOWNLOADS, ctypes.byref(guid))
    path_ptr = ctypes.c_wchar_p()
    ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path_ptr))
    try:
        return path_ptr.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)


def default_download_dir():
    """``<Downloads>/UniversalVideos``, using the Windows known folder when available."""
    downloads = None
    if sys.platform == "win32":
        try:
            downloads = _windows_downloads_dir()
        except (OSError, AttributeError, ValueError):
            downloads = None
    if not downloads:
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    return os.path.join(downloads, "UniversalVideos")
