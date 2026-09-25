# Development

## Setup

Requires Python 3.11+.

```
python -m venv .venv
.venv\Scripts\activate          # Windows (source .venv/bin/activate elsewhere)
python -m pip install -r requirements-dev.txt
git lfs pull                    # fetches the real bin/ffmpeg.exe and bin/ffprobe.exe
```

`requirements.txt` holds the exact runtime pins; `requirements-dev.txt` adds
pytest, ruff and PyInstaller. Bump a pin deliberately, then run the checks below.

## Checks

```
python -m ruff check .
python -m pytest
```

CI (`.github/workflows/ci.yml`) runs both on Windows and Ubuntu for every pull
request and every push to `main`.

Most tests replace `yt_dlp.YoutubeDL` with a fake, so they need no network,
no display and no FFmpeg. Two groups need more and skip themselves otherwise:

- UI tests drive a real window and need a display (`xvfb-run -a python -m pytest`
  on Linux).
- `tests/test_integration_ffmpeg.py` runs real downloads through yt-dlp and
  FFmpeg against media it generates and serves on `127.0.0.1`. It needs a
  working ffmpeg and ffprobe, bundled in `bin/` (after `git lfs pull`) or on
  `PATH`. CI installs FFmpeg on Linux so these always run there. Known bugs that are
not fixed yet are recorded as `xfail` tests; they are strict, so the fix must
remove the marker.
