# Playlists

Analysis (`App.run_analysis`, on the worker thread) passes yt-dlp's flat
result to `playlist.analyze()`, which returns an `AnalysisResult`:

- `items`: entries that can be queued, each a `QueueItem` with URL, title,
  1-based playlist position (`index`), playlist title and duration.
- `skipped`: entries that cannot be downloaded, with a reason: missing
  entry (`None`), `[Private video]` / `[Deleted video]` placeholders,
  `availability` of private / premium / subscriber-only / sign-in, live or
  upcoming streams, nested playlists, and entries without an absolute URL.
  An ID is only turned into a YouTube watch URL when the entry comes from
  YouTube.

`entries=None`, an empty list or a generator are all handled; an analysis
with nothing downloadable shows a warning instead of an empty queue.

## Selector dialog

`PlaylistSelector` is modal (`transient` + `grab_set`) and ends with exactly
one callback: the chosen items on confirm, or `None` when cancelled or
closed. Confirm is disabled while nothing is selected. Rows are created in
batches of 50 on idle, so large playlists do not freeze the window. The
selection is only queued if the URL field still holds the analysed link.

Skipped entries are carried into the download job and reported as
`skipped` in the final summary.
