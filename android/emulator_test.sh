#!/usr/bin/env bash
# Install the APK on a running emulator and let the app download <url>
# three times (Video + Audio, MP3, then seconds 1-3 as a trimmed MP4) through
# its self-test hook. Passes when all jobs succeed, the files exist, QuickJS
# ran and FFmpeg has HTTPS.
#
#   android/emulator_test.sh <apk> <url>
set -uo pipefail

APK=$1
URL=$2
PKG=io.github.dordeorz.universaldownloader
TIMEOUT=${TIMEOUT:-900}

adb install -r -g "$APK" || exit 1
adb logcat -c
adb shell am start -n "$PKG/org.kivy.android.PythonActivity" --es selftest_url "$URL"

log() { adb logcat -d 2>/dev/null | grep -a -E "UDSELFTEST|QuickJS|FFmpeg|yt-dlp|Traceback|Error" ; }

start=$(date +%s)
while true; do
  done_jobs=$(adb logcat -d 2>/dev/null | grep -a -c "UDSELFTEST job done")
  [ "$done_jobs" -ge 3 ] && break
  if adb logcat -d 2>/dev/null | grep -a -q -E "UDSELFTEST (analysis failed|tools ok=False)"; then break; fi
  if [ $(( $(date +%s) - start )) -gt "$TIMEOUT" ]; then echo "Timed out"; break; fi
  sleep 10
done

echo "----- app log -----"
log
echo "----- files -----"
adb shell ls -lR /sdcard/Download/UniversalDownloader 2>&1

status=0
[ "$(adb logcat -d | grep -a -c 'UDSELFTEST job done all_ok=True')" -eq 3 ] || { echo "FAIL: not all three downloads succeeded"; status=1; }
adb logcat -d | grep -a -q "UDSELFTEST tools ok=True https=True" || { echo "FAIL: FFmpeg missing or without HTTPS"; status=1; }
adb logcat -d | grep -a -q "QuickJS ready" || { echo "FAIL: QuickJS did not run"; status=1; }
[ "$(adb shell ls /sdcard/Download/UniversalDownloader/Other | grep -c '\.mp4')" -ge 2 ] || { echo "FAIL: MP4 and trimmed MP4 not saved"; status=1; }
adb shell ls /sdcard/Download/UniversalDownloader/Other | grep -q '\.mp3$' || { echo "FAIL: no MP3 saved"; status=1; }
if [ $status -ne 0 ]; then
  echo "----- full log (python) -----"
  adb logcat -d | grep -a -i python | tail -n 300
fi
exit $status
