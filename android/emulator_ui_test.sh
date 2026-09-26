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
  tap "Theme row" $(( W / 2 )) $(dp 200) &&
  tap "Download tab" $(( W / 6 )) "$nav_y" &&
  tap "Link field" $(( W / 2 )) $(dp 140) &&
  { adb shell input keyevent KEYCODE_HOME; sleep 3; adb shell am start -n "$ACTIVITY"; sleep 5; alive "background and back"; }

echo "----- app log -----"
adb logcat -d 2>/dev/null | grep -a -E "python|UDCRASH|AndroidRuntime|libc|DEBUG|SDL" | tail -n 300
if adb logcat -d 2>/dev/null | grep -a -q "UDCRASH"; then
  echo "FAIL: Python reported an error (UDCRASH above)"
  status=1
fi

# A Java crash must come back as a report on the next start: have Android
# crash the app's main thread (am crash) and start it again.
if [ $status -eq 0 ]; then
  adb logcat -c
  adb shell am crash "$PKG"
  sleep 5
  adb shell pidof "$PKG" >/dev/null && echo "note: the app is still running after am crash"
  adb shell am start -n "$ACTIVITY"
  for _ in $(seq 1 24); do
    adb logcat -d 2>/dev/null | grep -a -q "UDCRASH previous run" && break
    sleep 5
  done
  sleep 3  # the report reaches the log a line at a time
  if adb logcat -d 2>/dev/null | grep -a -A40 "UDCRASH previous run" | grep -a -q -E "FATAL EXCEPTION|CrashedByAdb"; then
    echo "ok: crash report after a Java crash"
  else
    echo "FAIL: no crash report after a Java crash"
    status=1
  fi
  adb logcat -d 2>/dev/null | grep -a -A40 "UDCRASH previous run" | head -n 60
fi

adb shell am force-stop "$PKG"
exit $status
