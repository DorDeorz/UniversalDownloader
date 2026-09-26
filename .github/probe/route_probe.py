"""Temporary probe 4: yt-dlp with its YouTube requests routed through a real browser (browser_route)."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "android", "app"))

import yt_dlp  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from yt_dlp.networking import Request  # noqa: E402

import browser_route  # noqa: E402

VIDEOS = ["dQw4w9WgXcQ"] * 4
BRIDGE = None


class PlaywrightBridge:
    def __init__(self, page):
        self.page = page

    def fetch(self, method, url, headers, body, timeout):
        return self.page.evaluate("(a) => __udFetch(...a)", ["1", method, url, headers, body])


def probe(mode, vid):
    lines = []

    class Log:
        def debug(self, msg):
            lines.append(msg)
        info = warning = error = debug

    before = browser_route.request_count()
    opts = {"quiet": True, "logger": Log(), "skip_download": True, "verbose": True,
            "js_runtimes": {"deno": {}}, "remote_components": ["ejs:npm"]}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info("https://www.youtube.com/watch?v=" + vid, download=False)
            media = []
            fmts = info.get("requested_formats") or [info]
            import urllib.parse as up
            q = up.parse_qs(up.urlsplit(fmts[0]["url"]).query)
            media.append("c=%s pot=%s" % (q.get("c"), "pot" in q))
            if mode == "browser":
                r = BRIDGE.fetch("GET", fmts[0]["url"], {"Range": "bytes=0-65535"}, None, 30)
                media.append("viabrowser=%s" % r[0])
            for f in fmts:
                try:
                    with ydl.urlopen(Request(f["url"], headers={**(f.get("http_headers") or {}), "Range": "bytes=0-65535"})) as r:
                        media.append(str(r.status))
                except Exception as e:
                    media.append("x" + str(getattr(e, "status", "") or type(e).__name__))
            result = "OK   %s media=%s" % (info.get("format_id"), ",".join(media))
    except Exception as e:
        msg = str(e)
        result = "BOT " if "not a bot" in msg else "FAIL " + msg.splitlines()[0][:150]
    routed = browser_route.request_count() - before
    print("%-8s %s %s (browser requests: %d)" % (mode, vid, result, routed), flush=True)
    if mode == "browser":
        for line in lines:
            if "UDBrowser" in line or "WARNING" in line or "ERROR" in line or "Downloading" in line or "player API" in line:
                print("       " + line[:200])


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(locale="en-US").new_page()
    page.goto(browser_route.HOME_URL, wait_until="load")
    page.wait_for_timeout(5000)
    print("page:", page.url, flush=True)
    page.evaluate(browser_route.FETCH_SCRIPT)
    bridge = BRIDGE = PlaywrightBridge(page)
    for vid in VIDEOS:
        browser_route.disable()
        probe("plain", vid)
        browser_route.enable(bridge)
        probe("browser", vid)
        time.sleep(1)
    browser.close()
