#!/usr/bin/env bash
# Build FFmpeg, ffprobe and QuickJS for Android with the NDK.
#
#   android/native/build_tools.sh <out-dir> [abi ...]     (default abi: arm64-v8a)
#
# Writes <out-dir>/<abi>/lib*.so: libffmpeg.so, libffprobe.so and libqjs.so
# are ordinary executables named like libraries, so the APK can carry them as
# native libraries (see android/recipes/udtools); FFmpeg's own libraries
# (libavcodec.so, ...) sit next to them. Building FFmpeg shared lets ffmpeg
# and ffprobe share one copy of that code, which keeps the APK small; the
# app points LD_LIBRARY_PATH at the folder.
#
# FFmpeg is built without GPL parts (LGPL 3 because of mbedTLS). LAME adds
# the MP3 encoder. mbedTLS gives FFmpeg HTTPS, which trimming needs: yt-dlp
# then lets FFmpeg read only the wanted part of the video from the server.
# ffmpeg-mbedtls-cafile.patch makes it check certificates against
# $SSL_CERT_FILE, which the app points at certifi's bundle.
#
# Needs: ANDROID_NDK_ROOT (or ANDROID_NDK_LATEST_HOME), curl, make, cmake.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(mkdir -p "${1:?usage: build_tools.sh <out-dir> [abi ...]}" && cd "$1" && pwd)
shift
ABIS=("${@:-arm64-v8a}")

# Pinned sources and their SHA-256. Change a version and its hash together.
FFMPEG_VERSION=7.1.1
FFMPEG_SHA256=733984395e0dbbe5c046abda2dc49a5544e7e0e1e2366bba849222ae9e3a03b1
LAME_VERSION=3.100
LAME_SHA256=ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e
QJS_VERSION=v0.17.0
QJS_SHA256=559bc4c420475e55c7ab4510adbc562f55d7524d75e8e89d79ce4bb02f5687d9
MBEDTLS_VERSION=3.6.4
MBEDTLS_SHA256=ec35b18a6c593cf98c3e30db8b98ff93e8940a8c4e690e66b41dfc011d678110
API=${ANDROID_API:-24}

NDK=${ANDROID_NDK_ROOT:-${ANDROID_NDK_LATEST_HOME:-}}
[ -d "$NDK" ] || { echo "Set ANDROID_NDK_ROOT to an Android NDK" >&2; exit 1; }
TC="$NDK/toolchains/llvm/prebuilt/linux-x86_64"
JOBS=$(nproc)
WORK=${WORK_DIR:-$(mktemp -d)}
mkdir -p "$WORK/src"

echo "FFmpeg $FFMPEG_VERSION, LAME $LAME_VERSION, mbedTLS $MBEDTLS_VERSION, QuickJS-ng $QJS_VERSION, API $API"

quiet() {  # run a noisy command; show the end of its output only if it fails
  local log; log=$(mktemp)
  "$@" >"$log" 2>&1 || { tail -n 80 "$log"; echo "Failed: $*" >&2; exit 1; }
}

fetch() {  # fetch <url> <file> <sha256>
  [ -f "$WORK/src/$2" ] || curl -fsSL --retry 4 -o "$WORK/src/$2" "$1"
  echo "$3  $WORK/src/$2" | sha256sum -c -
}

fetch "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" "ffmpeg-$FFMPEG_VERSION.tar.xz" "$FFMPEG_SHA256"
fetch "https://deb.debian.org/debian/pool/main/l/lame/lame_$LAME_VERSION.orig.tar.gz" "lame-$LAME_VERSION.tar.gz" "$LAME_SHA256"
fetch "https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-$MBEDTLS_VERSION/mbedtls-$MBEDTLS_VERSION.tar.bz2" \
  "mbedtls-$MBEDTLS_VERSION.tar.bz2" "$MBEDTLS_SHA256"
fetch "https://github.com/quickjs-ng/quickjs/archive/refs/tags/$QJS_VERSION.tar.gz" "quickjs-$QJS_VERSION.tar.gz" "$QJS_SHA256"

for ABI in "${ABIS[@]}"; do
  case "$ABI" in
    arm64-v8a) TRIPLE=aarch64-linux-android; FF_ARCH=aarch64; FF_EXTRA=() ;;
    # x86_64 only runs on the CI emulator. Without NASM, and with clang's
    # inline assembly, FFmpeg's x86 decoders fail on Android, so it gets no
    # assembly at all there.
    x86_64)    TRIPLE=x86_64-linux-android;  FF_ARCH=x86_64;  FF_EXTRA=(--disable-asm) ;;
    *) echo "Unsupported ABI $ABI" >&2; exit 1 ;;
  esac
  CC="$TC/bin/$TRIPLE$API-clang"
  B="$WORK/build-$ABI"
  PREFIX="$B/prefix"
  rm -rf "$B"; mkdir -p "$B" "$PREFIX" "$OUT/$ABI"
  echo "::group::LAME $LAME_VERSION ($ABI)"
  tar -xzf "$WORK/src/lame-$LAME_VERSION.tar.gz" -C "$B"
  cd "$B/lame-$LAME_VERSION"
  quiet env CC="$CC" AR="$TC/bin/llvm-ar" RANLIB="$TC/bin/llvm-ranlib" CFLAGS="-O2 -fPIC" \
    ./configure --host="$TRIPLE" --prefix="$PREFIX" --enable-static --disable-shared \
      --disable-frontend --disable-decoder --disable-gtktest
  quiet make -j"$JOBS"
  quiet make install
  echo "::endgroup::"

  echo "::group::mbedTLS $MBEDTLS_VERSION ($ABI)"
  tar -xjf "$WORK/src/mbedtls-$MBEDTLS_VERSION.tar.bz2" -C "$B"
  quiet cmake -S "$B/mbedtls-$MBEDTLS_VERSION" -B "$B/mbedtls" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$API" -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DENABLE_TESTING=OFF -DENABLE_PROGRAMS=OFF \
    -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON
  quiet cmake --build "$B/mbedtls" -j"$JOBS"
  quiet cmake --install "$B/mbedtls"
  echo "::endgroup::"

  echo "::group::FFmpeg $FFMPEG_VERSION ($ABI)"
  tar -xJf "$WORK/src/ffmpeg-$FFMPEG_VERSION.tar.xz" -C "$B"
  cd "$B/ffmpeg-$FFMPEG_VERSION"
  patch -p1 < "$HERE/ffmpeg-mbedtls-cafile.patch"
  quiet ./configure --prefix="$PREFIX" --target-os=android --arch="$FF_ARCH" --enable-cross-compile \
      --cc="$CC" --cxx="$TC/bin/$TRIPLE$API-clang++" --ar="$TC/bin/llvm-ar" --nm="$TC/bin/llvm-nm" \
      --ranlib="$TC/bin/llvm-ranlib" --strip="$TC/bin/llvm-strip" --pkg-config=false \
      --enable-pic --enable-shared --disable-static --disable-doc --disable-ffplay --disable-debug \
      --disable-autodetect --enable-zlib --enable-libmp3lame --enable-version3 --enable-mbedtls \
      --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib" "${FF_EXTRA[@]}"
  quiet make -j"$JOBS"
  quiet make install
  cp "$PREFIX/bin/ffmpeg" "$OUT/$ABI/libffmpeg.so"
  cp "$PREFIX/bin/ffprobe" "$OUT/$ABI/libffprobe.so"
  # On Android FFmpeg names its libraries without a version (libavcodec.so),
  # so the names the programs ask for are the files the APK carries.
  for lib in avcodec avdevice avfilter avformat avutil swresample swscale; do
    cp -L "$PREFIX/lib/lib$lib.so" "$OUT/$ABI/"
  done
  echo "::endgroup::"

  echo "::group::QuickJS-ng $QJS_VERSION ($ABI)"
  tar -xzf "$WORK/src/quickjs-$QJS_VERSION.tar.gz" -C "$B"
  QJS_SRC=$(find "$B" -maxdepth 1 -type d -name 'quickjs-*' | head -1)
  quiet cmake -S "$QJS_SRC" -B "$B/qjs" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$API"
  quiet cmake --build "$B/qjs" --target qjs_exe -j"$JOBS"
  cp "$B/qjs/qjs" "$OUT/$ABI/libqjs.so"
  echo "::endgroup::"

  "$TC/bin/llvm-strip" --strip-unneeded "$OUT/$ABI"/*.so
  file "$OUT/$ABI"/*.so || true
  ls -l "$OUT/$ABI"
done
