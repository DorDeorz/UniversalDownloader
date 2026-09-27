# Building the Windows EXE

There is one build definition, `Orbida.spec`; `build_app.py`
checks the inputs, runs it and records what was built.

```
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
git lfs pull            # real bin\ffmpeg.exe and bin\ffprobe.exe
python build_app.py
```

Output in `dist\`:

- `Orbida-<version>.exe` (single file, windowed, no UPX)
- `SHA256SUMS.txt`: checksums of the EXE and the bundled FFmpeg/ffprobe
- `build-info.json`: version, git commit (with `-dirty` when the tree has
  uncommitted changes), Python and package versions, checksums

`build_app.py` refuses to build (and lists every problem) when:

- it is not running on Windows or not inside a virtual environment (a global
  site-packages would leak unpinned packages into the EXE);
- `bin\ffmpeg.exe` or `bin\ffprobe.exe` is missing, is a Git LFS pointer,
  or does not answer `-version`;
- `app.ico` is not a real `.ico` file, or `app.png` /
  `THIRD_PARTY_NOTICES.md` is missing.

## Installer

The installer packs a folder build, which starts fast because nothing is
unpacked on launch:

```
python build_app.py --onedir --require-deno   # needs bin\deno.exe
iscc /DAppVersion=1.0.0 installer\Orbida.iss
```

`--onedir` writes `dist\Orbida\` (the EXE plus `_internal\`).
With it, `bin\deno.exe` is bundled next to FFmpeg when present;
`--require-deno` makes it mandatory. The app puts that folder first on
`PATH`, where yt-dlp looks for Deno, and logs at startup whether it found
one.

`curl_cffi` (in `requirements.txt`) lets yt-dlp make browser-like requests.
TikTok needs it: without it TikTok answers with a page yt-dlp cannot read
("Unexpected response from webpage request"). yt-dlp's PyInstaller hook
bundles it automatically, the preflight refuses to build without it, and the
app logs at startup whether it is available.

`installer\Orbida.iss` (Inno Setup 6) makes
`dist\Orbida-Setup-<version>.exe`, which:

- installs for the current user without an administrator prompt, into
  `%LOCALAPPDATA%\Programs\Orbida` (or for all users, if chosen). An
  existing Universal Video Downloader 1.0.x install is upgraded in place (same
  AppId, same folder); its old program file and shortcuts are removed;
- adds a Start menu entry, an optional desktop shortcut and an uninstaller;
- asks the user to close the app first if it is running;
- replaces the whole program folder on upgrade, and keeps settings, logs
  and downloads on uninstall;
- with `/SILENT /RELAUNCH=1` (what the in-app updater passes) shows only its
  progress window and starts the new version when it is done.

## Release workflow

One GitHub Release per version holds both apps: `Orbida-Setup-<version>.exe`
(Windows), `Orbida-<version>.apk` (Android), `SHA256SUMS.txt` for both, and
`build-info.json`. It is tagged `orbida-v<version>`, and the in-app updaters
of both apps read the latest such release (see [updates.md](updates.md)).

`.github/workflows/release.yml`:

1. **Windows** (`windows-latest`): checks out with Git LFS, so the real FFmpeg
   and ffprobe are used; downloads the latest Deno; builds the folder and the
   installer; installs it silently, runs FFmpeg, ffprobe and Deno from the
   installed folder, starts the app and checks it is still running after 20
   seconds, then uninstalls it. It then installs again and lets the running
   app update itself with the new installer, the way the updater does, and
   checks that the app closed and started again.
2. **Android**: runs `.github/workflows/android.yml` (APK build and emulator
   test).
3. **Publish**: puts both files in one release with one checksum list. With
   **delete_android_previews** ticked it also deletes every
   `android-preview-*` pre-release and its tag.

Pushing a tag `orbida-v<version>` releases (the tag must match `version.py`).
A manual run from the Actions tab builds and tests only, unless **publish**
is ticked; then it also creates the tag on the chosen commit. The release
text is `RELEASE_NOTES.md`. Pull requests that change the Windows build run
the Windows job only.

The version lives only in `version.py`; the window title, the EXE name,
`build-info.json`, the release tag and the updater all read it. Bump it
there for a release. Releases up to 1.0.2 were called Universal Video
Downloader and tagged `v<version>`; the updater ignores those tags.

## Known limits

- **Portable EXE start-up**: the single EXE unpacks itself (about 200 MB
  with FFmpeg) to a temp folder on every start, so the first window takes a
  few seconds, and unsigned single-file EXEs are more likely to be flagged
  by SmartScreen or antivirus. The installer's folder build has neither
  problem.
- **YouTube JavaScript challenges**: `yt-dlp-ejs` is bundled, and yt-dlp
  also needs a JavaScript runtime for some YouTube formats. The installer
  ships Deno; the portable EXE and a source checkout use Deno from `PATH`
  if there is one, and otherwise yt-dlp logs a warning and may offer fewer
  formats.
- **Code signing** is not done, so SmartScreen warns on the installer too.
