import json, re, urllib.parse, urllib.request, urllib.error
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
      "Accept-Language": "en"}
def get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}"
            if "token" in k.lower() or k in ("totalCount", "total", "trackCount"):
                print("PROBE key", p, "=", str(v)[:60])
            walk(v, p)
    elif isinstance(node, list) and node:
        walk(node[0], path + "[0]")
for pid in ["37i9dQZF1DX5Ejj0EkURtP", "37i9dQZF1DWXRqgorJj26U"]:
    st, html = get(f"https://open.spotify.com/embed/playlist/{pid}")
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    data = json.loads(m.group(1))
    ent = data["props"]["pageProps"]["state"]["data"]["entity"]
    print("PROBE", pid, "embed tracks", len(ent.get("trackList") or []), "entity keys", sorted(ent))
    walk(data)
    token = None
    def find(n):
        global token
        if isinstance(n, dict):
            for k, v in n.items():
                if k == "accessToken" and isinstance(v, str): token = v
                find(v)
        elif isinstance(n, list):
            for v in n: find(v)
    find(data)
    print("PROBE token found:", bool(token))
    if token:
        st, body = get(f"https://api.spotify.com/v1/playlists/{pid}/tracks?offset=100&limit=100&fields=total,next,items(track(name,artists(name),duration_ms))",
                       {"Authorization": "Bearer " + token})
        print("PROBE webapi", st, body[:300])
        st, body = get(f"https://api.spotify.com/v1/playlists/{pid}?fields=name,tracks.total", {"Authorization": "Bearer " + token})
        print("PROBE webapi meta", st, body[:200])
        st, body = get("https://api-partner.spotify.com/pathfinder/v1/query?operationName=fetchPlaylist&variables="
                       + urllib.parse.quote(json.dumps({"uri": f"spotify:playlist:{pid}", "offset": 100, "limit": 100})),
                       {"Authorization": "Bearer " + token})
        print("PROBE pathfinder", st, body[:200])
    st, page = get(f"https://open.spotify.com/playlist/{pid}")
    print("PROBE page", st, len(page), "song metas", len(re.findall(r'music:song"', page)), "token in page", "accessToken" in page)
