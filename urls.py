"""Basic URL checks before any network request (ISSUES.md #32)."""

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
