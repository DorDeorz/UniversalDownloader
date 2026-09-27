# Updates

Orbida checks for a newer version when it opens (Settings › Updates, on by
default) and on **Check now**. `updates.py` has no Tk import, so the Android
app can share it.

## Which release counts

The updater reads `https://api.github.com/repos/DorDeorz/UniversalDownloader/releases/latest`
over HTTPS with certifi's CA bundle. GitHub never returns drafts or
pre-releases there. Only tags `orbida-v<major>.<minor>.<patch>` count; the
old `v1.0.x` releases of UniversalDownloader and the `android-preview-*`
pre-releases are ignored. Versions are compared as numbers, so 1.0.10 is
newer than 1.0.9. No answer (offline, rate limit) is logged and never stops
the app; a manual check says it could not check.

## What happens

1. A newer release shows an **Update to x.y.z** button in the top bar and a
   line in the activity log. The button opens a dialog with the release
   notes.
2. **Download and install** fetches `Orbida-Setup-<version>.exe` into
   `%LOCALAPPDATA%\Orbida\updates` and checks its SHA-256 against the
   release's `SHA256SUMS.txt`. A file that does not match (or a release
   without the list) is deleted and nothing is installed.
3. The app releases its single-instance lock, starts the installer with
   `/SILENT /SUPPRESSMSGBOXES /NORESTART /RELAUNCH=1` and closes. Setup
   shows its progress window, replaces the program folder and starts the new
   version. Settings, history and downloads are kept.
4. The first start of the new version logs "Orbida was updated to x.y.z".

The update waits while a media download runs. A copy run from source (not
the installed app) cannot replace itself; there the button opens the release
page instead.

## Checked by the release workflow

`release.yml` installs the new build, starts it with
`ORBIDA_SELFTEST_UPDATE` pointing at the installer (which makes the app run
step 3 after five seconds), and fails unless the app closed and a new copy
started. Unit tests cover tag parsing, version order, the checksum check,
cancelling and the installer command line (`tests/test_updates.py`), and
the button, dialog and hand-over in a real window (`tests/test_ui_orbida.py`).
