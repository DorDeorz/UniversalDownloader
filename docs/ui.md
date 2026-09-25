# Main window

The window is built in `ui.py` with CustomTkinter. Colours are design
tokens at the top of the file, each a `(light, dark)` pair, so the Light,
Dark and System themes need no extra code.

## Layout

- **Sidebar**: the download folder (Change... and Open), the theme switch
  and the FFmpeg status found at startup.
- **Link card**: the URL field with Paste and Analyze. The line below it
  shows what the link contains, or why it was rejected (in red).
- **Options card**: mode (Video + Audio, Video Only, Audio Only), format,
  quality, and "Only part of the video" for trimming.
- **Actions**: Download (shows the item count), Cancel and Retry failed.
- **Progress card**: the current item ("2 of 5: title"), the bar, the
  percentage, and the speed and time left, or the current step such as
  "Merging" or "Converting audio". When a job ends the bar turns green
  (all done), amber (some failed) or red (none done).
- **Activity**: the log of what happened.

The window can be resized; the minimum size is 900x680.

## Links

`urls.normalize_url` checks the text before any network request. A missing
`https://` is added; text with spaces, a scheme other than http or https,
or a host without a dot (other than `localhost`) is rejected with a message
under the field.

## Saved settings

`settings.py` stores the folder, mode, format, quality and theme in
`%LOCALAPPDATA%\UniversalDownloader\settings.json`, written atomically
each time one of them changes. Unknown or invalid values in the file fall
back to the defaults, so a damaged file never stops the app from starting.
Trim times and the queue are not saved on purpose: they belong to one link.

## Playlist dialog

The dialog lists the entries that can be downloaded, says how many were
skipped and why, and adds only the chosen ones to the queue ("Add 7 to
queue"). With nothing selected the button is disabled.
