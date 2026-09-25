# Main window

The window is built in `ui.py` with CustomTkinter. Colours are design
tokens at the top of the file, each a `(light, dark)` pair, so the Light,
Dark and System themes need no extra code.

## Layout

- **Top bar**: the app name and version, the FFmpeg status found at
  startup, and the Settings button.
- **Link card**: the URL field with Paste and Analyze. The line below it
  shows what the link contains, or why it was rejected (in red).
- **Options card**: mode (Video + Audio, Video Only, Audio Only), format,
  quality, "Only part of the video" for trimming, and **Save to**: the
  download folder (shortened in the middle when long) with Change... and
  Open.
- **Actions**: Download (shows the item count), Cancel and Retry failed.
- **Progress card**: the current item ("2 of 5: title"), the bar, the
  percentage, and the speed and time left, or the current step such as
  "Merging" or "Converting audio". When a job ends the bar turns green
  (all done), amber (some failed) or red (none done).
- **Activity**: the log of what happened.

The window can be resized. It grows to fit its content (up to the screen
size), so larger text sizes never cut off the bottom.

## Settings

The Settings button (or Ctrl+,) opens a dialog. Changes apply at once and
are saved:

- **Theme**: System, Dark or Light.
- **Text size**: Normal, Large (115%) or Larger (130%); scales all text and
  controls.
- **When downloads finish**: show a summary window (on by default) and
  open the download folder (off by default; only when something was saved).
- **Keyboard shortcuts** and **About** (version, FFmpeg found, a button to
  open the log folder).

## Keyboard

| Key | Action |
|---|---|
| Enter (in the link field) | Analyze the link |
| Ctrl+Enter | Start the download |
| Esc | Cancel the download |
| Ctrl+O | Choose the download folder |
| Ctrl+, | Open settings |

Shortcuts only act when the matching button is enabled. The link field has
focus when the app starts.

## Accessibility

Text is at least 12 px at normal size and uses the design tokens, which
keep body text above a 4.5:1 contrast ratio on its background in both
themes. Selected segments are a white chip in the light theme so their
dark text stays readable.

## Links

`urls.normalize_url` checks the text before any network request. A missing
`https://` is added; text with spaces, a scheme other than http or https,
or a host without a dot (other than `localhost`) is rejected with a message
under the field.

## Saved settings

`settings.py` stores the folder, mode, format, quality, theme, text size
and the two "when downloads finish" choices in
`%LOCALAPPDATA%\UniversalDownloader\settings.json`, written atomically
each time one of them changes. Unknown or invalid values in the file fall
back to the defaults, so a damaged file never stops the app from starting.
Trim times and the queue are not saved on purpose: they belong to one link.

## Playlist dialog

The dialog lists the entries that can be downloaded, says how many were
skipped and why, and adds only the chosen ones to the queue ("Add 7 to
queue"). With nothing selected the button is disabled.
