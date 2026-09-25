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
| `job_done` | `run_queue` (always, via `finally`) | Mark finished, show the "Done" dialog |

A handler that raises is reported in the console and does not stop later
events. `events.progress_from_hook` derives the progress fraction from
yt-dlp's byte counters and falls back to `_percent_str` with ANSI colour codes
stripped.

## One job at a time

`App._start_job()` is the only way a worker thread is started. It refuses to
start a second job while one is running (`App.is_busy()`), keeps the thread
handle in `_job_thread` (daemon, named `uvd-<kind>`), and disables the URL,
folder, format and trim controls until the job's final event (`analysis_done`,
`analysis_failed` or `job_done`) calls `_end_job()` on the main thread.

Starting a new analysis clears the previous queue and progress, and editing the
URL after an analysis drops the analysed queue, so a download can never use the
results of a different URL.

## Running the tests

```
pip install pytest customtkinter yt-dlp
python -m pytest tests
```

`tests/test_ui_events.py::test_real_window_applies_worker_events_on_main_thread`
opens a real window; on Linux without a display it is skipped (run it with
`xvfb-run -a python -m pytest tests`).
