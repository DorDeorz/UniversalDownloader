# UniversalDownloader for Android (preview)

A small Android version of the downloader, for trying the core flow on a
phone. It is a preview: the Windows app in the repository root is the
product, and its build and releases do not change.

## What it does

One screen: paste a link, **Analyze**, choose **Video + Audio** (MP4 with a
quality limit) or **Audio Only** (MP3 or M4A), **Download**, with progress
and **Cancel**. Playlists download every available entry. Files are saved to
`Download/UniversalDownloader/<site>/` and added to the media index, so they
show up in gallery and music apps. When that folder cannot be written, the
app uses its own folder under `Android/data/io.github.dordeorz.universaldownloader/`.

Not in the preview: trimming, Video Only, picking a folder, settings, and
TikTok (needs `curl_cffi`, which is not built for Android yet).

## How it is built

- **UI:** [Kivy](https://kivy.org), packaged with buildozer and
  python-for-android. Flet was the other candidate, but its build cannot add
  executable programs to the APK, and the downloader needs FFmpeg as a
  program.
- **Shared code:** `android/stage.py` copies the repository's download
  modules (`logic.py`, `formats.py`, `filenames.py`, `playlist.py`,
  `events.py` and the rest listed in `SHARED_MODULES`) and `locales/` next to
  `android/app/` before each build. There is no second copy in git.
  `android/app/worker.py` runs analysis and downloads on a worker thread and
  reports through the same `events.EventQueue` the Windows app uses.
- **FFmpeg, ffprobe and QuickJS:** `android/native/build_tools.sh` builds
  them with the Android NDK (FFmpeg without GPL parts, plus LAME for MP3).
  Android only lets apps run programs from their native library folder, so
  they are packaged as `libffmpeg.so`, `libffprobe.so` and `libqjs.so` by
  the local recipe in `android/recipes/udtools`. At start the app links them
  under the names yt-dlp expects (`android/app/android_env.py`).
- **YouTube:** the Windows app uses Deno for YouTube's JavaScript
  challenges. Deno does not run on Android, so the app passes the bundled
  QuickJS to yt-dlp instead (`logic.set_platform_options`).

## Building

`.github/workflows/android.yml` builds on every change to `android/` or the
shared modules:

1. `native`: FFmpeg, ffprobe and QuickJS for arm64-v8a and x86_64 (cached).
2. `apk`: the debug-signed APK for phones (arm64-v8a) and one for the
   emulator (x86_64), as workflow artifacts.
3. `emulator`: installs the x86_64 APK on an Android 14 emulator and runs
   `android/emulator_test.sh`, which starts the app with a `selftest_url`
   extra. The app then downloads a local test video as MP4 and as MP3 and
   logs `UDSELFTEST` lines the script checks.

Run the workflow by hand with **publish** ticked to attach the phone APK to
a GitHub pre-release tagged `android-preview-<run number>`. It is never
marked as the latest release.

Locally on Linux, with an NDK and buildozer installed:

```sh
android/native/build_tools.sh /tmp/native-tools arm64-v8a
python android/stage.py
cd android
UD_NATIVE_TOOLS_DIR=/tmp/native-tools buildozer android debug
```

## Installing on a phone

The APK is not on Google Play (Play does not allow YouTube downloaders).
Download the `.apk` on the phone and open it. Android asks to allow
"Install unknown apps" for the browser or file manager you opened it from;
allow it, go back and tap **Install**. Play Protect may warn about an
unknown developer; choose **More details → Install anyway**. The APK is
debug-signed, so a later preview installs over it only if it was built with
the same debug key; otherwise uninstall the old one first.
