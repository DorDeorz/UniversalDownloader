"""Basic URL checks before any network request (ISSUES.md #32)."""

from urllib.parse import urlsplit


def normalize_url(text):
    """Return a cleaned http(s) URL, or raise ValueError with a readable reason.

    Adds ``https://`` when the scheme is missing (``youtu.be/abc``), so a
    pasted link without it still works.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Paste a link first")
    if any(ch.isspace() for ch in text):
        raise ValueError("A link cannot contain spaces; paste one link at a time")
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Only http and https links are supported, not '{parts.scheme}'")
    host = parts.hostname or ""
    if "." not in host and host != "localhost":
        raise ValueError("This does not look like a web link")
    return text
