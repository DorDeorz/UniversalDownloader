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

The window can be resized. It grows to fit its content, but never past the
screen's work area (on Windows, the screen minus the taskbar), and moves up
if its bottom edge would go under the taskbar. Spare height goes to the
activity box; when the window cannot be tall enough (large text on a small
screen, or the user made it smaller) the content scrolls instead of being
cut off. The playlist dialog also grows with the text size, stays within
the work area and uses the app icon.

## Settings

The Settings button (or Ctrl+,) opens the settings page inside the main
window, in place of the download page; Back, Esc or the Settings button
again return to it. Changes apply at once and are saved.

The page never scrolls. Its cards sit in two columns (appearance on the
left; finish actions and shortcuts on the right). When the window is too
short, the hints under the appearance settings are hidden first, then the
spacing tightens. It fits at every text size on 1280x720 and 1366x768 at
100%, 1366x768 at 125% and 1920x1080 at 150% Windows scaling. The one
setup found that does not fit is Larger text at 150% scaling on a
1280x720 screen. The settings are:

- **Language**: one of 25 languages, or the system language (the
  default). The whole window switches at once, without a restart.
- **Theme**: System, Dark or Light.
- **Text size**: Normal, Large (115%) or Larger (130%); scales all text and
  controls.
- **When downloads finish**: show a summary window (on by default) and
  open the download folder (off by default; only when something was saved).
- **Keyboard shortcuts**. The page header also shows the version and a
  button that opens the log folder.

## Keyboard

| Key | Action |
|---|---|
| Enter (in the link field) | Analyze the link |
| Ctrl+Enter | Start the download |
| Esc | Cancel the download, or leave the settings page |
| Ctrl+O | Choose the download folder |
| Ctrl+, | Open settings |

Shortcuts only act when the matching button is enabled. The link field has
focus when the app starts.

## Accessibility

Text is at least 12 px at normal size and uses the design tokens, which
keep body text above a 4.5:1 contrast ratio on its background in both
themes. Selected segments are a white chip in the light theme so their
dark text stays readable.

## Languages

`i18n.py` holds the list of languages and `tr(key, **values)`, which
returns a message in the current language. The messages are JSON files in
`locales/`, one per language code, mapping a key such as
`"action.download_n"` to text with `{count}`-style placeholders.
`en.json` is complete and is the fallback for any missing key or broken
placeholder. `tests/test_i18n.py` checks that every language has every key
with the same placeholders.

To change a text, edit `en.json` and the same key in the other files. To
add a language, copy `en.json` to `locales/<code>.json`, translate the
values, and add the code with the language's own name to
`i18n.LANGUAGES`. Right-to-left and Indic scripts are not offered because
Tk does not lay them out correctly.

Widgets that show translated text are registered with `App._live`, and
choices (mode, quality, theme, text size) use `ChoiceSegment` and
`ChoiceMenu`, which show translated labels but keep the English values in
the code and in `settings.json`. Messages that come from websites or
yt-dlp (such as "HTTP Error 403"), file paths and the FFmpeg line in the
activity log stay as they are; the log file is always in English.

## Links

`urls.normalize_url` checks the text before any network request. A missing
`https://` is added; text with spaces, a scheme other than http or https,
or a host without a dot (other than `localhost`) is rejected with a message
under the field.

## Saved settings

`settings.py` stores the folder, mode, format, quality, theme, text size,
language and the two "when downloads finish" choices in
`%LOCALAPPDATA%\UniversalDownloader\settings.json`, written atomically
each time one of them changes. Unknown or invalid values in the file fall
back to the defaults, so a damaged file never stops the app from starting.
Trim times and the queue are not saved on purpose: they belong to one link.

## Playlist dialog

The dialog lists the entries that can be downloaded, says how many were
skipped and why, and adds only the chosen ones to the queue ("Add 7 to
queue"). With nothing selected the button is disabled.
