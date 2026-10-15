**Orbida 1.2.0** brings a browser extension for Windows, Spotify songs with
their real names and album covers, subtitles, a speed limit and a proxy. This
release holds both apps:

- **Windows:** `Orbida-Setup-1.2.0.exe`, for Windows 10 or 11 (64-bit).
- **Android:** `Orbida-1.2.0.apk`, for 64-bit ARM phones with Android 7 or newer.

Orbida 1.0 updates itself to this version: on Windows click **Update to
1.2.0** in the top bar; on Android open Settings › About › Check for
updates.

## New in 1.2.0 (both apps)

- **Spotify songs keep Spotify's names and cover.** Files are named
  "Artist - Song" and tagged with the title, artist, album and album cover
  from Spotify, not the YouTube video's.
- **Better song matches.** The first three YouTube results are compared and
  the one whose length is closest to the Spotify song wins, so long music
  videos and live versions lose to the plain song.
- **Subtitles.** Videos can be saved with their subtitles as .srt files, in
  the app's language and English (Windows: the Subtitles switch next to the
  mode; Android: Settings › Downloads).
- **Several links at once.** Paste a list of links and press Analyze: each
  one downloads in turn.
- **Speed limit** (1 to 20 MB/s) and **proxy** (HTTP or SOCKS) in Settings.

**Windows:**
- **Browser extension** for Chrome, Edge, Brave and Opera: a toolbar button
  and a right-click item send the video page or a link to Orbida, which opens
  if it is closed. Settings › Browser extension shows how to add it.
- **Clipboard watch.** With Settings › Copied links › Watch, every link you
  copy while Orbida runs is offered with a Download button.

## New in 1.1.1 (both apps)

- Spotify playlists longer than 100 songs now download in full. Before,
  only the first 100 songs were found.

## New in 1.1.0 (both apps)

- **New look**, after FitWren: warm neutral colours, filled cards, rounded
  buttons and a progress ring. Your accent colour stays the same.
- **Spotify** tracks, albums and playlists. Spotify's own audio is
  copy-protected, so each song is found on YouTube and saved as audio. The
  app switches to audio for these links.
- **Queue.** While a download runs, the Analyze button becomes **Add to
  queue**. Queued links start one after another. Cancel empties the queue.
- **Playlists remember** what you downloaded before. Those entries start
  unticked and are marked "downloaded before"; **Only new** selects the rest.

**Windows:** a new **Black** (AMOLED) theme in Settings › Theme, and
Download, History and Settings in the top bar.

**Android:**
- Choose which playlist videos to download.
- Downloads keep going in the background, with progress in a notification.
  Android 13 and newer ask once for permission to show notifications.
- Two tiles show the files and size downloaded in the last 7 days.
- A pure black (AMOLED) switch in Settings › Appearance.

## New in 1.0.1 (both apps)

- Fixed: Reddit videos failed with "The downloaded file is empty" after
  many "Conflicting range" errors. They download normally now.

Before this version, the Windows app was called Universal Video Downloader.

## Windows

**New in 1.0.0**
- The app is now called **Orbida** and has a new icon.
- If Universal Video Downloader 1.0.x is installed, this setup upgrades it
  in place. Your settings are kept, and the old shortcuts are replaced.
- **Updates inside the app.** Orbida checks GitHub for a new version when it
  opens; you can also press Settings › Updates › Check now. When a new
  version is found, click **Update to x.y.z** in the top bar. Orbida then:
  - downloads the new setup;
  - checks it against `SHA256SUMS.txt`;
  - installs it;
  - opens again.
- **History page.** Every finished download is listed there, with Open,
  Show in folder and Remove.
- **New settings, the same as in the Android app:**
  - accent colour, with eight colours;
  - parallel connections, so streamed videos download faster;
  - paste a copied link when the app opens;
  - keep the computer awake while downloading;
  - keep a download history.
- The settings page shows one setting per line and still fits on the
  screen.
- New downloads go to `Downloads\Orbida` by default. A folder you chose
  before stays the same.

**Install:** run `Orbida-Setup-1.1.1.exe`. It installs for your user only,
with no administrator password. FFmpeg, ffprobe and Deno are included.
The setup is not code-signed, so SmartScreen may say "Windows protected
your PC". Click **More info**, then **Run anyway**.

## Android

**New in 1.0.0**
- This is the first stable version, signed with the project's own key.
  Every later version installs over it.
- **Updates inside the app.** Orbida checks GitHub for a new version when
  it opens, downloads it, and asks Android to install it.
- Each version is now one GitHub release that holds both the Windows app and
  the Android app.

**Install:**
1. Open the APK on the phone.
2. Allow "Install unknown apps" when Android asks.
3. Tap **Install**.

The app is not on Google Play, so Play Protect may scan it or warn about an
unknown developer. Choose **More details**, then **Install anyway**. If you
have an Android preview (UniversalDownloader or Orbida 0.x), uninstall it
once first: 1.0 has a new app id and signing key.

**Earlier Android previews added:**
- a Material You design;
- History and Settings;
- TikTok, trimming and the Share menu;
- faster downloads;
- YouTube without an account, using the phone's browser engine when YouTube
  asks to confirm you're not a bot;
- a fix for the crash on phones with Qualcomm Adreno graphics;
- lighter, faster lists;
- the name Orbida.

`SHA256SUMS.txt` lists the checksums of both files. `build-info.json` records
the exact source commit and versions of the Windows build.
