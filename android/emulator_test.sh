#!/usr/bin/env bash
# Install the APK on a running emulator and let the app download <url>
# twice (Video + Audio, then MP3) through its self-test hook. Passes when
# both jobs succeed, the files exist and QuickJS ran.
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
  [ "$done_jobs" -ge 2 ] && break
  if adb logcat -d 2>/dev/null | grep -a -q -E "UDSELFTEST (analysis failed|tools ok=False)"; then break; fi
  if [ $(( $(date +%s) - start )) -gt "$TIMEOUT" ]; then echo "Timed out"; break; fi
  sleep 10
done

echo "----- app log -----"
log
echo "----- files -----"
adb shell ls -lR /sdcard/Download/UniversalDownloader 2>&1

status=0
[ "$(adb logcat -d | grep -a -c 'UDSELFTEST job done all_ok=True')" -eq 2 ] || { echo "FAIL: downloads did not both succeed"; status=1; }
adb logcat -d | grep -a -q "QuickJS ready" || { echo "FAIL: QuickJS did not run"; status=1; }
adb shell ls /sdcard/Download/UniversalDownloader/Other | grep -q '\.mp4$' || { echo "FAIL: no MP4 saved"; status=1; }
adb shell ls /sdcard/Download/UniversalDownloader/Other | grep -q '\.mp3$' || { echo "FAIL: no MP3 saved"; status=1; }
if [ $status -ne 0 ]; then
  echo "----- full log (python) -----"
  adb logcat -d | grep -a -i python | tail -n 300
fi
exit $status
