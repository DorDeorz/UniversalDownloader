import os
import sys

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

def get_ffmpeg_path():
    """ Returns path to bundled ffmpeg """
    return resource_path(os.path.join("bin", "ffmpeg.exe"))

def get_ffprobe_path():
    """ Returns path to bundled ffprobe """
    return resource_path(os.path.join("bin", "ffprobe.exe"))