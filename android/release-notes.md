**Android preview. This is not a Windows release;** the Windows installer is in the `v<version>` releases.

A first test build of UniversalDownloader for Android phones (64-bit ARM, Android 7 or newer). It is debug-signed and not on Google Play.

**What works:** paste a link, Analyze, choose Video + Audio (MP4, with a quality limit) or Audio Only (MP3 or M4A), Download with progress and Cancel. Playlists download every available entry. Files go to `Download/UniversalDownloader` and show up in the gallery or music app.

**Not in this preview:** trimming, Video Only, choosing the folder, settings. TikTok may refuse downloads because browser impersonation (curl_cffi) is not available on Android yet. Keep the app open while it downloads; Android may stop it in the background.

**Install:** download the `.apk` on the phone, open it, allow "Install unknown apps" for your browser or file manager when Android asks, then tap Install. Play Protect may warn about an unknown developer; choose "Install anyway".
