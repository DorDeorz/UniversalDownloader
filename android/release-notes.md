**Android preview. This is not a Windows release;** the Windows installer is in the `v<version>` releases.

UniversalDownloader for Android phones (64-bit ARM, Android 7 or newer), version 0.2.0. It is debug-signed and not on Google Play.

**New in 0.2.0**
- Material You design with Download, History and Settings tabs. On Android 12 and newer the colours follow your wallpaper.
- Settings: light, dark or system theme, accent colour, language, default mode, quality and formats, parallel connections, auto-paste, keep the screen on, history.
- About: version, what's new and the bundled components, in Settings.
- Faster downloads: streamed videos (Instagram, X, live) download several parts at once.
- TikTok support (browser impersonation with curl_cffi).
- Trim: download only part of a video.
- Share a link from another app straight to UniversalDownloader.
- Download history with Open, Share and Remove.
- More formats: MKV, FLAC, WAV and an audio bitrate choice.
- Smaller FFmpeg: its programs share one copy of the code.

**Updating from 0.1.0:** uninstall the old preview first; it was signed with a different debug key, so Android will not install over it.

**Install:** download the `.apk` on the phone, open it, allow "Install unknown apps" for your browser or file manager when Android asks, then tap Install. Play Protect may warn about an unknown developer; choose "Install anyway".
