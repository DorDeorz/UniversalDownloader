# HTTPS verification and error reporting

All `yt_dlp.YoutubeDL` instances are built from `logic.base_ydl_options()`.

- **HTTPS certificates are verified.** `nocheckcertificate` is never set, so a
  download from a server with an invalid or intercepted certificate fails with
  a `CERTIFICATE_VERIFY_FAILED` error instead of continuing silently.
- **Messages are not silenced.** Instead of `quiet`/`no_warnings`, yt-dlp output
  goes through `logic.YtDlpLogger`. Warnings and errors are forwarded to the
  optional `log_callback` (prefixed `Warning: ` for warnings) and to the
  `logic` Python logger; routine output goes to the logger at debug level.
- **Single downloads raise on failure.** `download_video` does not use
  `ignoreerrors`, so any failure (network, extractor, format, postprocessor)
  reaches `error_callback` and `complete_callback` is not called. A missing
  info result is also treated as a failure.
- **Playlist analysis tolerates bad entries.** `fetch_info` keeps
  `ignoreerrors` so one unavailable entry does not abort the whole playlist,
  but the entry errors are still logged, and when the whole lookup fails the
  returned `{'error', 'error_type'}` carries yt-dlp's real reason.

The UI does not yet pass `log_callback`; that wiring lands with the UI event
queue change so log lines are delivered on the main thread.
