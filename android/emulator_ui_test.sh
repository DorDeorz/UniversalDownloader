#!/usr/bin/env bash
# Start the app on a running emulator the way a person would, tap through
# its tabs and buttons with real touch events, send it to the background and
# back, and fail if the process dies or Python reports an error on the way.
#
#   android/emulator_ui_test.sh <apk>
set -uo pipefail

APK=$1
PKG=io.github.dordeorz.universaldownloader
ACTIVITY="$PKG/org.kivy.android.PythonActivity"

adb uninstall "$PKG" >/dev/null 2>&1  # each CI job signs with its own debug key
adb install -g "$APK" || exit 1
adb shell am force-stop "$PKG"
adb logcat -c
adb shell am start -n "$ACTIVITY"
# The first start unpacks the app and checks FFmpeg; wait for that to finish.
for _ in $(seq 1 36); do
  adb logcat -d 2>/dev/null | grep -a -q -E "UDSELFTEST tools|UDCRASH" && break
  sleep 5
done
sleep 3

size=$(adb shell wm size | tr -d '\r' | awk '{print $3}' | tail -n 1)
W=${size%x*}
H=${size#*x}
density=$(adb shell wm density | tr -d '\r' | awk '{print $3}' | tail -n 1)
dp() { echo $(( $1 * density / 160 )); }
nav_y=$(( H - $(dp 48) - $(dp 40) ))  # middle of the app's navigation bar, above Android's own
echo "Screen ${W}x${H}, density $density"

status=0
alive() {
  if ! adb shell pidof "$PKG" >/dev/null; then
    echo "FAIL: the app closed after: $1"
    status=1
    return 1
  fi
  echo "ok: $1"
}

tap() {  # name x y
  adb shell input tap "$2" "$3"
  sleep 3
  alive "tap $1 at $2,$3"
}

alive "start" &&
  tap "Paste (top bar)" $(( W - $(dp 28) )) $(dp 64) &&
  tap "Clear" $(dp 60) $(dp 200) &&
  tap "History tab" $(( W / 2 )) "$nav_y" &&
  tap "Settings tab" $(( W * 5 / 6 )) "$nav_y" &&
  tap "Theme row" $(( W / 2 )) $(dp 165) &&  # below the status bar and the Appearance heading
  { adb shell input keyevent KEYCODE_BACK; sleep 2; alive "Back closes the choice dialog"; } &&
  tap "Download tab" $(( W / 6 )) "$nav_y" &&
  tap "Link field" $(( W / 2 )) $(dp 140) &&
  { adb shell input keyevent KEYCODE_HOME; sleep 3; adb shell am start -n "$ACTIVITY"; sleep 5; alive "background and back"; }

echo "----- app log -----"
adb logcat -d 2>/dev/null | grep -a -E "python|UDCRASH|AndroidRuntime|libc|DEBUG|SDL" | tail -n 300
if grep -a -q "UDCRASH" <<<"$(adb logcat -d 2>/dev/null)"; then
  echo "FAIL: Python reported an error (UDCRASH above)"
  status=1
fi

# The YouTube sign-in page: a WebView over the app that closes again (the
# selftest_login extra opens it with this page and closes it after 4 s).
if [ $status -eq 0 ]; then
  adb shell am force-stop "$PKG"
  adb logcat -c
  adb shell am start -n "$ACTIVITY" --es selftest_login "about:blank"
  for _ in $(seq 1 24); do
    adb logcat -d 2>/dev/null | grep -a -q -E "UDSELFTEST login closed|UDCRASH" && break
    sleep 5
  done
  login=$(adb logcat -d 2>/dev/null | grep -a -E "UDSELFTEST login|UDCRASH")
  adb logcat -d 2>/dev/null | grep -a -E " python |chromium|WebView|AndroidRuntime" | tail -n 120
  if grep -a -q "UDSELFTEST login closed signed_in=False" <<<"$login" && ! grep -a -q UDCRASH <<<"$login"; then
    alive "YouTube sign-in page opened and closed"
  else
    echo "FAIL: the YouTube sign-in page did not open and close cleanly"
    status=1
  fi
fi

# The browser route (browser_route.py, BrowserFetch.java): analyse a YouTube
# video with yt-dlp's YouTube requests going through a hidden WebView, and
# download it with the PO token the WebView mints. YouTube often answers
# this runner's network with its bot check, even for a real browser; that
# still shows the route worked, as long as requests went through it.
if [ $status -eq 0 ]; then
  adb shell am force-stop "$PKG"
  adb logcat -c
  adb shell am start -n "$ACTIVITY" --es selftest_browser "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  for _ in $(seq 1 60); do
    adb logcat -d 2>/dev/null | grep -a -q -E "UDSELFTEST (job done|analysis failed)|UDCRASH" && break
    sleep 5
  done
  route=$(adb logcat -d 2>/dev/null | grep -a -E "UDSELFTEST|UDCRASH")
  adb logcat -d 2>/dev/null | grep -a -E " python |chromium|AndroidRuntime" | tail -n 150
  echo "$route"
  if grep -a -q UDCRASH <<<"$route"; then
    echo "FAIL: Python reported an error in the browser route"
    status=1
  elif grep -a -q "UDSELFTEST job done all_ok=True" <<<"$route"; then
    alive "YouTube video analysed and downloaded through the browser route"
  elif grep -a -q -E "UDSELFTEST analysis failed: .*not a bot.* browser_requests=[1-9]" <<<"$route"; then
    alive "browser route answered; YouTube bot-checks this runner's network"
  else
    echo "FAIL: the browser route did not work"
    status=1
  fi
fi

# A Java crash must come back as a report on the next start: have Android
# crash the app's main thread (am crash) and start it again.
if [ $status -eq 0 ]; then
  adb logcat -c
  # By process id: with the browser route's WebView running, the package
  # also has a page process, and that one ending no longer closes the app.
  adb shell am crash "$(adb shell pidof "$PKG" | tr -d '\r' | awk '{print $1}')"
  sleep 5
  adb shell pidof "$PKG" >/dev/null && echo "note: the app is still running after am crash"
  adb shell am start -n "$ACTIVITY"
  for _ in $(seq 1 24); do
    adb logcat -d 2>/dev/null | grep -a -q "UDCRASH previous run" && break
    sleep 5
  done
  sleep 3  # the report reaches the log a line at a time
  # Kept in a variable: with pipefail, grep -q ending a pipe early fails it.
  report=$(adb logcat -d 2>/dev/null | grep -a -A40 "UDCRASH previous run")
  echo "$report" | head -n 60
  if grep -a -q -E "FATAL EXCEPTION|CrashedByAdb" <<<"$report"; then
    echo "ok: crash report after a Java crash"
  else
    echo "FAIL: no crash report after a Java crash"
    status=1
  fi
fi

adb shell am force-stop "$PKG"
exit $status
