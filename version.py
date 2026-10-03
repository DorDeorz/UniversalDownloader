"""Single source of the app's name and version (ISSUES.md #65).

main.py, the window title, the build script, the PyInstaller spec, the
installer and the updater all read these values.
"""

APP_NAME = "Orbida"
DISPLAY_NAME = "Orbida"
__version__ = "1.0.1"
# The app was called UniversalDownloader before 1.0.0. Its per-user data
# folder is migrated from this name (see app_setup.data_dir).
LEGACY_APP_NAME = "UniversalDownloader"
# Windows taskbar grouping id and single-instance mutex name. Keep it stable
# across versions: the installer finds a running copy by it.
APP_USER_MODEL_ID = "DorDeorz.UniversalDownloader"
# Where releases are published; the updater reads the latest one.
GITHUB_REPO = "DorDeorz/UniversalDownloader"
