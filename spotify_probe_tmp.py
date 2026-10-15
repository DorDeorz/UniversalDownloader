import logic, playlist
m = logic.DownloadManager()
for url in ["https://open.spotify.com/playlist/37i9dQZF1DWXRqgorJj26U",
            "https://open.spotify.com/playlist/37i9dQZF1DX5Ejj0EkURtP",
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "https://open.spotify.com/album/4yP0hdKOZPNshxUOjY0cZj"]:
    info = m.fetch_info(url, log_callback=print)
    if "error" in info:
        print("PROBE", url, "ERROR", info["error"]); continue
    a = playlist.analyze(info, url)
    print("PROBE", url, a.title, "items", len(a.items), "partial", info.get("partial"))
    for item in a.items[98:103]:
        print("PROBE   ", item.index, item.title, "|", item.url, item.duration)
