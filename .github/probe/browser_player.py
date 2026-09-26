"""Temporary probe 3: does a real browser on this machine get playable videos where yt-dlp is bot-checked?"""
import json

from playwright.sync_api import sync_playwright

VIDEOS = ["jNQXAC9IVRw", "dQw4w9WgXcQ", "9bZkp7q19f0", "kJQP7kiw5Fk", "OPf0YbXqDm0",
          "JGwWNGJdvx8", "RgKAFK5djSk", "fJ9rUzIMcZQ"]
MOBILE = ("Mozilla/5.0 (Linux; Android 13; 22111317PG) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/140.0.0.0 Mobile Safari/537.36")

SUMMARY = """(pr) => {
  if (!pr) return 'no player response';
  const ps = pr.playabilityStatus || {};
  const sd = pr.streamingData || {};
  const f = (sd.formats || []).concat(sd.adaptiveFormats || []);
  return [ps.status, (ps.reason || '').slice(0, 60), 'formats=' + f.length,
          'url=' + f.filter(x => x.url).length, 'cipher=' + f.filter(x => x.signatureCipher).length,
          'hls=' + !!sd.hlsManifestUrl, 'sabr=' + !!sd.serverAbrStreamingUrl].join(' ');
}"""

# The page's own innertube request, made again from inside the page with a client of our choosing.
FETCH = """async ([vid, client]) => {
  const cfg = window.ytcfg && ytcfg.data_ || {};
  const ctx = JSON.parse(JSON.stringify(cfg.INNERTUBE_CONTEXT || {}));
  ctx.client = Object.assign(ctx.client || {}, client);
  const r = await fetch('/youtubei/v1/player?prettyPrint=false', {method: 'POST', headers: {'content-type': 'application/json',
      'x-youtube-client-name': String(cfg.INNERTUBE_CONTEXT_CLIENT_NAME || 2), 'x-youtube-client-version': ctx.client.clientVersion,
      'x-goog-visitor-id': ctx.client.visitorData || ''},
    body: JSON.stringify({context: ctx, videoId: vid, contentCheckOk: true, racyCheckOk: true,
      playbackContext: {contentPlaybackContext: {html5Preference: 'HTML5_PREF_WANTS', signatureTimestamp: cfg.STS}}})});
  return await r.json();
}"""

with sync_playwright() as p:
    browser = p.chromium.launch()
    for label, ua, host in (("mobile", MOBILE, "m.youtube.com"), ("desktop", None, "www.youtube.com")):
        context = browser.new_context(user_agent=ua, locale="en-US") if ua else browser.new_context(locale="en-US")
        page = context.new_page()
        for vid in VIDEOS:
            api = []
            page.on("response", lambda r: api.append(r) if "/youtubei/v1/player" in r.url else None)
            try:
                page.goto(f"https://{host}/watch?v={vid}", wait_until="load", timeout=45000)
                page.wait_for_timeout(4000)
                initial = page.evaluate(SUMMARY, page.evaluate("() => window.ytInitialPlayerResponse || null"))
                own = []
                for r in api:
                    try:
                        own.append(page.evaluate(SUMMARY, r.json()))
                    except Exception as e:
                        own.append("unreadable " + type(e).__name__)
                print(f"{label:8} {vid} initial: {initial} | page api: {own[:2]}", flush=True)
                for name, client in (("same", {}),
                                     ("tvhtml5", {"clientName": "TVHTML5", "clientVersion": "7.20250923.13.00"}),
                                     ("ios", {"clientName": "IOS", "clientVersion": "20.10.4"})):
                    try:
                        print(f"{label:8} {vid} fetch {name}: {page.evaluate(SUMMARY, page.evaluate(FETCH, [vid, client]))}",
                              flush=True)
                    except Exception as e:
                        print(f"{label:8} {vid} fetch {name}: error {str(e)[:100]}", flush=True)
            except Exception as e:
                print(f"{label:8} {vid} error {str(e)[:120]}", flush=True)
            page.remove_listener("response", page.listeners("response")[0]) if hasattr(page, "listeners") else None
        context.close()
    browser.close()
