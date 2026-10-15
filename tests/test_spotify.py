"""Spotify links: the embed page's song list becomes YouTube searches."""

import json

import pytest

import logic
import playlist
import spotify


def _page(entity):
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


PLAYLIST = {
    "type": "playlist", "name": "Road Trip",
    "trackList": [
        {"uri": "spotify:track:1", "title": "Bohemian Rhapsody", "subtitle": "Queen", "duration": 354000},
        {"uri": "spotify:track:2", "title": "Under Pressure", "subtitle": "Queen, David Bowie",
         "duration": 248000},
        {"uri": "spotify:track:3", "title": ""},  # nothing to search for
    ],
}
TRACK = {"type": "track", "name": "Blinding Lights", "title": "Blinding Lights",
         "artists": [{"name": "The Weeknd", "uri": "spotify:artist:1"}], "duration": 200040}


@pytest.mark.parametrize("url, link", [
    ("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=abc", ("track", "4uLU6hMCjMI75M1A2tKUQC")),
    ("https://open.spotify.com/intl-tr/album/1A2GTWGtFfWp7KSQTwWOyo", ("album", "1A2GTWGtFfWp7KSQTwWOyo")),
    ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", ("playlist", "37i9dQZF1DXcBWIGoYBM5M")),
    ("https://open.spotify.com/embed/playlist/37i9dQZF1DXcBWIGoYBM5M", ("playlist", "37i9dQZF1DXcBWIGoYBM5M")),
    ("https://open.spotify.com/episode/7makk4oTQel546B0PZlDM5", None),  # podcasts: yt-dlp
    ("https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF", None),
    ("https://www.youtube.com/watch?v=abc", None),
])
def test_music_links(url, link):
    assert spotify.music_link(url) == link


def test_playlist_becomes_searches():
    info = spotify.info_from_embed(_page(PLAYLIST), "playlist")
    assert info["_type"] == "playlist" and info["title"] == "Road Trip"
    assert [e["url"] for e in info["entries"]] == [
        "ytsearch1:Queen - Bohemian Rhapsody audio", "ytsearch1:Queen, David Bowie - Under Pressure audio"]
    assert info["entries"][0]["title"] == "Queen - Bohemian Rhapsody"
    assert info["entries"][0]["duration"] == 354
    analysis = playlist.analyze(info, "https://open.spotify.com/playlist/x")
    assert analysis.is_playlist and len(analysis.items) == 2 and not analysis.skipped
    assert playlist.found_by_search(analysis)
    assert analysis.items[1].index == 2 and analysis.items[1].playlist == "Road Trip"


def test_track_is_one_song():
    info = spotify.info_from_embed(_page(TRACK), "track")
    analysis = playlist.analyze(info, "https://open.spotify.com/track/x")
    assert not analysis.is_playlist
    assert analysis.title == "The Weeknd - Blinding Lights"
    assert analysis.items[0].url == "ytsearch1:The Weeknd - Blinding Lights audio"
    assert playlist.found_by_search(analysis)


def test_entity_is_found_when_the_page_moves_it():
    data = {"props": {"other": [{"entity": PLAYLIST}]}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    assert len(spotify.info_from_embed(html, "playlist")["entries"]) == 2


@pytest.mark.parametrize("html", ["<html>no data</html>", _page({"type": "playlist", "trackList": []})])
def test_unreadable_pages_say_so(html):
    with pytest.raises(spotify.SpotifyError):
        spotify.info_from_embed(html, "playlist")


def test_fetch_follows_short_links_and_reads_the_embed_page():
    asked = []

    def open_url(url, headers=None, data=None):
        asked.append(url)
        if "spotify.link" in url:
            return "https://open.spotify.com/track/abc?si=1", "<html></html>"
        return url, _page(TRACK)

    info = spotify.fetch_info("https://spotify.link/xyz", open_url)
    assert asked == ["https://spotify.link/xyz", "https://open.spotify.com/embed/track/abc"]
    assert info["webpage_url"].startswith("ytsearch1:The Weeknd")
    assert spotify.fetch_info("https://www.youtube.com/watch?v=a", open_url) is None


def test_fetch_info_answers_spotify_links_without_yt_dlp(monkeypatch):
    monkeypatch.setattr(logic, "_read_page", lambda url, opts, headers=None, data=None: (url, _page(PLAYLIST)))
    info = logic.DownloadManager().fetch_info("https://open.spotify.com/playlist/abc")
    assert info["title"] == "Road Trip" and len(info["entries"]) == 2

    def broken(url, opts, headers=None, data=None):
        raise OSError("HTTP Error 404: Not Found")
    monkeypatch.setattr(logic, "_read_page", broken)
    assert "404" in logic.DownloadManager().fetch_info("https://open.spotify.com/playlist/abc")["error"]


def test_search_items_are_remembered_by_their_search():
    item = playlist.QueueItem(url="ytsearch1:Queen - Bohemian Rhapsody audio", title="x")
    assert playlist.downloaded_before([item], ["ytsearch1:Queen - Bohemian Rhapsody audio"]) == [item]
    assert playlist.downloaded_before([item], ["https://open.spotify.com/track/1"]) == []


def test_a_song_search_downloads_its_first_result(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"_type": "playlist", "title": "Queen - Bohemian Rhapsody audio",
                     "entries": [{"id": "fJ9rUzIMcZQ", "title": "Queen – Bohemian Rhapsody (Official Audio)",
                                  "ext": "mp4", "acodec": "opus", "vcodec": "none", "extractor": "youtube"}]}
    import formats
    result = manager.download_video("ytsearch1:Queen - Bohemian Rhapsody audio",
                                    {"mode": formats.AUDIO_ONLY, "format": "mp3", "save_path": str(tmp_path)})
    assert result.ok, result.error
    assert result.title.startswith("Queen – Bohemian Rhapsody")
    assert result.path.endswith(".mp3")


def _embed_with_token(count):
    entity = {"type": "playlist", "name": "Long",
              "trackList": [{"title": f"Song {i}", "subtitle": "Band"} for i in range(count)]}
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity},
                                              "settings": {"session": {"accessToken": "TOKEN"}}}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def _pathfinder_page(offset, total, limit=100):
    items = []
    for i in range(offset, min(offset + limit, total)):
        items.append({"itemV2": {"data": {"__typename": "Track", "name": f"Song {i}",
                                          "artists": {"items": [{"profile": {"name": "Band"}}]},
                                          "trackDuration": {"totalMilliseconds": 180000}}}})
    items.append({"itemV2": {"data": {"__typename": "LocalTrack", "name": "my file"}}})
    return {"data": {"playlistV2": {"content": {"items": items, "totalCount": total}}}}


def test_long_playlists_are_read_past_the_embed_limit():
    posts = []

    def open_url(url, headers=None, data=None):
        if "/embed/" in url:
            return url, _embed_with_token(100)
        if url == "https://open.spotify.com/playlist/big":
            return url, '<script src="https://open.spotifycdn.com/cdn/build/web-player/web-player.35377fe6.js"></script>'
        if url.endswith("web-player.35377fe6.js"):
            return url, 'x("fetchPlaylist","query","' + "a" * 64 + '",null)'
        assert url == spotify.PATHFINDER and headers["Authorization"] == "Bearer TOKEN"
        body = json.loads(data)
        posts.append(body)
        return url, json.dumps(_pathfinder_page(body["variables"]["offset"], 250))

    info = spotify.fetch_info("https://open.spotify.com/playlist/big", open_url)
    assert len(info["entries"]) == 250 and "partial" not in info
    assert info["entries"][249]["url"] == "ytsearch1:Band - Song 249 audio"
    assert info["entries"][100]["duration"] == 180
    # The whole list comes from pathfinder, which also names albums and covers.
    assert [p["variables"]["offset"] for p in posts] == [0, 100, 200]
    assert posts[0]["extensions"]["persistedQuery"]["sha256Hash"] == "a" * 64


def test_short_playlists_keep_the_embed_songs_when_pathfinder_fails():
    def open_url(url, headers=None, data=None):
        if data is not None:
            raise OSError("HTTP Error 400: Bad Request")
        return url, _embed_with_token(42)

    info = spotify.fetch_info("https://open.spotify.com/playlist/small", open_url)
    assert len(info["entries"]) == 42 and "partial" not in info


def test_the_first_100_songs_stay_when_the_rest_cannot_be_read():
    def open_url(url, headers=None, data=None):
        if "/embed/" in url:
            return url, _embed_with_token(100)
        if data is not None:
            raise OSError("HTTP Error 400: Bad Request")
        return url, "<html></html>"  # no script found: the known query id is used

    info = spotify.fetch_info("https://open.spotify.com/playlist/big", open_url)
    assert len(info["entries"]) == 100 and "400" in info["partial"]
