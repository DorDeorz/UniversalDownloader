**Orbida for Android**, version 1.0.1 (64-bit ARM phones, Android 7 or newer). Not on Google Play; Android's Play Protect may scan it when it is installed.

Coming from an Android preview (UniversalDownloader or Orbida 0.x)? Uninstall it once: 1.0 has a new app id and signing key. From 1.0 on, the app updates itself (Settings › About › Check for updates).

**New in 1.0.1**
- Fixed: Reddit videos failed with "The downloaded file is empty". They download normally now.

**New in 1.0.0**
- The first stable version, signed with the project's own key, so every later version installs over it.
- Updates inside the app: Orbida looks for a new version on GitHub when it opens, downloads it and hands it to Android to install.
- Each version is one GitHub release with both the Windows and the Android app.

**New in 0.2.7**
- The app is now called Orbida; the start screen shows the name under the icon. New downloads go to `Download/Orbida`; earlier ones stay where they are and remain in History.
- Smoother: Settings, History and the choice dialogs open several times faster, Settings and History are prepared in the background after start-up, and touches and scrolling no longer run hundreds of mouse-hover checks.

**New in 0.2.6**
- YouTube without an account: when YouTube asks to "confirm you're not a bot", the app tries again through the phone's own browser engine, the way a browser would open the video. No sign-in needed.
- If YouTube blocks even that, the app says so and suggests Wi-Fi or another network. Signing in (Settings › YouTube) stays available but optional.

**New in 0.2.5**
- YouTube: sign in to YouTube inside the app (Settings › YouTube, or the button shown with the "confirm you're not a bot" error). YouTube lets signed-in sessions through; the sign-in stays on the phone. A spare Google account is safest.
- Copy diagnostic log starts with the app's own log and skips the first-start lines.

**New in 0.2.4**
- YouTube: when YouTube asks to "confirm you're not a bot", the app retries with YouTube's TV and embedded players, which are often let through, and keeps using the one that worked.
- Faster: a video's download reuses what Analyze found instead of asking the site again, and YouTube's player code is cached between runs.
- Quality, format and settings choices open in a scrolling dialog that fits every screen.
- Smoother: fewer redraws while downloading, History and Settings rebuilt only after a change, quicker tab switches.
- New app icon and start screen.

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
