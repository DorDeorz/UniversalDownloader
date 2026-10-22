**Orbida 1.2.4** continues a failed download where it stopped, checks
every finished file, saves subtitles in several languages, and reworks the
Download, History and Settings pages of both apps. This release holds both
apps and the Firefox add-on:

- **Windows:** `Orbida-Setup-1.2.4.exe`, for Windows 10 or 11 (64-bit).
- **Android:** `Orbida-1.2.4.apk`, for 64-bit ARM phones with Android 7 or newer.
- **Firefox:** `Orbida-Firefox-1.2.4.xpi`, the browser extension signed by Mozilla.

Orbida 1.0 updates itself to this version: on Windows click **Update to
1.2.4** in the top bar; on Android open Settings › About › Check for
updates.

## New in 1.2.4

**Both apps:**
- **Subtitles in several languages**, as srt, ass or vtt, and embedded into
  the video if you like (Windows: Settings › Advanced; Android: Settings ›
  Downloads).
- **SponsorBlock parts** can be chosen (sponsor, self-promotion, intro,
  outro, reminders, music off-topic).
- **Update channel:** stable or beta, and **Skip this version** when an
  update is offered.
- **History:** search, Show more, Download again, and Undo after Remove
  (removing never deletes the file); dates in your system's format.
- **Playlist picker:** search, entries left out with the reason, and pages
  of 100 rows, so playlists of thousands open at once.
- **After a download:** Open the file, Retry the failed ones, Download
  again.
- **Waiting links** can be moved up or down or taken out of the queue.
- **Errors stay** in a card or band until you close them.
- **The activity log** wraps, scrolls and has Copy and Clear.
- Spotify songs match better: the name counts too, and live takes, covers
  and remixes lose to the song. Long Spotify playlists are read faster.

**Windows:**
- **A failed download continues** from its partial files on the next try.
  Only the same video with the same formats and file type continues;
  partial files older than 7 days are deleted.
- **Every finished file is checked** with ffprobe: it opens and has the
  tracks its mode promises.
- **Settings has tabs:** General, Advanced (subtitles, SponsorBlock,
  connection test, detailed log, Copy diagnostics, live streams from their
  start, update channel, forget downloaded links, reset settings) and About
  (versions, What's new, licenses). Every tab fits a 1366×768 screen with
  Larger text.
- **Live streams** can be downloaded from their start.
- **Only new** in playlists now uses its own download list, so it keeps
  working after the history is cleared.
- The Download, Pause and Cancel buttons stay at the bottom; a clear button
  in the link field; long titles wrap; a bar for jobs of several items;
  tooltips and first-run tips.
- The window opens where it was closed, and shrinks back after a smaller
  text size.
- Names Windows reserves (CON, NUL, COM1...) and very long folders are
  handled; more yt-dlp errors are translated.
- Notifications come from Orbida's tray icon; the update check runs at most
  once a day.

**Android:**
- **Notification buttons:** Pause/Resume and Cancel while downloading, Open
  when finished.
- A single video shows its picture and about how big the file will be.
- The Download button stays at the bottom; trimming sits under **More
  options**; a long playlist shows how much has been read.
- Settings has search, a **Licenses** page and an option to stop Android
  from pausing downloads to save battery.
- Landscape and tablets; the sign-in page follows the dark theme; screen
  readers hear tab changes and results.
- The playlist choice is remembered per playlist.

## New in 1.2.3

**Both apps:**
- **Pause and resume.** A running download can be paused and picks up
  where it stopped (Windows: the Download button reads Pause while a
  download runs; Android: the button on the progress card).
- **yt-dlp stays up to date.** When Orbida looks for updates it also
  fetches the newest yt-dlp (checked against its published checksum) and
  uses it from the next start, so a site that changed works again without
  waiting for a new Orbida.
- **Cancel an analysis.** A long playlist or a slow site can be stopped
  while it is being read.
- **More sign-ins.** Instagram posts and age-restricted YouTube videos that
  need an account now say so and offer a sign-in:
  - Windows: Settings › Downloads › **Use my browser's sign-in** now lends
    your Firefox or Zen sign-in to Reddit, Instagram, YouTube, Facebook, X
    and TikTok (and to no other site).
  - Android: Settings › **Instagram** sign-in; YouTube's sign-in is offered
    for age-restricted videos.
- A failed download no longer leaves half-downloaded files behind.
- Checking for and downloading updates goes through the proxy from
  Settings.

**Windows:**
- **Keep running in the tray.** With Settings › Downloads › **Keep running
  in the tray when closed**, closing the window keeps Orbida in the
  notification area: downloads go on, and the icon shows their progress.
  Starting Orbida again brings its window back.
- A file whose name differs only in capital letters no longer counts as a
  new name.
- Pasting text with a link in it keeps just the link; the activity box is
  read-only; Open log folder opens the right folder; the window fits the
  monitor it is on.

**Android:**
- **Wi-Fi only.** Settings › Behaviour › **Download on Wi-Fi only** asks
  before downloading on mobile data and pauses a running download until
  Wi-Fi is back.
- All of the app's texts are now in all 25 languages.
- A link shared while a download runs waits in the queue; Back closes a
  dialog or returns to Download; low free space is pointed out before a
  download.

## New in 1.2.2

**Both apps:**
- **NSFW Reddit posts.** Reddit shows them only to signed-in accounts, and
  they failed with "Account authentication is required". The sign-in is
  optional and off by default:
  - Windows: Settings › Downloads › **Use my browser's Reddit sign-in**.
    Orbida sends Reddit the reddit.com cookies of your Firefox or Zen (also
    LibreWolf, Floorp, Waterfox); no other site gets them, and Orbida never
    sees a password.
  - Android: Settings › Reddit › **Sign in to Reddit**. The sign-in stays on
    the phone.
  - Both apps offer it when Reddit refuses a post. Allow mature content in
    your Reddit settings.
- **YouTube Mix links.** A song opened inside a Mix (`&list=RD...`)
  downloads alone; a **Download the Mix** button gets the whole Mix.
- **SponsorBlock.** Sponsor and intro segments can be cut out of YouTube
  videos (off by default; Windows: the switch on the options card; Android:
  Settings). Trimmed downloads are not cut.

**Windows:**
- A Windows notification and a taskbar flash when downloads finish while
  Orbida is in the background.
- **Add to Firefox** also finds Zen, LibreWolf, Floorp and Waterfox.

## New in 1.2.1

**Windows:**
- **Firefox add-on that stays.** The extension is now signed by Mozilla, so
  Firefox keeps it after it closes (Firefox 140 or newer). In Settings ›
  Browser extension click **Add to Firefox**, then **Add** in Firefox. The
  `.xpi` above can also be dragged into a Firefox window.

**Android:** no changes.

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

**Install:** run `Orbida-Setup-1.2.4.exe`. It installs for your user only,
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

`SHA256SUMS.txt` lists the checksums of all three files. `build-info.json` records
the exact source commit and versions of the Windows build.
