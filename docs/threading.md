# Threading and UI updates

Tkinter widgets must only be touched from the main thread (the one running
`mainloop()`). Analysis and downloads run on worker threads, so they never
call widget methods directly.

- `events.EventQueue` is a thread-safe FIFO. Workers call `post(kind, **payload)`.
- `App` registers one handler per event kind and drains the queue on the main
  thread every 50 ms via `after()` (`App._poll_events`). The poll is cancelled
  in `App.destroy()`.
- `App.log()` posts a `log` event, so it is safe from any thread. Handlers that
  run on the main thread write to widgets with `_append_log`, `_show_progress`
  and friends.

| Event | Posted by | Main-thread effect |
|---|---|---|
| `log` | `App.log`, `on_error` | Append a console line |
| `progress` | `progress_hook` | Set progress bar and percentage label |
| `analysis_done` | `run_analysis` | Re-enable Analyze; open playlist selector or queue the video |
| `analysis_failed` | `run_analysis` | Re-enable Analyze; log the error |
| `item_done` | `run_queue`, once per item | Log the item's result (saved path, or failed/skipped/cancelled with the reason) |
| `job_done` | `run_queue` (always, via `finally`) | End the job, show a summary dialog (info when every item completed, warning otherwise) |

A handler that raises is reported in the console and does not stop later
events. `events.progress_from_hook` derives the progress fraction from
yt-dlp's byte counters and falls back to `_percent_str` with ANSI colour codes
stripped.

## Download results

`DownloadManager.download_video()` returns a `results.ItemResult` instead of
calling success/error callbacks. Its status is `completed`, `failed`,
`skipped` or `cancelled`; a result is only `completed` when the final file
(from yt-dlp's `requested_downloads[-1]['filepath']`, i.e. after merging and
conversion) exists and is not empty. `run_queue` collects the results in a
`results.JobSummary`, which gives the headline ("2 completed, 1 failed") and
the list of items that did not complete for the final dialog.

## One job at a time

`App._start_job()` is the only way a worker thread is started. It refuses to
start a second job while one is running (`App.is_busy()`), keeps the thread
handle in `_job_thread` (daemon, named `uvd-<kind>`), and disables the URL,
folder, format and trim controls until the job's final event (`analysis_done`,
`analysis_failed` or `job_done`) calls `_end_job()` on the main thread.

Starting a new analysis clears the previous queue and progress, and editing the
URL after an analysis drops the analysed queue, so a download can never use the
results of a different URL.

## Cancel, retry and closing the window

- **Cancel** sets a `threading.Event` that is bound to the running job. The
  progress hook and the postprocessor hook raise `DownloadCancelled` when it
  is set, so a download stops at its next progress update and conversions
  stop before the next step. The item is reported as `cancelled`, the files
  it was writing (`.part`, `.ytdl`, `.part-FragN` and finished intermediate
  streams) are removed, and the remaining queue items are reported as
  `cancelled` without starting.
- **Network limits**: every yt-dlp instance uses a 30 s socket timeout and
  bounded retries (`retries`, `fragment_retries`, `extractor_retries`), so a
  dead connection fails the item instead of hanging the job.
- **Retry failed** re-queues only the items the last job reported as
  `failed`.
- **Closing the window** during a download asks for confirmation, cancels
  the job and waits (up to 15 s) for the worker to clean up before the window
  is destroyed. During an analysis the window closes at once; the analysis
  thread is a daemon and touches no widgets.

## Running the tests

```
pip install pytest customtkinter yt-dlp
python -m pytest tests
```

`tests/test_ui_events.py::test_real_window_applies_worker_events_on_main_thread`
opens a real window; on Linux without a display it is skipped (run it with
`xvfb-run -a python -m pytest tests`).
