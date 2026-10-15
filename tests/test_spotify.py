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

    def open_url(url):
        asked.append(url)
        if "spotify.link" in url:
            return "https://open.spotify.com/track/abc?si=1", "<html></html>"
        return url, _page(TRACK)

    info = spotify.fetch_info("https://spotify.link/xyz", open_url)
    assert asked == ["https://spotify.link/xyz", "https://open.spotify.com/embed/track/abc"]
    assert info["webpage_url"].startswith("ytsearch1:The Weeknd")
    assert spotify.fetch_info("https://www.youtube.com/watch?v=a", open_url) is None


def test_fetch_info_answers_spotify_links_without_yt_dlp(monkeypatch):
    monkeypatch.setattr(logic, "_read_page", lambda url, opts: (url, _page(PLAYLIST)))
    info = logic.DownloadManager().fetch_info("https://open.spotify.com/playlist/abc")
    assert info["title"] == "Road Trip" and len(info["entries"]) == 2

    def broken(url, opts):
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
