# Output files

`filenames.py` decides where each download is saved.

- **Folder**: `<download folder>/<platform>/[<playlist title>/]`. The platform
  comes from yt-dlp's extractor (`Youtube` -> `YouTube`, `Generic` -> `Other`,
  any other site by its extractor name), not from text in the URL.
- **Name**: `%(title)s.<ext>`; playlist items start with their position,
  `007 - Title.mp3`, so the order survives on disk. `windowsfilenames` is
  always on, the playlist folder is sanitized the same way, and the title is
  cut (in bytes) so the full path stays under the Windows 260-character
  limit.
- **No overwrites**: after the metadata pass the final name is computed;
  if any file with that name already exists, whatever its extension, the
  name gets a numeric suffix: `Title (2).mp4`, `Title (3).mp4`. Checking all
  extensions matters because yt-dlp would otherwise reuse an existing
  `Title.mp4` as the "already downloaded" source for a new `Title.mp3`. The
  log says when a suffix was added. `overwrites` is off as a second guard.
- **Before a job starts** the folder is created and a temporary file is
  written to prove it is writable; otherwise the job does not start and the
  reason is shown. Less than 1 GB of free space logs a warning.
- **Default folder**: `UniversalVideos` inside the user's real Downloads
  folder (Windows known folder, so OneDrive or moved folders are followed).
