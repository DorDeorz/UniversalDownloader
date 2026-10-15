import json, re, urllib.parse, urllib.request, urllib.error
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
      "Accept-Language": "en"}
def req(url, headers=None, data=None):
    r = urllib.request.Request(url, headers={**UA, **(headers or {})}, data=data)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
PID = "37i9dQZF1DWXRqgorJj26U"
st, html = req(f"https://open.spotify.com/embed/playlist/{PID}")
data = json.loads(re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S).group(1))
token = data["props"]["pageProps"]["state"]["settings"]["session"]["accessToken"]
st, page = req(f"https://open.spotify.com/playlist/{PID}")
scripts = re.findall(r'<script[^>]+src="([^"]+\.js)"', page)
print("PROBE scripts", scripts)
hashes = {}
for src in scripts:
    st, js = req(src)
    for m in re.finditer(r'"(fetchPlaylist\w*|queryPlaylist\w*)","query","([0-9a-f]{64})"', js):
        hashes[m.group(1)] = m.group(2)
    if "fetchPlaylist" in js and not hashes:
        i = js.index("fetchPlaylist"); print("PROBE ctx", src, js[i-80:i+160])
    # chunk map: look for other chunk files
    for m in re.finditer(r'fetchPlaylist', js):
        pass
print("PROBE hashes", hashes)
for name, h in hashes.items():
    body = json.dumps({"variables": {"uri": f"spotify:playlist:{PID}", "offset": 100, "limit": 100,
                                     "enableWatchFeedEntrypoint": False},
                       "operationName": name,
                       "extensions": {"persistedQuery": {"version": 1, "sha256Hash": h}}}).encode()
    for ver in ("v2",):
        st, out = req(f"https://api-partner.spotify.com/pathfinder/{ver}/query",
                      {"Authorization": "Bearer " + token, "Content-Type": "application/json;charset=UTF-8",
                       "app-platform": "WebPlayer"}, data=body)
        print("PROBE pathfinder", ver, name, st, out[:400])
        try:
            d = json.loads(out)
            c = d["data"]["playlistV2"]["content"]
            print("PROBE total", c.get("totalCount"), "got", len(c["items"]))
            it = c["items"][0]["itemV2"]["data"]
            print("PROBE first", json.dumps(it)[:600])
        except Exception as e:
            print("PROBE parse", e)
    q = urllib.parse.urlencode({"operationName": name,
        "variables": json.dumps({"uri": f"spotify:playlist:{PID}", "offset": 100, "limit": 100}),
        "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": h}})})
    st, out = req("https://api-partner.spotify.com/pathfinder/v1/query?" + q, {"Authorization": "Bearer " + token, "app-platform": "WebPlayer"})
    print("PROBE pathfinder v1 GET", name, st, out[:200])
