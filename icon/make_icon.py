"""Render the app icon (orbida.svg) to app.png and app.ico for the Windows app.

    python icon/make_icon.py [path to chrome or headless_shell]

The SVG is the same drawing the Android app uses (android/icon/icon.svg).
Chromium draws it (any recent Chrome or Chromium works; pass its path or set
CHROME); Pillow rounds the corners and writes a PNG plus a real multi-size
.ico. Both files are kept in git, so a normal build needs neither tool.
"""

import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _chrome():
    for candidate in (sys.argv[1] if len(sys.argv) > 1 else None, os.environ.get("CHROME"),
                      shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("chrome")):
        if candidate:
            return candidate
    sys.exit("Pass the path to Chrome or Chromium")


def render(chrome):
    with open(os.path.join(HERE, "orbida.svg"), encoding="utf-8") as f:
        svg = f.read()
    # The Android launcher crops the foreground; a desktop icon shows it whole.
    svg = svg.replace("scale(0.82)", "scale(0.96)")
    with tempfile.TemporaryDirectory() as work:
        source = os.path.join(work, "icon.svg")
        out = os.path.join(work, "icon.png")
        with open(source, "w", encoding="utf-8") as f:
            f.write(svg)
        subprocess.run([chrome, "--headless", "--no-sandbox", "--hide-scrollbars", f"--screenshot={out}",
                        "--window-size=1024,1024", "--default-background-color=00000000", f"file://{source}"],
                       check=True, capture_output=True)
        full = Image.open(out).convert("RGBA")
    mask = Image.new("L", full.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, 999, 999), radius=200, fill=255)
    icon = Image.new("RGBA", full.size, (0, 0, 0, 0))
    icon.paste(full, (0, 0), mask)
    return icon


def main():
    icon = render(_chrome())
    icon.resize((256, 256), Image.LANCZOS).save(os.path.join(ROOT, "app.png"), optimize=True)
    icon.save(os.path.join(ROOT, "app.ico"), sizes=ICO_SIZES)
    print("Wrote app.png and app.ico")


if __name__ == "__main__":
    main()
