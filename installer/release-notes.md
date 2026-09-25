## Install

1. Download **UniversalDownloader-Setup-<version>.exe** below and run it.
2. Windows SmartScreen may say "Windows protected your PC", because the
   installer is not code-signed. Click **More info**, then **Run anyway**.
3. Setup installs for your user only (no administrator password) into
   `%LOCALAPPDATA%\Programs\UniversalDownloader`, adds a Start menu entry
   and, if you tick it, a desktop shortcut.

Everything the app needs is included: the app itself, FFmpeg and ffprobe
for merging and converting, and Deno so YouTube works fully. Nothing else
has to be installed. Windows 10 or 11 (64-bit) is required.

Uninstall from **Settings > Apps**. Your settings and downloaded files are
kept.

`SHA256SUMS.txt` lists the checksums of the installer and the bundled
programs; `build-info.json` records the exact source commit and versions.
