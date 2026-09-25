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

_catalogs = {}
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


def tr_message(text):
    """Translate a fixed English message from another module (a skip
    reason, a processing step); unknown text is returned unchanged."""
    return tr("msg." + text) if ("msg." + text) in load_catalog(FALLBACK) else text
