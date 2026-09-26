"""Temporary probe 2: bot-check pass rates, with and without an anonymous browser session."""
import sys
import time

import yt_dlp
from yt_dlp.networking import Request

VIDEOS = ["jNQXAC9IVRw", "dQw4w9WgXcQ", "9bZkp7q19f0", "kJQP7kiw5Fk", "OPf0YbXqDm0",
          "JGwWNGJdvx8", "RgKAFK5djSk", "fJ9rUzIMcZQ"]


class Log:
    def __init__(self):
        self.lines = []

    def debug(self, msg):
        self.lines.append(msg)

    info = warning = error = debug


def probe(mode, vid, extra):
    log = Log()
    opts = {"quiet": True, "logger": log, "skip_download": True, "verbose": True,
            "js_runtimes": {"deno": {}}, "remote_components": ["ejs:npm"], **extra}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info("https://www.youtube.com/watch?v=" + vid, download=False)
            fmts = info.get("requested_formats") or [info]
            media = []
            for f in fmts:
                try:
                    with ydl.urlopen(Request(f["url"], headers={**(f.get("http_headers") or {}), "Range": "bytes=0-65535"})) as r:
                        media.append(str(r.status))
                except Exception as e:
                    media.append("x" + str(getattr(e, "status", "") or type(e).__name__))
            ok = all(m == "206" or m == "200" for m in media)
            result = "%s %s media=%s" % ("OK  " if ok else "MEDIA", info.get("format_id"), ",".join(media))
    except Exception as e:
        msg = str(e)
        result = "BOT " if "not a bot" in msg else "FAIL " + msg.splitlines()[0][:120]
    print("%-12s %s %s" % (mode, vid, result), flush=True)
    return result.startswith("OK")


def main():
    from yt_dlp.networking.impersonate import ImpersonateTarget
    modes = {
        "plain": {},
        "impersonate": {"impersonate": ImpersonateTarget("chrome")},
    }
    if len(sys.argv) > 1:
        modes["cookies"] = {"cookiefile": sys.argv[1]}
        modes["cookies+imp"] = {"cookiefile": sys.argv[1], "impersonate": ImpersonateTarget("chrome")}
    score = {m: 0 for m in modes}
    for rnd in range(2):
        for vid in VIDEOS:
            for mode, extra in modes.items():
                score[mode] += probe(mode, vid, extra)
                time.sleep(1)
    total = 2 * len(VIDEOS)
    for mode, n in score.items():
        print("SCORE %-12s %d/%d" % (mode, n, total))


if __name__ == "__main__":
    main()
