# buildozer settings for the Android preview. Build with
# .github/workflows/android.yml, or locally on Linux (see android/README.md).

[app]
title = UniversalDownloader
package.name = universaldownloader
package.domain = io.github.dordeorz
# Filled by android/stage.py: android/app plus the shared modules.
source.dir = .build/src
source.include_exts = py,json,png
version = 0.2.1
icon.filename = %(source.dir)s/icon.png
orientation = portrait
fullscreen = 0

# Local recipes in android/recipes: udtools adds FFmpeg, ffprobe and
# QuickJS; kivymd, materialyoucolor, curl_cffi and charset_normalizer
# install pinned wheels without pulling in dependencies the app does not use
# (see android/recipes/wheel_recipe.py). cffi comes from python-for-android
# for curl_cffi, which lets yt-dlp impersonate a browser (TikTok). The rest
# are yt-dlp and the pure-Python parts of its extras, pinned like
# requirements.txt; brotli, websockets and pycryptodomex need native builds
# and yt-dlp works without them.
requirements = python3,kivy==2.3.1,pyjnius,android,udtools,charset_normalizer,materialyoucolor,kivymd,asyncgui==0.6.3,asynckivy==0.6.4,cffi,curl_cffi,yt-dlp==2026.8.19,yt-dlp-ejs==0.8.0,certifi==2026.7.22,mutagen==1.48.1

# Storage permission is only needed on Android 10 and older; newer versions
# let the app write its own files to Download/ without it.
# WAKE_LOCK keeps a download running while the screen is off.
android.permissions = INTERNET, ACCESS_NETWORK_STATE, WAKE_LOCK, (name=android.permission.WRITE_EXTERNAL_STORAGE;maxSdkVersion=29), (name=android.permission.READ_EXTERNAL_STORAGE;maxSdkVersion=29)
android.extra_manifest_application_arguments = manifest_application_arguments.xml
# Offer the app in Android's Share menu for links (text); a link shared
# while the app runs reaches the same activity (singleTask).
android.manifest.intent_filters = intent_filters.xml
android.manifest.launch_mode = singleTask

android.api = 35
android.minapi = 24
android.ndk = 28c
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = False
android.enable_androidx = True

p4a.local_recipes = recipes
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 0
