# FFmpeg and ffprobe

Every download mode needs FFmpeg (merging, conversion, metadata, trimming),
so the app checks for it at startup, on a worker thread (`media_tools.find_tools`):

1. The bundled `bin/ffmpeg(.exe)` and `bin/ffprobe(.exe)`. `bin/*.exe` are
   **Git LFS** objects: a clone without `git lfs pull` holds 134-byte pointer
   text files. These are detected and reported as "a Git LFS pointer, not the
   program. Run 'git lfs pull'".
2. Otherwise `ffmpeg` and `ffprobe` on `PATH`.

Each candidate must answer `-version` within 15 s (no console window is
opened on Windows). The log shows what was found, e.g.
`FFmpeg 7.1 (bundled: C:\...\bin)`.

If nothing works, an error dialog explains why, the status shows
"FFmpeg missing" and the download button reads **FFMPEG MISSING**; analysis
still works. `DownloadManager` also refuses to start a download without
FFmpeg, with the same message.

The tools' folder is passed to yt-dlp as `ffmpeg_location` (a folder, so
ffprobe is found next to ffmpeg) and put first on this process's `PATH`:
yt-dlp's check for partial (trimmed) downloads only looks on `PATH`, so
without it trimming failed with "ffmpeg is not installed" in the packaged app.
