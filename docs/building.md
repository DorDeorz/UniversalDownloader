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

The version lives only in `version.py`; the window title, the EXE name and
`build-info.json` all read it. Bump it there for a release.

## Known limits

- **Onefile start-up**: the single EXE unpacks itself (about 200 MB with
  FFmpeg) to a temp folder on every start, so the first window takes a few
  seconds, and unsigned single-file EXEs are more likely to be flagged by
  SmartScreen or antivirus. Switching the spec to a one-folder build fixes
  both if that becomes a problem.
- **Code signing** needs a certificate and is not part of the build.
- **YouTube JavaScript challenges**: `yt-dlp-ejs` is bundled, but yt-dlp also
  needs a JavaScript runtime (Deno, Node, Bun or QuickJS) on PATH for some
  YouTube formats. Without one, yt-dlp logs a warning and may offer fewer
  formats.
