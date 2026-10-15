"""Turn analysis results into validated download queue items.

``fetch_info`` uses yt-dlp's flat extraction, so playlist entries are only
stubs. This module decides which of them can be queued and why the others
are skipped (ISSUES.md #16, #17, #18, #24), and keeps each entry's position
in the playlist so file names can follow the playlist order (#36).
"""

from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

# yt-dlp's 'availability' values that mean the entry cannot be downloaded
# without an account or at all.
_BLOCKED_AVAILABILITY = {
    "private": "private video",
    "premium_only": "premium only",
    "subscriber_only": "subscribers only",
    "needs_auth": "sign-in required",
}
# Placeholder titles YouTube uses for removed entries in flat playlists.
_PLACEHOLDER_TITLES = {
    "[private video]": "private video",
    "[deleted video]": "deleted video",
    "[unavailable video]": "unavailable video",
}
_LIVE_STATUS = {
    "is_live": "live stream",
    "is_upcoming": "not yet available (upcoming)",
    "post_live": "live stream still processing",
}


@dataclass
class QueueItem:
    url: str
    title: str
    index: int | None = None          # 1-based position in the playlist
    playlist: str | None = None       # playlist title, for the output folder
    duration: float | None = None
    skip_reason: str | None = None    # set when the entry cannot be downloaded

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class AnalysisResult:
    """What an analysis found: one video, or a playlist's entries."""

    title: str
    items: list = field(default_factory=list)      # downloadable QueueItems
    skipped: list = field(default_factory=list)    # QueueItems with skip_reason
    is_playlist: bool = False

    @property
    def total(self):
        return len(self.items) + len(self.skipped)


def entry_url(entry):
    """Best URL for a flat entry, or None."""
    for key in ("webpage_url", "original_url", "url"):
        value = entry.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    # YouTube flat entries sometimes carry only the video id.
    if entry.get("id") and (entry.get("ie_key") == "Youtube" or entry.get("extractor_key") == "Youtube"):
        return f"https://www.youtube.com/watch?v={entry['id']}"
    return None


def skip_reason(entry):
    """Why a video entry cannot be downloaded, or None if it looks fine."""
    title = (entry.get("title") or "").strip().lower()
    if title in _PLACEHOLDER_TITLES:
        return _PLACEHOLDER_TITLES[title]
    availability = entry.get("availability")
    if availability in _BLOCKED_AVAILABILITY:
        return _BLOCKED_AVAILABILITY[availability]
    if entry.get("live_status") in _LIVE_STATUS:
        return _LIVE_STATUS[entry["live_status"]]
    if entry.get("is_live"):
        return _LIVE_STATUS["is_live"]
    if entry.get("_type") == "playlist" or entry.get("ie_key") in ("YoutubeTab", "YoutubePlaylist"):
        return "nested playlist (open it separately)"
    return None


def analyze(info, url):
    """Build an :class:`AnalysisResult` from ``fetch_info`` output."""
    if "entries" not in info and info.get("_type") != "playlist":
        title = info.get("title") or url
        item = QueueItem(url=info.get("webpage_url") or info.get("original_url") or url, title=title,
                         duration=info.get("duration"))
        reason = skip_reason(info)
        if reason:
            item.skip_reason = reason
            return AnalysisResult(title=title, skipped=[item])
        return AnalysisResult(title=title, items=[item])

    playlist_title = info.get("title") or info.get("id") or "Playlist"
    result = AnalysisResult(title=playlist_title, is_playlist=True)
    # yt-dlp may return a generator, a list, or None for an empty playlist.
    for position, entry in enumerate(info.get("entries") or [], start=1):
        if not entry:
            result.skipped.append(QueueItem(url="", title=f"Video #{position}", index=position,
                                            playlist=playlist_title, skip_reason="unavailable"))
            continue
        index = entry.get("playlist_index") or position
        title = entry.get("title") or f"Video #{index}"
        item = QueueItem(url=entry_url(entry) or "", title=title, index=index, playlist=playlist_title,
                         duration=entry.get("duration"))
        item.skip_reason = skip_reason(entry) or (None if item.url else "no downloadable URL")
        (result.skipped if item.skip_reason else result.items).append(item)
    return result


def url_key(url):
    """A key that is the same for every link to one video.

    YouTube links differ in form (watch?v=, youtu.be/, shorts/, music.) and
    in extra parameters (list=, t=, si=), so they are reduced to the video
    id. Other links lose their scheme, "www." and a trailing slash.
    """
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m.", "music."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    path = parts.path.rstrip("/")
    if host == "youtube.com":
        video = parse_qs(parts.query).get("v", [None])[0]
        if video:
            return "youtube:" + video
        for prefix in ("/shorts/", "/live/", "/embed/"):
            if path.startswith(prefix):
                return "youtube:" + path[len(prefix):].split("/")[0]
    if host == "youtu.be" and path:
        return "youtube:" + path.lstrip("/").split("/")[0]
    return f"{host}{path}" + (f"?{parts.query}" if parts.query else "")


def downloaded_before(items, urls):
    """The items whose link is among ``urls`` (links downloaded earlier)."""
    known = {url_key(u) for u in urls if u}
    return [item for item in items if item.url and url_key(item.url) in known]
