"""The software inside the Android app and its licenses (Settings › About › Licenses).

The Windows app shows THIRD_PARTY_NOTICES.md; the APK carries a different
set of programs (no Deno or CustomTkinter, but Kivy, QuickJS and Python
for Android), listed here.
"""

# (component, what it does in the app, license)
COMPONENTS = (
    ("yt-dlp", "media extraction and download", "Unlicense"),
    ("yt-dlp-ejs", "YouTube JavaScript challenge solver scripts", "Unlicense / MIT"),
    ("FFmpeg (libffmpeg.so, libffprobe.so, libav*.so)", "merging, conversion, trimming",
     "LGPL v3 (built with --enable-version3, without GPL parts)"),
    ("LAME (in FFmpeg)", "MP3 encoding", "LGPL v2"),
    ("Mbed TLS (in FFmpeg)", "HTTPS for trimming", "Apache-2.0"),
    ("zlib (in FFmpeg)", "compression", "zlib License"),
    ("QuickJS-ng (libqjs.so)", "runs YouTube's JavaScript challenges", "MIT"),
    ("Python", "runtime", "PSF License"),
    ("python-for-android, pyjnius", "Android packaging and Java access", "MIT"),
    ("Kivy", "user interface", "MIT"),
    ("SDL2", "window, input and graphics for Kivy", "zlib License"),
    ("KivyMD, materialyoucolor", "Material Design widgets and colours", "MIT"),
    ("asynckivy, asyncgui", "KivyMD helpers", "MIT"),
    ("curl_cffi with curl-impersonate, cffi", "browser-like requests (TikTok)",
     "MIT (bundles curl and BoringSSL under their own licenses)"),
    ("certifi", "CA certificates for HTTPS verification", "MPL-2.0"),
    ("charset-normalizer", "text encodings", "MIT"),
    ("mutagen", "song tags and cover art", "GPL v2 or later"),
    ("OpenSSL (Python's ssl)", "HTTPS", "Apache-2.0"),
    ("Material Design Icons", "icons", "Apache-2.0 / Pictogrammers Free License"),
    ("Roboto", "font", "Apache-2.0 / OFL-1.1"),
)

SOURCE = "https://github.com/DorDeorz/UniversalDownloader"


def text():
    """The list as plain text, one component per paragraph."""
    lines = [f"{name}\n{use} · {license_}" for name, use, license_ in COMPONENTS]
    lines.append(f"Orbida: {SOURCE}\nFFmpeg: https://ffmpeg.org/legal.html")
    return "\n\n".join(lines)
