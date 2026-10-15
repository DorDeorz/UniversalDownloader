import json
import logic
m = logic.DownloadManager()
for url in ["https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b",
            "https://open.spotify.com/album/4yP0hdKOZPNshxUOjY0cZj",
            "https://open.spotify.com/playlist/37i9dQZF1DWXRqgorJj26U",
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"]:
    info = m.fetch_info(url, log_callback=lambda s: print("PROBE log", s))
    entries = info.get("entries") or [info]
    print("PROBE", url, "error", info.get("error"), "partial", info.get("partial"), "count", len(entries),
          "cover", sum(1 for e in entries if (e.get("meta") or {}).get("cover")),
          "album", sum(1 for e in entries if (e.get("meta") or {}).get("album")))
    for e in entries[:2]:
        print("PROBE meta", json.dumps(e.get("meta"), ensure_ascii=False))
for q, d in [("ytsearch1:Queen - Bohemian Rhapsody audio", 354), ("ytsearch1:The Weeknd - Blinding Lights audio", 200)]:
    print("PROBE closest", q, m._closest_result(q, d, log_callback=lambda s: print("PROBE log", s)))
