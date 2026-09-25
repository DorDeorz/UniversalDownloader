# Download modes and formats

`formats.py` turns the Mode / Format / Quality choices into yt-dlp options.
The UI only offers the choices that are valid for the selected mode, and
`build_format_plan()` rejects anything else before any network access.

| Mode | Formats | Quality | What is downloaded |
|---|---|---|---|
| Video + Audio | mp4, mkv, webm | Best, 2160p (4K), 1440p, 1080p, 720p, 480p, 360p | Best video at or below the height plus best audio, merged into the container |
| Video Only | mp4, mkv, webm | same | A video stream at or below the height; if the site only has files with sound, the audio track is removed afterwards |
| Audio Only | mp3, m4a, opus, flac, wav | Best, 320/192/128 kbps (ignored for flac and wav) | The audio track converted to that codec; the file extension always matches the codec |

## Rules

- **The height is a hard limit.** Selectors are `bv*[height<=H]+ba/b[height<=H]`
  with no unrestricted `/best` fallback, so 720p never produces a 1080p file.
  When nothing fits, the item fails with "No 720p or lower version of this
  video is available". Only sources that report no height at all (direct file
  links) can pass the limit; the log then shows a warning.
- **The container is guaranteed.** `merge_output_format` covers merged
  downloads and `FFmpegVideoRemuxer` covers single files. After the metadata
  pass, `postprocessors_for()` checks the selected codecs; if they cannot be
  remuxed into the container (for example H.264 into webm) the file is
  re-encoded with `FFmpegVideoConvertor` instead.
- **Codec preference per container.** Formats are sorted by resolution first,
  then by codecs that fit the container (H.264/AAC for mp4, VP9/Opus for webm).
- **Audio must exist.** Video + Audio and Audio Only fail with "This media has
  no audio track" when yt-dlp reports that no selected format has audio.
- **Cover art** is embedded only into containers that support it (not wav or
  webm). Embedding into opus and flac needs `mutagen`.
- The log shows what was picked, e.g. `Format: 1920x1080 avc1 + mp4a -> mp4`.

## Verifying against real FFmpeg

`tests/test_formats.py` runs yt-dlp's real format selector on a synthetic
YouTube-like format list. Conversions were also checked end to end with
FFmpeg against locally served files (see `tests/test_integration_ffmpeg.py`).
