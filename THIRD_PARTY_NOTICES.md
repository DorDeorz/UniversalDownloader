# Third-party software

UniversalDownloader bundles or depends on the following software. Each is
distributed under its own license; the full texts are available from the
linked projects.

| Component | Use | License |
|---|---|---|
| [FFmpeg](https://ffmpeg.org/) (`bin/ffmpeg.exe`, `bin/ffprobe.exe`) | Merging, conversion, trimming | GPL v3 or LGPL v2.1, depending on the build ([legal](https://ffmpeg.org/legal.html)) |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Media extraction and download | Unlicense |
| [Deno](https://deno.com/) (`bin/deno.exe`, installer only) | Runs YouTube's JavaScript challenges for yt-dlp | MIT |
| [yt-dlp-ejs](https://github.com/yt-dlp/ejs) | YouTube JavaScript challenge solver scripts | Unlicense / MIT (see project) |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) | User interface | MIT |
| [darkdetect](https://github.com/albertosottile/darkdetect) | Dark mode detection | BSD-3-Clause |
| [mutagen](https://github.com/quodlibet/mutagen) | Cover art in opus/flac files | GPL v2 or later |
| [requests](https://github.com/psf/requests), [urllib3](https://github.com/urllib3/urllib3), [idna](https://github.com/kjd/idna), [charset-normalizer](https://github.com/jawah/charset_normalizer) | HTTP | Apache-2.0 / MIT / BSD-3-Clause / MIT |
| [certifi](https://github.com/certifi/python-certifi) | CA certificates for HTTPS verification | MPL-2.0 |
| [brotli](https://github.com/google/brotli) | HTTP compression | MIT |
| [websockets](https://github.com/python-websockets/websockets) | Live/websocket downloads | BSD-3-Clause |
| [curl_cffi](https://github.com/lexiforest/curl_cffi) with [curl-impersonate](https://github.com/lexiforest/curl-impersonate), [cffi](https://github.com/python-cffi/cffi), [pycparser](https://github.com/eliben/pycparser) | Browser-like requests (needed for TikTok) | MIT / MIT (bundles curl and BoringSSL under their own licenses) / MIT-0 / BSD-3-Clause |
| [pycryptodomex](https://github.com/Legrandin/pycryptodome) | Decrypting some streams | BSD-2-Clause / Public Domain |
| [Python](https://www.python.org/) (embedded by PyInstaller) | Runtime | PSF License |

## FFmpeg

The FFmpeg binaries in `bin/` are distributed unmodified. If the build you
ship is a GPL build, the whole distributed package must meet the GPL's
conditions, including offering the corresponding FFmpeg source code. Record
the exact FFmpeg build (source URL and version, shown in the app log at
startup) with each release.
