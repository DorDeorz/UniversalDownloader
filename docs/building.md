# Building the Windows EXE

There is one build definition, `UniversalDownloader.spec`; `build_app.py`
checks the inputs, runs it and records what was built.

```
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
git lfs pull            # real bin\ffmpeg.exe and bin\ffprobe.exe
python build_app.py
```

Output in `dist\`:

- `UniversalDownloader-<version>.exe` (single file, windowed, no UPX)
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
iscc /DAppVersion=1.0.0 installer\UniversalDownloader.iss
```

`--onedir` writes `dist\UniversalDownloader\` (the EXE plus `_internal\`).
With it, `bin\deno.exe` is bundled next to FFmpeg when present;
`--require-deno` makes it mandatory. The app puts that folder first on
`PATH`, where yt-dlp looks for Deno, and logs at startup whether it found
one.

`installer\UniversalDownloader.iss` (Inno Setup 6) makes
`dist\UniversalDownloader-Setup-<version>.exe`, which:

- installs for the current user without an administrator prompt, into
  `%LOCALAPPDATA%\Programs\UniversalDownloader` (or for all users, if
  chosen);
- adds a Start menu entry, an optional desktop shortcut and an uninstaller;
- asks the user to close the app first if it is running;
- replaces the whole program folder on upgrade, and keeps settings, logs
  and downloads on uninstall.

## Release workflow

`.github/workflows/release.yml` runs on `windows-latest`:

1. Checks out with Git LFS, so the real FFmpeg and ffprobe are used.
2. Downloads the latest Deno and builds the folder and the installer.
3. Installs the result silently on the runner, runs FFmpeg, ffprobe and
   Deno from the installed folder, starts the app and checks it is still
   running after 20 seconds, then uninstalls it.
4. Uploads the installer, `SHA256SUMS.txt` and `build-info.json`, and
   publishes a GitHub Release with them.

Pushing a tag `v<version>` releases (the tag must match `version.py`). A
manual run from the Actions tab builds and tests only, unless **publish**
is ticked; then it also creates the tag on the chosen commit. The release
text is `installer\release-notes.md`.

The version lives only in `version.py`; the window title, the EXE name and
`build-info.json` all read it. Bump it there for a release.

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
