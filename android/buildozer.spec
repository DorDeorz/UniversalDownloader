# buildozer settings for the Android preview. Build with
# .github/workflows/android.yml, or locally on Linux (see android/README.md).

[app]
title = UniversalDownloader
package.name = universaldownloader
package.domain = io.github.dordeorz
# Filled by android/stage.py: android/app plus the shared modules.
source.dir = .build/src
source.include_exts = py,json,png
version = 0.1.0
icon.filename = %(source.dir)s/icon.png
orientation = portrait
fullscreen = 0

# udtools is the local recipe in android/recipes that adds FFmpeg, ffprobe
# and QuickJS. The rest are yt-dlp and the pure-Python parts of its
# recommended extras, pinned like requirements.txt. brotli, websockets,
# pycryptodomex and curl_cffi are left out: they need native builds, and
# yt-dlp works without them (TikTok may refuse downloads without curl_cffi).
requirements = python3,kivy==2.3.1,pyjnius,android,udtools,yt-dlp==2026.8.19,yt-dlp-ejs==0.8.0,certifi==2026.7.22,mutagen==1.48.1,requests==2.34.2,urllib3==2.7.0,idna==3.18,charset-normalizer==3.5.0

# Storage permission is only needed on Android 10 and older; newer versions
# let the app write its own files to Download/ without it.
android.permissions = INTERNET, ACCESS_NETWORK_STATE, (name=android.permission.WRITE_EXTERNAL_STORAGE;maxSdkVersion=29), (name=android.permission.READ_EXTERNAL_STORAGE;maxSdkVersion=29)
android.extra_manifest_application_arguments = manifest_application_arguments.xml

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
