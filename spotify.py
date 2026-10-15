"""Spotify tracks, albums and playlists, found on YouTube.

Spotify's audio is DRM-protected and yt-dlp has no extractor for its
music (only for podcast episodes and shows), so the songs themselves are
not downloaded from Spotify. Instead the public embed page of the link
(``open.spotify.com/embed/<kind>/<id>``, no account needed) gives the
title and artists of each song, and each song becomes a YouTube search
for "<artists> - <title>" whose first result is downloaded.

The embed page lists what Spotify shows in its embedded player; for very
long playlists that may be fewer songs than the playlist has.
"""

import json
import re
from urllib.parse import urlsplit

from playlist import SEARCH_PREFIX

KINDS = ("track", "album", "playlist")
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


def _entity(html):
    match = _NEXT_DATA.search(html or "")
    if not match:
        raise SpotifyError("Spotify did not return the song list (the page has changed or the link is private)")
    data = json.loads(match.group(1))
    entity = _find_entity(data)
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


def fetch_info(url, open_url):
    """Look up a Spotify link; ``open_url(url)`` returns ``(final url, page text)``.

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
    return info_from_embed(html, kind)
