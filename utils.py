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
