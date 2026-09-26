**Orbida 1.0.0** is the first stable version. This release holds both apps:

- **Windows:** `Orbida-Setup-1.0.0.exe`, for Windows 10 or 11 (64-bit).
- **Android:** `Orbida-1.0.0.apk`, for 64-bit ARM phones with Android 7 or newer.

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

**Install:** run `Orbida-Setup-1.0.0.exe`. It installs for your user only,
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
