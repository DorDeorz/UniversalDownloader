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

## Running the tests

```
pip install pytest customtkinter yt-dlp
python -m pytest tests
```

`tests/test_ui_events.py::test_real_window_applies_worker_events_on_main_thread`
opens a real window; on Linux without a display it is skipped (run it with
`xvfb-run -a python -m pytest tests`).
