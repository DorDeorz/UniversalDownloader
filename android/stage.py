"""Put the Android app's sources together for buildozer.

buildozer packages one folder. The Android app reuses the download code at
the repository root instead of keeping a copy, so this script copies the
shared modules and the translations next to ``android/app`` into
``android/.build/src`` (ignored by git) before each build.

    python android/stage.py
"""

import os
import shutil
import sys

ANDROID = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(ANDROID)
DEST = os.path.join(ANDROID, ".build", "src")

# Modules from the repository root the Android app imports (directly or
# through each other). Nothing Tk- or Windows-specific.
SHARED_MODULES = (
    "events.py",
    "filenames.py",
    "formats.py",
    "i18n.py",
    "logic.py",
    "media_tools.py",
    "playlist.py",
    "results.py",
    "urls.py",
    "utils.py",
    "version.py",
)


def stage(dest=DEST):
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for name in SHARED_MODULES:
        shutil.copy2(os.path.join(ROOT, name), dest)
    for name in os.listdir(os.path.join(ANDROID, "app")):
        if name.endswith((".py", ".json")):
            shutil.copy2(os.path.join(ANDROID, "app", name), dest)
    shutil.copytree(os.path.join(ROOT, "locales"), os.path.join(dest, "locales"))
    return dest


if __name__ == "__main__":
    print(f"Staged Android sources in {stage(sys.argv[1] if len(sys.argv) > 1 else DEST)}")
