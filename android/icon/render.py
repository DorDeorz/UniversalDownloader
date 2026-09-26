"""Render the app icon (icon.svg) to the PNG files the Android build uses.

    python android/icon/render.py [path to chrome or headless_shell]

Chromium draws the SVG (any recent Chrome or Chromium works; pass its path
or set CHROME). Pillow then scales and masks the layers. The PNGs are kept
in git, so a normal build needs neither.

Files written next to this script:

* icon_fg.png, icon_bg.png: foreground and background of the adaptive
  icon Android 8+ shows in the shape the launcher chooses;
* icon.png: the same icon as a rounded square, for older Android versions;
* presplash.png: the glyph on the background colour with the app's name
  under it, shown while the app starts. The name is drawn in Roboto Medium
  from the installed KivyMD package.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 512
SPLASH_COLOUR = "#221B4F"  # keep in step with android.presplash_color in buildozer.spec
APP_NAME = "Orbida"        # keep in step with title in buildozer.spec


def _chrome():
    for candidate in (sys.argv[1] if len(sys.argv) > 1 else None, os.environ.get("CHROME"),
                      shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("chrome")):
        if candidate:
            return candidate
    sys.exit("Pass the path to Chrome or Chromium")


def _render(svg_text, out, chrome, workdir):
    source = os.path.join(workdir, "layer.svg")
    with open(source, "w", encoding="utf-8") as f:
        f.write(svg_text)
    subprocess.run([chrome, "--headless", "--no-sandbox", "--hide-scrollbars", f"--screenshot={out}",
                    "--window-size=1024,1024", "--default-background-color=00000000", f"file://{source}"],
                   check=True, capture_output=True)
    return Image.open(out).convert("RGBA")


def _without(svg, group):
    return re.sub(rf'<g id="{group}".*?\n  </g>\n', "", svg, flags=re.S)


def _scaled(svg, factor):
    return svg.replace('transform="translate(512 512) scale(0.82) translate(-512 -512)"',
                       f'transform="translate(512 512) scale({factor}) translate(-512 -512)"')


def _wordmark(image, text, centre_y, size, tracking):
    """Write ``text`` centred at ``centre_y``, in the tray's white, letter-spaced."""
    kivymd = os.path.dirname(importlib.util.find_spec("kivymd").origin)  # found, not imported (that opens a window)
    font = ImageFont.truetype(os.path.join(kivymd, "fonts", "Roboto-Medium.ttf"), size)
    widths = [font.getlength(char) for char in text]
    x = (image.width - sum(widths) - tracking * (len(text) - 1)) / 2
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for char, width in zip(text, widths):
        draw.text((x, centre_y), char, font=font, fill=(255, 255, 255, 235), anchor="lm")
        x += width + tracking
    image.alpha_composite(layer)


def main():
    chrome = _chrome()
    with open(os.path.join(HERE, "icon.svg"), encoding="utf-8") as f:
        svg = f.read()
    with tempfile.TemporaryDirectory() as work:
        full = _render(_scaled(svg, 1.0), os.path.join(work, "full.png"), chrome, work)
        fg = _render(_without(svg, "background"), os.path.join(work, "fg.png"), chrome, work)
        bg = _render(_without(svg, "foreground"), os.path.join(work, "bg.png"), chrome, work)
        splash = _render(_scaled(_without(svg, "background"), 0.5), os.path.join(work, "splash.png"), chrome, work)

    fg.resize((SIZE, SIZE), Image.LANCZOS).save(os.path.join(HERE, "icon_fg.png"), optimize=True)
    bg.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(os.path.join(HERE, "icon_bg.png"), optimize=True)

    # Older Android versions show the icon as it is: round its corners.
    mask = Image.new("L", (1024, 1024), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, 983, 983), radius=220, fill=255)
    legacy = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    legacy.paste(full, (0, 0), mask)
    legacy.resize((SIZE, SIZE), Image.LANCZOS).save(os.path.join(HERE, "icon.png"), optimize=True)

    presplash = Image.new("RGBA", (1024, 1024), SPLASH_COLOUR)
    presplash.alpha_composite(splash)
    _wordmark(presplash, APP_NAME, centre_y=730, size=72, tracking=6)
    presplash.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(
        os.path.join(HERE, "presplash.png"), optimize=True)


if __name__ == "__main__":
    main()
