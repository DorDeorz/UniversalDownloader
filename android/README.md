# UniversalDownloader for Android (preview)

A small Android version of the downloader, for trying the core flow on a
phone. It is a preview: the Windows app in the repository root is the
product, and its build and releases do not change.

## What it does

A Material You app (Material Design 3, colours from the wallpaper on
Android 12 and newer) with three tabs:

- **Download:** paste or share a link, **Analyze**, choose **Video** (MP4
  or MKV, with a quality limit) or **Audio** (MP3, M4A, FLAC or WAV, with a
  bitrate), optionally **Only part of it** (start and end time), then
  **Download** with progress and **Cancel**. Playlists download every
  available entry. Files are saved to `Download/UniversalDownloader/<site>/`
  and added to the media index, so they show up in gallery and music apps.
  When that folder cannot be written, the app uses its own folder under
  `Android/data/io.github.dordeorz.universaldownloader/`.
- **History:** what was downloaded, with Open, Share and Remove.
- **Settings:** theme (system, light, dark), wallpaper colours, accent
  colour, language, default mode, quality and formats, parallel
  connections, auto-paste from the clipboard, analyzing shared links at
  once, keeping the screen on while downloading, history on/off, and
  **About** with the version, what's new (`android/app/whats_new.json`) and
  the bundled components.

Links can be shared to the app from any app's **Share** menu. While a
download runs the app holds a wake lock, so it continues with the screen
off as long as Android keeps the app alive.

Not in the app: Video Only, picking a folder, background downloads after
the app is closed.

Speed and YouTube:

- Downloading a single video starts from the information Analyze already
  fetched (`info=` in `DownloadManager.download_video`) for up to 20
  minutes, so the site is not asked twice; if those links have expired,
  the worker tries once more with fresh information.
- yt-dlp's cache (YouTube's player code and solved challenges) lives in the
  app's cache folder.
- YouTube sometimes answers "Sign in to confirm you're not a bot" to phone
  networks. The app's `DownloadManager` is built with
  `logic.BOT_CHECK_CLIENTS`, so it then retries with the `tv` and
  `web_embedded`/`tv_downgraded` player clients (none needs a PO token) and
  keeps the one that worked. The Windows app does not turn this on.
- Progress is sent to the screen at most four times a second, the log is
  drawn only while it is open, and History and Settings are rebuilt only
  when shown after a change.

The icon is `android/icon/icon.svg`; `android/icon/render.py` draws the
PNGs buildozer uses (adaptive icon layers, a rounded icon for Android 7 and
the start screen).

## How it is built

- **UI:** [Kivy](https://kivy.org) with [KivyMD 2](https://github.com/kivymd/KivyMD)
  for the Material 3 widgets, packaged with buildozer and
  python-for-android. Flet was the other candidate, but its build cannot add
  executable programs to the APK, and the downloader needs FFmpeg as a
  program. `android/app/layout.py` holds the screens in Kivy language,
  `main.py` the behaviour, `app_settings.py` and `history.py` the JSON files
  in the app's private folder, and `texts.py` the Android-only texts
  (English and Turkish; other languages show English).
- **Shared code:** `android/stage.py` copies the repository's download
  modules (`logic.py`, `formats.py`, `filenames.py`, `playlist.py`,
  `events.py` and the rest listed in `SHARED_MODULES`) and `locales/` next to
  `android/app/` before each build. There is no second copy in git.
  `android/app/worker.py` runs analysis and downloads on a worker thread and
  reports through the same `events.EventQueue` the Windows app uses.
- **FFmpeg, ffprobe and QuickJS:** `android/native/build_tools.sh` builds
  them with the Android NDK (FFmpeg without GPL parts, plus LAME for MP3 and
  mbedTLS for HTTPS). Android only lets apps run programs from their native
  library folder, so they are packaged as `libffmpeg.so`, `libffprobe.so`
  and `libqjs.so` by the local recipe in `android/recipes/udtools`, next to
  FFmpeg's shared libraries (`libavcodec.so`, ...), which both programs use,
  so the code is in the APK once. At start the app links the programs under
  the names yt-dlp expects and sets `LD_LIBRARY_PATH`
  (`android/app/android_env.py`).
- **Trimming:** yt-dlp lets FFmpeg read only the wanted part of the video
  from the server, so FFmpeg needs HTTPS. mbedTLS has no certificate store
  on Android; `android/native/ffmpeg-mbedtls-cafile.patch` makes FFmpeg
  check certificates against `$SSL_CERT_FILE`, which the app points at
  certifi's bundle.
- **Speed:** the parallel connections setting becomes yt-dlp's
  `concurrent_fragment_downloads` (HLS/DASH videos download several parts at
  once) and plain files are fetched in 10 MB ranges
  (`app_settings.download_speed_options`).
- **TikTok:** yt-dlp needs `curl_cffi` to impersonate a browser. PyPI has an
  Android wheel for 64-bit ARM, which the local recipe
  `android/recipes/curl_cffi` installs (stripped of debug symbols); the
  x86_64 emulator build has none.
- **Wheels:** `android/recipes/wheel_recipe.py` installs a pinned, hashed
  wheel without its dependencies. KivyMD, materialyoucolor, curl_cffi and
  charset-normalizer use it, because python-for-android either picks
  versions that do not fit or cannot install Android wheels itself.
- **YouTube:** the Windows app uses Deno for YouTube's JavaScript
  challenges. Deno does not run on Android, so the app passes the bundled
  QuickJS to yt-dlp instead (`logic.set_platform_options`).

## Building

`.github/workflows/android.yml` builds on every change to `android/` or the
shared modules:

1. `native`: FFmpeg, ffprobe and QuickJS for arm64-v8a and x86_64 (cached
   by the contents of `android/native/`).
2. `apk`: the debug-signed APK for phones (arm64-v8a) and one for the
   emulator (x86_64), as workflow artifacts.
3. `emulator`: on an Android 14 emulator, `android/emulator_ui_test.sh`
   first starts the app normally and taps through its tabs and buttons,
   for the x86_64 APK and for the phone APK under the emulator's ARM
   translation; it fails if the app closes or logs a `UDCRASH` error. Then
   `android/emulator_test.sh` starts the app with a `selftest_url`
   extra. The app then downloads a local test video as MP4, as MP3 and
   trimmed to seconds 1 to 3, and logs `UDSELFTEST` lines the script
   checks. Setting `UD_SELFTEST_URL` runs the same passes on a desktop.

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

## When it goes wrong

KivyMD 2.0 draws its touch ripple through an `Fbo` whose shader is set
after the `Fbo` is made, which crashes Qualcomm Adreno drivers on the first
tap (kivymd/KivyMD#1900, #1508). The emulator's software GPU does not, so CI
cannot see it. `android/app/md_patches.py` switches the ripple off before
any widget is built.


A Python error in the app no longer closes it: the app records it, shows
it in a snackbar and keeps running. If the app does close (a crash in
native code), `faulthandler` has written the stack of every Python thread
to the app's folder, and the next start shows that report with a **Copy
report** button (`android/app/crash_report.py`). That report also carries
what Android's crash log holds for the app since the last report (Java
exceptions, fatal signals), which apps may read for their own user id. The
Android log carries the same text on lines starting with `UDCRASH`, and
Settings › About › **Copy diagnostic log** copies the app's recent log at
any time. The emulator UI test crashes the app with `am crash` and checks
that the next start reports it.
