"""Spotify tracks, albums and playlists, found on YouTube.

Spotify's audio is DRM-protected and yt-dlp has no extractor for its
music (only for podcast episodes and shows), so the songs themselves are
not downloaded from Spotify. Instead the public embed page of the link
(``open.spotify.com/embed/<kind>/<id>``, no account needed) gives the
title and artists of each song, and each song becomes a YouTube search
for "<artists> - <title>" whose first result is downloaded.

The embed page lists at most 100 songs of a playlist. The rest are read
the way Spotify's own web player reads them: its GraphQL endpoint
("pathfinder"), called with the anonymous token the embed page carries and
the query id found in the web player's script. If that fails, the first 100
songs are still returned, with ``partial`` set.
"""

import json
import re
from urllib.parse import urlsplit

from playlist import SEARCH_PREFIX

KINDS = ("track", "album", "playlist")
EMBED_LIMIT = 100          # songs the embed page lists at most
PAGE_SIZE = 100            # songs per pathfinder request
MAX_SONGS = 10000          # Spotify's own playlist limit
PATHFINDER = "https://api-partner.spotify.com/pathfinder/v2/query"
# The web player's query id when this was written; it is looked up again in
# the web player's script, since Spotify changes it when the query changes.
KNOWN_QUERY_HASH = "21ea11a6ac75a5f3e01fd365d29c18e0a4a8b7dc09f89bbb5d73910190c6acaf"
_SCRIPT = re.compile(r'<script[^>]+src="([^"]*/web-player\.[0-9a-f]+\.js)"')
_QUERY_HASH = re.compile(r'"fetchPlaylist","query","([0-9a-f]{64})"')
SHORT_HOSTS = ("spotify.link", "spoti.fi")

_PATH = re.compile(r"^/(?:intl-[\w-]+/)?(?:embed/)?(track|album|playlist)/([A-Za-z0-9]+)")
_NEXT_DATA = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class SpotifyError(ValueError):
    pass


def music_link(url):
    """``(kind, id)`` for a Spotify track, album or playlist link, else None."""
    parts = urlsplit(url or "")
    if (parts.hostname or "").lower() != "open.spotify.com":
        return None
    match = _PATH.match(parts.path)
    return (match.group(1), match.group(2)) if match else None


def is_short_link(url):
    return (urlsplit(url or "").hostname or "").lower() in SHORT_HOSTS


def embed_url(kind, item_id):
    return f"https://open.spotify.com/embed/{kind}/{item_id}"


def search_query(artists, title):
    """The YouTube search for one song; "audio" favours the plain song over music videos."""
    name = f"{artists} - {title}" if artists else title
    return f"{SEARCH_PREFIX}{name} audio"


def _page_data(html):
    match = _NEXT_DATA.search(html or "")
    if not match:
        raise SpotifyError("Spotify did not return the song list (the page has changed or the link is private)")
    return json.loads(match.group(1))


def _entity(html):
    entity = _find_entity(_page_data(html))
    if entity is None:
        raise SpotifyError("Spotify did not return the song list (the page has changed or the link is private)")
    return entity


def _find_entity(data):
    """props.pageProps.state.data.entity, looked up without trusting the exact path."""
    try:
        return data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError):
        pass
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if isinstance(node.get("entity"), dict) and node["entity"].get("type") in KINDS:
                return node["entity"]
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def _artists(item):
    names = [a.get("name") for a in item.get("artists") or [] if isinstance(a, dict) and a.get("name")]
    if names:
        return ", ".join(names)
    return (item.get("subtitle") or "").replace(" ", " ").strip()


def _seconds(item):
    duration = item.get("duration")
    if isinstance(duration, dict):
        duration = duration.get("totalMilliseconds")
    return duration / 1000 if isinstance(duration, (int, float)) and duration > 0 else None


def _song(item):
    title = (item.get("title") or item.get("name") or "").strip()
    if not title:
        return None
    artists = _artists(item)
    return {
        "title": f"{artists} - {title}" if artists else title,
        "url": search_query(artists, title),
        "duration": _seconds(item),
    }


def info_from_embed(html, kind):
    """yt-dlp style info (one song, or a playlist of songs) from an embed page."""
    entity = _entity(html)
    name = (entity.get("name") or entity.get("title") or "Spotify").strip()
    if kind == "track":
        song = _song(entity)
        if song is None:
            raise SpotifyError("Spotify did not say which song this is")
        return {"title": song["title"], "webpage_url": song["url"], "duration": song["duration"],
                "extractor_key": "Spotify"}
    entries = [song for song in map(_song, entity.get("trackList") or []) if song]
    if not entries:
        raise SpotifyError("This Spotify list has no songs that can be shown")
    return {"_type": "playlist", "title": name, "entries": entries, "extractor_key": "Spotify"}


def access_token(html):
    """The anonymous token in an embed page, or None."""
    try:
        return _page_data(html)["props"]["pageProps"]["state"]["settings"]["session"]["accessToken"] or None
    except (KeyError, TypeError, SpotifyError):
        return None


def query_hash(open_url, playlist_id):
    """The web player's id of its playlist query (the known one if it cannot be found)."""
    try:
        _final, page = open_url(f"https://open.spotify.com/playlist/{playlist_id}")
        script = _SCRIPT.search(page)
        if script:
            _final, js = open_url(script.group(1))
            found = _QUERY_HASH.search(js)
            if found:
                return found.group(1)
    except Exception:
        pass
    return KNOWN_QUERY_HASH


def songs_from_pathfinder(data):
    """``(songs as embed-style items, total count)`` from a fetchPlaylist answer."""
    try:
        content = data["data"]["playlistV2"]["content"]
    except (KeyError, TypeError):
        raise SpotifyError("Spotify did not return the rest of the playlist") from None
    items = []
    for entry in content.get("items") or []:
        track = ((entry or {}).get("itemV2") or {}).get("data") or {}
        if track.get("__typename") != "Track" or not track.get("name"):
            continue  # local files, removed or unavailable songs, podcast episodes
        artists = [{"name": a["profile"]["name"]} for a in (track.get("artists") or {}).get("items") or []
                   if (a.get("profile") or {}).get("name")]
        if not artists:
            artists = [{"name": a["profile"]["name"]}
                       for a in ((track.get("albumOfTrack") or {}).get("artists") or {}).get("items") or []
                       if (a.get("profile") or {}).get("name")]
        items.append({"title": track["name"], "artists": artists,
                      "duration": (track.get("trackDuration") or {}).get("totalMilliseconds")})
    return items, content.get("totalCount")


def rest_of_playlist(playlist_id, token, open_url, start):
    """The songs of a playlist from position ``start`` on."""
    query = query_hash(open_url, playlist_id)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json;charset=UTF-8",
               "App-Platform": "WebPlayer"}
    songs, offset = [], start
    while offset < MAX_SONGS:
        body = json.dumps({
            "operationName": "fetchPlaylist",
            "variables": {"uri": f"spotify:playlist:{playlist_id}", "offset": offset, "limit": PAGE_SIZE,
                          "enableWatchFeedEntrypoint": False},
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": query}},
        }).encode()
        _final, text = open_url(PATHFINDER, headers=headers, data=body)
        page, total = songs_from_pathfinder(json.loads(text))
        songs.extend(page)
        offset += PAGE_SIZE
        if not total or offset >= total:
            break
    return songs


def fetch_info(url, open_url):
    """Look up a Spotify link.

    ``open_url(url, headers=None, data=None)`` returns ``(final url, page
    text)``; with ``data`` it sends a POST.

    Returns None when ``url`` is not a Spotify music link (podcasts are left
    to yt-dlp).
    """
    if is_short_link(url):
        final, _text = open_url(url)
        url = final
    link = music_link(url)
    if link is None:
        return None
    kind, item_id = link
    _final, html = open_url(embed_url(kind, item_id))
    info = info_from_embed(html, kind)
    if kind == "playlist" and len(info["entries"]) >= EMBED_LIMIT:
        try:
            token = access_token(html)
            if not token:
                raise SpotifyError("no access token in the embed page")
            more = [song for song in map(_song, rest_of_playlist(item_id, token, open_url, EMBED_LIMIT)) if song]
            info["entries"].extend(more)
        except Exception as e:  # the first 100 songs are still worth downloading
            info["partial"] = str(e) or type(e).__name__
    return info
