"""Interface translations.

Each language is a JSON file in ``locales/`` mapping message keys to text,
with ``{name}`` placeholders for values. English (``en.json``) is complete
and is the fallback for any key a language lacks. Only the app's own text is
translated; messages that come from websites or yt-dlp stay as they are.

``set_language`` switches the language for the whole process; widgets that
show translated text must be refreshed by the UI afterwards.
"""

import json
import locale
import logging
import os
import re
import sys

from utils import resource_path

_log = logging.getLogger(__name__)

FALLBACK = "en"
AUTO = "auto"  # follow the system language

# Code -> the language's own name, as shown in the language menu. Scripts Tk
# cannot lay out correctly (right-to-left, Indic) are not offered.
LANGUAGES = {
    "en": "English",
    "tr": "Türkçe",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "it": "Italiano",
    "pt": "Português",
    "nl": "Nederlands",
    "pl": "Polski",
    "cs": "Čeština",
    "sv": "Svenska",
    "da": "Dansk",
    "nb": "Norsk bokmål",
    "fi": "Suomi",
    "hu": "Magyar",
    "ro": "Română",
    "el": "Ελληνικά",
    "bg": "Български",
    "ru": "Русский",
    "uk": "Українська",
    "id": "Bahasa Indonesia",
    "vi": "Tiếng Việt",
    "ja": "日本語",
    "ko": "한국어",
    "zh": "简体中文",
}

_catalogs: dict = {}
_current = FALLBACK


def locales_dir():
    return resource_path("locales")


def load_catalog(code):
    """The messages of one language, read once; {} if the file is missing or broken."""
    if code not in _catalogs:
        path = os.path.join(locales_dir(), f"{code}.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _catalogs[code] = {k: v for k, v in data.items() if isinstance(v, str)}
        except (OSError, ValueError) as e:
            _log.warning("Cannot read translations %s: %s", path, e)
            _catalogs[code] = {}
    return _catalogs[code]


def system_language():
    """The supported language closest to the user's system language, else English."""
    names = []
    if sys.platform == "win32":
        try:
            import ctypes
            names.append(locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage()))
        except (AttributeError, OSError):
            pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        names.append(os.environ.get(var))
    try:
        names.append(locale.getlocale()[0])
    except ValueError:
        pass
    for name in names:
        code = (name or "").replace("-", "_").split("_")[0].split(".")[0].lower()
        code = {"no": "nb", "nn": "nb"}.get(code, code)
        if code in LANGUAGES:
            return code
    return FALLBACK


def resolve(code):
    """A supported language code for a setting value (a code or 'auto')."""
    if code in LANGUAGES:
        return code
    return system_language()


def set_language(code):
    global _current
    _current = resolve(code)
    return _current


def current():
    return _current


def tr(key, **values):
    """Text for ``key`` in the current language, with ``values`` filled in."""
    text = load_catalog(_current).get(key)
    if text is None:
        text = load_catalog(FALLBACK).get(key, key)
    if values:
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            _log.warning("Bad placeholders in %s translation of %r", _current, key)
            return load_catalog(FALLBACK).get(key, key).format(**values)
    return text


def tr_label(key):
    """A text that ends with an example, without it: "Kết thúc  1:30" -> "Kết thúc"."""
    return tr(key).rsplit(None, 1)[0]


# Messages from another module that name a value, as the keys whose English
# text they are (logic.SIGN_IN_OFF and SIGN_IN_MISSING, filenames.FOLDER_TOO_LONG,
# logic.explain_format_error, results.verify_output and the trim checks).
MESSAGE_TEMPLATES = ("signin.off", "signin.missing", "folder.too_long", "error.no_quality", "error.output_empty",
                     "error.output_missing", "trim.invalid_format", "trim.invalid_60", "trim.start_beyond",
                     "trim.end_beyond", "trim.start_after_end")

# yt-dlp's (and the network's) refusals, by words they contain, and the key
# of what each means for the user. The first match wins, so the more
# specific ones come first. yt-dlp's own words stay in the activity log.
ERROR_PATTERNS = (
    (("not a bot",), "error.bot_check"),
    (("http error 429", "too many requests"), "error.rate_limited"),
    (("no space left", "errno 28", "not enough space on the disk", "disk is full"), "error.disk_full"),
    (("not available in your country", "geo restrict", "geo-restrict", "blocked it in your country",
      "not made this video available in your country", "from your location"), "error.geo"),
    (("members-only", "members only", "join this channel"), "error.members"),
    (("drm protected", "drm-protected", "uses drm", "is drm"), "error.drm"),
    (("premieres in", "live event will begin", "this live event will", "is_upcoming"), "error.not_yet"),
    (("private video", "this video is private", "this account is private"), "error.private"),
    (("http error 403", "403: forbidden"), "error.forbidden"),
    (("http error 404", "404: not found"), "error.not_found"),
    (("video unavailable", "this video is unavailable", "has been removed", "no longer available",
      "account associated with this video has been terminated", "this content isn't available",
      "content is private or unavailable"), "error.unavailable"),
    (("unsupported url",), "error.unsupported"),
    (("unable to download webpage", "timed out", "connection refused", "getaddrinfo failed",
      "name or service not known", "network is unreachable", "connection reset", "connection aborted",
      "temporary failure in name resolution", "failed to resolve", "unable to connect", "nodename nor servname",
      "remote end closed connection"), "error.network"),
)


def _template_pattern(template):
    """A regex for ``template`` with each ``{name}`` as a group (a repeat must be the same text)."""
    seen = set()

    def group(match):
        name = match.group(1)
        if name in seen:
            return f"(?P={name})"
        seen.add(name)
        return f"(?P<{name}>.+?)"
    return re.sub(r"\\\{(\w+)\\\}", group, re.escape(template)) if template else r"(?!)"


def error_key(text):
    """The key of the explanation for an error from yt-dlp or the network (ERROR_PATTERNS), or None."""
    lower = str(text or "").lower()
    for words, key in ERROR_PATTERNS:
        if any(word in lower for word in words):
            return key
    return None


def tr_message(text):
    """Translate a fixed English message from another module (a skip
    reason, a processing step, an error yt-dlp is known to give); unknown
    text is returned unchanged."""
    if ("msg." + text) in load_catalog(FALLBACK):
        return tr("msg." + text)
    for key in MESSAGE_TEMPLATES:
        match = re.fullmatch(_template_pattern(load_catalog(FALLBACK).get(key, "")), text)
        if match:
            return tr(key, **match.groupdict())
    key = error_key(text)
    if key is not None:
        return tr(key)
    return text
