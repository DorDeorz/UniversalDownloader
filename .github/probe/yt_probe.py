"""Temporary probe: which yt-dlp setups pass YouTube's bot check from this runner."""
import json
import sys
import time
import urllib.request

import yt_dlp

VIDEOS = ["https://www.youtube.com/watch?v=jNQXAC9IVRw", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
CLIENTS = ["default", "web", "web_safari", "web_embedded", "mweb", "tv", "tv_downgraded", "tv_simply",
           "android", "android_vr", "ios", "visionos"]


class Quiet:
    def __init__(self):
        self.lines = []

    def debug(self, msg):
        if "PO Token" in msg or "pot" in msg.lower() or "JS" in msg or "runtime" in msg.lower():
            self.lines.append(msg)

    info = debug

    def warning(self, msg):
        self.lines.append("W " + msg)

    def error(self, msg):
        self.lines.append("E " + msg)


def probe(label, url, extra):
    log = Quiet()
    opts = {"quiet": True, "logger": log, "skip_download": True, "verbose": True,
            "js_runtimes": {"deno": {}}, "remote_components": ["ejs:npm"], **extra}
    start = time.time()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            fmt = next((f for f in info.get("requested_formats") or [info] if f.get("url")), None)
            media = "?"
            if fmt:
                req = urllib.request.Request(fmt["url"], headers={**(fmt.get("http_headers") or {}), "Range": "bytes=0-65535"})
                try:
                    with urllib.request.urlopen(req, timeout=20) as r:
                        media = "media %d" % r.status
                except Exception as e:
                    media = "media fail %s" % e
            result = "OK %s formats=%d %s" % (info.get("format_id"), len(info.get("formats") or []), media)
    except Exception as e:
        result = "FAIL " + str(e).splitlines()[0][:160]
    print("%-28s %-12s %5.1fs %s" % (label, url[-11:], time.time() - start, result), flush=True)
    for line in log.lines[-6:]:
        if "bot" in line or "PO" in line or "E " in line[:2]:
            print("      " + line[:200])


def main(mode):
    for url in VIDEOS:
        for client in CLIENTS:
            extra = {}
            if client != "default":
                extra["extractor_args"] = {"youtube": {"player_client": [client]}}
            if mode == "impersonate":
                from yt_dlp.networking.impersonate import ImpersonateTarget
                extra["impersonate"] = ImpersonateTarget("chrome")
            probe("%s/%s" % (mode, client), url, extra)


if __name__ == "__main__":
    main(sys.argv[1])
