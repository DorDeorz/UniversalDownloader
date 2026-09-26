**Android preview. This is not a Windows release;** the Windows installer is in the `v<version>` releases.

UniversalDownloader for Android phones (64-bit ARM, Android 7 or newer), version 0.2.3. It is debug-signed and not on Google Play.

**New in 0.2.3**
- Fixed: the app closed at the first tap on phones with Qualcomm Adreno graphics (many Xiaomi and Samsung phones). The touch ripple that crashed their graphics driver is off; buttons still light up when pressed.

**New in 0.2.2**
- After an unexpected close, the report also includes what Android logged about it.
- Settings › About › Copy diagnostic log copies the app's recent Android log.

**New in 0.2.1**
- When something goes wrong, the app stays open and shows the error instead of closing.
- If it still closes unexpectedly, the next start shows a report you can copy and send.

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

**Updating:** uninstall the old preview first; every preview is signed with a different debug key, so Android will not install over it.

**Install:** download the `.apk` on the phone, open it, allow "Install unknown apps" for your browser or file manager when Android asks, then tap Install. Play Protect may warn about an unknown developer; choose "Install anyway".
