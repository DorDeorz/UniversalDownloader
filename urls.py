"""Basic URL checks before any network request (ISSUES.md #32)."""

import re
from urllib.parse import urlsplit


class UrlError(ValueError):
    """A rejected link. ``key`` and ``values`` let the UI translate the reason."""

    def __init__(self, key, message, **values):
        super().__init__(message)
        self.key = key
        self.values = values


def normalize_url(text):
    """Return a cleaned http(s) URL, or raise UrlError with a readable reason.

    Adds ``https://`` when the scheme is missing (``youtu.be/abc``), so a
    pasted link without it still works.
    """
    text = (text or "").strip()
    if not text:
        raise UrlError("url.empty", "Paste a link first")
    if any(ch.isspace() for ch in text):
        raise UrlError("url.spaces", "A link cannot contain spaces; paste one link at a time")
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        raise UrlError("url.scheme", f"Only http and https links are supported, not '{parts.scheme}'",
                       scheme=parts.scheme)
    host = parts.hostname or ""
    if "." not in host and host != "localhost":
        raise UrlError("url.invalid", "This does not look like a web link")
    return text


def split_links(text):
    """The http(s) links in ``text`` (several pasted at once), in order, without repeats.

    Words that are not links are ignored, so a pasted list with numbers or
    titles between the links still works.
    """
    links = []
    for word in (text or "").split():
        word = word.strip("<>()[]\"',;")
        if not word.lower().startswith(("http://", "https://")):
            continue
        try:
            link = normalize_url(word)
        except UrlError:
            continue
        if link not in links:
            links.append(link)
    return links


PROXY_SCHEMES = ("http", "https", "socks4", "socks4a", "socks5", "socks5h")
_PROXY = re.compile(r"^(?:(?P<scheme>[A-Za-z0-9]+)://)?(?:[^@/\s]+@)?"
                    r"(?P<host>[^:/@\s\[\]]+|\[[0-9A-Fa-f:]+\]):(?P<port>\d{1,5})/?$")


def proxy_url(text):
    """The proxy address for yt-dlp from what the user typed ('' for none).

    "host:port" means an HTTP proxy. Raises ValueError for anything that is
    not ``[scheme://][user:password@]host:port`` with a known scheme.
    """
    text = (text or "").strip()
    if not text:
        return ""
    match = _PROXY.match(text)
    scheme = (match.group("scheme") or "http").lower() if match else ""
    if not match or scheme not in PROXY_SCHEMES or not 0 < int(match.group("port")) < 65536:
        raise ValueError(f"'{text}' is not a proxy address; use host:port or e.g. socks5://host:port")
    return text if match.group("scheme") else f"http://{text}"
