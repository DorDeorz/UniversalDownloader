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

Tests import `logic` and `utils` only and replace `yt_dlp.YoutubeDL` with a
fake, so they need no network, no display and no FFmpeg. Known bugs that are
not fixed yet are recorded as `xfail` tests; they are strict, so the fix must
remove the marker.
