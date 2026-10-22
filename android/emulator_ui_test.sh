#!/usr/bin/env bash
# Start the app on a running emulator the way a person would, tap through
# its tabs and buttons with real touch events, send it to the background and
# back, and fail if the process dies or Python reports an error on the way.
#
# Widgets are tapped by name, not by fixed coordinates: started with the
# selftest_ui extra, the app logs where each named widget is on the screen
# ("UDSELFTEST where screen=home btn_paste=384,32 ..."; main._report_where),
# so the taps follow the layout on any screen size, Android version and
# language.
#
#   android/emulator_ui_test.sh <apk>
# UD_SMOKE=1 runs the taps only (the other Android versions of the CI matrix).
set -uo pipefail

APK=$1
PKG=io.github.dordeorz.orbida
ACTIVITY="$PKG/org.kivy.android.PythonActivity"

adb uninstall "$PKG" >/dev/null 2>&1  # each CI job signs with its own debug key
adb install -g "$APK" || exit 1
adb shell am force-stop "$PKG"
adb logcat -c
adb shell am start -n "$ACTIVITY" --es selftest_ui 1
# The first start unpacks the app and checks FFmpeg; wait for that to finish.
for _ in $(seq 1 36); do
  adb logcat -d 2>/dev/null | grep -a -q -E "UDSELFTEST where|UDCRASH" && break
  sleep 5
done
sleep 3

size=$(adb shell wm size | tr -d '\r' | awk '{print $3}' | tail -n 1)
W=${size%x*}
H=${size#*x}
echo "Screen ${W}x${H}, Android $(adb shell getprop ro.build.version.sdk | tr -d '\r')"

status=0
alive() {
  if ! adb shell pidof "$PKG" >/dev/null; then
    echo "FAIL: the app closed after: $1"
    status=1
    return 1
  fi
  echo "ok: $1"
}

where_of() {  # name -> "x y" from the app's latest report, or nothing
  adb logcat -d 2>/dev/null | grep -a -o "UDSELFTEST where .*" | tail -n 1 | tr -d '\r' | tr ' ' '\n' \
    | grep -a "^$1=" | head -n 1 | cut -d= -f2 | tr ',' ' '
}

scroll() {  # down|up: move the page's content by a third of the screen
  if [ "$1" = down ]; then
    adb shell input swipe $(( W / 2 )) $(( H * 6 / 10 )) $(( W / 2 )) $(( H * 3 / 10 )) 400
  else
    adb shell input swipe $(( W / 2 )) $(( H * 3 / 10 )) $(( W / 2 )) $(( H * 6 / 10 )) 400
  fi
}

tap_id() {  # name: wait until the app reports the widget on screen, then tap it
  # A small phone screen may have the widget scrolled out of view: look
  # further down the page, then back up.
  local xy="" way
  for way in none none none down down up up up up; do
    [ "$way" != none ] && scroll "$way"
    for _ in 1 2 3; do
      xy=$(where_of "$1")
      [ -n "$xy" ] && break 2
      sleep 1
    done
  done
  if [ -z "$xy" ]; then
    echo "FAIL: no widget named $1 on the screen"
    adb logcat -d 2>/dev/null | grep -a -o "UDSELFTEST where .*" | tail -n 1
    status=1
    return 1
  fi
  # shellcheck disable=SC2086
  adb shell input tap $xy
  sleep 3
  alive "tap $1 at $xy"
}

alive "start" &&
  tap_id btn_paste &&
  tap_id btn_clear &&
  tap_id btn_options &&                    # More options opens
  tap_id btn_details &&                    # the activity log opens
  tap_id nav.history &&
  tap_id history_search &&
  { adb shell input keyevent KEYCODE_BACK; sleep 2; alive "Back closes the keyboard"; } &&
  tap_id nav.settings &&
  tap_id settings.theme &&
  { adb shell input keyevent KEYCODE_BACK; sleep 2; alive "Back closes the choice dialog"; } &&
  tap_id settings.theme &&
  tap_id choice.light &&                   # picks it; the row updates in place
  { adb shell input swipe $(( W / 2 )) $(( H * 3 / 4 )) $(( W / 2 )) $(( H / 4 )) 300; sleep 2; alive "scroll Settings"; } &&
  tap_id nav.home &&
  tap_id url &&
  { adb shell input keyevent KEYCODE_BACK; sleep 2; alive "Back closes the keyboard"; } &&
  { adb shell input keyevent KEYCODE_HOME; sleep 3; adb shell am start -n "$ACTIVITY"; sleep 5; alive "background and back"; } &&
  { adb shell settings put system user_rotation 1; adb shell settings put system accelerometer_rotation 0; sleep 4;
    alive "landscape"; } &&
  tap_id nav.settings &&
  { adb shell settings put system user_rotation 0; sleep 4; alive "portrait again"; }

echo "----- app log -----"
adb logcat -d 2>/dev/null | grep -a -E "python|UDCRASH|AndroidRuntime|libc|DEBUG|SDL" | tail -n 300
if grep -a -q "UDCRASH" <<<"$(adb logcat -d 2>/dev/null)"; then
  echo "FAIL: Python reported an error (UDCRASH above)"
  status=1
fi

if [ -n "${UD_SMOKE:-}" ]; then
  adb shell am force-stop "$PKG"
  exit $status
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
  if grep -a -q "UDSELFTEST login closed site=YouTube signed_in=False" <<<"$login" && ! grep -a -q UDCRASH <<<"$login"; then
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

# Updates (self_update.py, UpdateInstaller.java), last because the update
# replaces the app and ends it: with UD_UPDATE_RELEASES set to
# a releases list that offers this same APK as a newer version, the app must
# find it, download it and hand it to Android's installer; the test then taps
# Update on Android's screen and checks that the package was replaced.
if [ $status -eq 0 ] && [ -n "${UD_UPDATE_RELEASES:-}" ]; then
  adb shell am force-stop "$PKG"
  # What a person allows once on the phone: installing apps from Orbida.
  adb shell appops set "$PKG" REQUEST_INSTALL_PACKAGES allow
  before=$(adb shell dumpsys package "$PKG" | tr -d '\r' | grep -m1 lastUpdateTime)
  adb logcat -c
  adb shell am start -n "$ACTIVITY" --es selftest_update "$UD_UPDATE_RELEASES"
  for _ in $(seq 1 36); do
    adb logcat -d 2>/dev/null | grep -a -q -E "UDSELFTEST update status=(confirm|failed)|UDSELFTEST update (found|downloaded) .*error=[^N]|UDCRASH" && break
    sleep 5
  done
  sleep 3
  update=$(adb logcat -d 2>/dev/null | grep -a -E "UDSELFTEST update|UDCRASH")
  echo "$update"
  tapped=""
  if grep -a -q "UDSELFTEST update status=confirm" <<<"$update"; then
    # Android's "Do you want to update this app?" screen: tap its Update button.
    for _ in $(seq 1 10); do
      adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1
      xy=$(adb shell cat /sdcard/ui.xml 2>/dev/null | python3 -c '
import re, sys
for node in re.findall(r"<node [^>]*>", sys.stdin.read()):
    text = re.search(r"text=\"([^\"]*)\"", node).group(1).strip().lower()
    if text in ("update", "install") and "clickable=\"true\"" in node:
        x1, y1, x2, y2 = map(int, re.search(r"bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"", node).groups())
        print((x1 + x2) // 2, (y1 + y2) // 2)
        break
')
      if [ -n "$xy" ]; then
        adb shell input tap $xy
        tapped=yes
        break
      fi
      sleep 3
    done
  fi
  after="$before"
  if [ -n "$tapped" ]; then
    for _ in $(seq 1 24); do
      after=$(adb shell dumpsys package "$PKG" | tr -d '\r' | grep -m1 lastUpdateTime)
      [ "$after" != "$before" ] && break
      sleep 5
    done
  fi
  echo "before: $before"
  echo "after:  $after"
  if grep -a -q UDCRASH <<<"$update"; then
    echo "FAIL: Python reported an error while updating"
    status=1
  elif [ "$after" != "$before" ]; then
    echo "ok: the app found, downloaded and installed an update"
  else
    adb logcat -d 2>/dev/null | grep -a -E " python |PackageInstaller|AndroidRuntime" | tail -n 80
    echo "FAIL: the update was not installed"
    status=1
  fi
fi

adb shell am force-stop "$PKG"
exit $status
