"""Translations: every language is complete, and texts fall back to English."""

import json
import os
import string

import pytest

import i18n
import settings as settings_store
import urls
from results import ItemResult, ItemStatus, JobSummary

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCALES = os.path.join(ROOT, "locales")
REAL_SYSTEM_LANGUAGE = i18n.system_language  # conftest replaces it during tests


def _read(code):
    with open(os.path.join(LOCALES, f"{code}.json"), encoding="utf-8") as f:
        return json.load(f)


def _fields(text):
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)


ENGLISH = _read("en")


def test_at_least_twenty_languages():
    assert len(i18n.LANGUAGES) >= 20
    assert {"en", "tr", "de", "fr"} <= set(i18n.LANGUAGES)
    assert sorted(f[:-5] for f in os.listdir(LOCALES) if f.endswith(".json")) == sorted(i18n.LANGUAGES)


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_language_has_every_message_with_the_same_placeholders(code):
    catalog = _read(code)
    assert set(catalog) == set(ENGLISH)
    for key, english in ENGLISH.items():
        assert isinstance(catalog[key], str) and catalog[key].strip(), key
        assert _fields(catalog[key]) == _fields(english), key
        catalog[key].format(**{name: "x" for name in _fields(english)})  # formats cleanly


def test_missing_key_falls_back_to_english(monkeypatch):
    monkeypatch.setitem(i18n._catalogs, "de", {"link.paste": "Einfügen"})
    i18n.set_language("de")
    assert i18n.tr("link.paste") == "Einfügen"
    assert i18n.tr("link.analyze") == "Analyze"
    assert i18n.tr("action.download_n", count=3) == "Download 3 items"
    assert i18n.tr("no.such.key") == "no.such.key"


def test_broken_placeholder_in_a_translation_uses_english(monkeypatch):
    monkeypatch.setitem(i18n._catalogs, "de", {"action.download_n": "{anzahl} laden"})
    i18n.set_language("de")
    assert i18n.tr("action.download_n", count=2) == "Download 2 items"


def test_fixed_messages_from_other_modules_are_translated(monkeypatch):
    monkeypatch.setitem(i18n._catalogs, "tr", {"msg.private video": "özel video"})
    i18n.set_language("tr")
    assert i18n.tr_message("private video") == "özel video"
    assert i18n.tr_message("Something nobody knows went wrong") == "Something nobody knows went wrong"


@pytest.mark.parametrize("message, key", [
    ("[youtube] abc: Sign in to confirm you\u2019re not a bot. Use --cookies-from-browser", "error.bot_check"),
    ("unable to download video data: HTTP Error 403: Forbidden", "error.forbidden"),
    ("HTTP Error 429: Too Many Requests", "error.rate_limited"),
    ("HTTP Error 404: Not Found", "error.not_found"),
    ("[youtube] abc: Video unavailable. This video has been removed by the uploader", "error.unavailable"),
    ("[youtube] abc: Private video. Sign in if you've been granted access", "error.private"),
    ("The uploader has not made this video available in your country", "error.geo"),
    ("Join this channel to get access to members-only content", "error.members"),
    ("This video is DRM protected", "error.drm"),
    ("Premieres in 3 hours", "error.not_yet"),
    ("Unsupported URL: https://example.com/page", "error.unsupported"),
    ("[Errno 28] No space left on device", "error.disk_full"),
    ("Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>", "error.network"),
    ("The read operation timed out", "error.network"),
])
def test_known_yt_dlp_errors_are_explained(message, key):
    assert i18n.error_key(message) == key
    i18n.set_language("tr")
    assert i18n.tr_message(message) == i18n.tr(key) != message
    i18n.set_language("en")


def test_app_messages_with_values_are_translated():
    import filenames
    import logic
    i18n.set_language("de")
    text = filenames.FOLDER_TOO_LONG.format(length=180, limit=150)
    assert i18n.tr_message(text) == i18n.tr("folder.too_long", length="180", limit="150") != text
    with pytest.raises(logic.TrimError) as e:
        logic.parse_trim_range("1:75", "")
    assert i18n.tr_message(str(e.value)) != str(e.value)
    assert "1:75" in i18n.tr_message(str(e.value))
    for start, end, duration in (("50", "", 30), ("0", "40", 30), ("20", "10", None)):
        with pytest.raises(logic.TrimError) as e:
            logic.parse_trim_range(start, end, duration)
        assert i18n.tr_message(str(e.value)) != str(e.value)
    message = logic.explain_format_error("Requested format is not available", "Video + Audio", "720p")
    assert "720p" in i18n.tr_message(message) and i18n.tr_message(message) != message
    i18n.set_language("en")


@pytest.mark.parametrize("env, expected", [
    ({"LANG": "tr_TR.UTF-8"}, "tr"),
    ({"LC_ALL": "de_DE.UTF-8", "LANG": "fr_FR"}, "de"),
    ({"LANG": "nn_NO"}, "nb"),
    ({"LANG": "zh_CN.UTF-8"}, "zh"),
    ({"LANG": "xx_YY"}, "en"),
])
def test_system_language(monkeypatch, env, expected):
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: (None, None))
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    assert REAL_SYSTEM_LANGUAGE() == expected


def test_auto_follows_the_system_and_unknown_codes_are_not_used():
    assert i18n.set_language(i18n.AUTO) == "en"  # English in tests (conftest)
    assert i18n.set_language("ja") == "ja"
    assert i18n.set_language("xx") == "en"


def test_language_setting_is_saved_and_validated(tmp_path):
    path = str(tmp_path / "settings.json")
    settings_store.save(path, settings_store.Settings(download_folder=str(tmp_path), language="ko"))
    assert settings_store.load(path, str(tmp_path)).language == "ko"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"language": "klingon"}, f)
    assert settings_store.load(path, str(tmp_path)).language == i18n.AUTO


@pytest.mark.parametrize("text, key", [("", "url.empty"), ("a b", "url.spaces"),
                                       ("ftp://x.org", "url.scheme"), ("nodot", "url.invalid")])
def test_rejected_links_carry_a_message_key(text, key):
    with pytest.raises(urls.UrlError) as caught:
        urls.normalize_url(text)
    assert caught.value.key == key
    i18n.tr(caught.value.key, **caught.value.values)  # every value the message needs is there


def test_summary_uses_translated_words():
    summary = JobSummary()
    summary.add(ItemResult("u1", "A", ItemStatus.COMPLETED))
    summary.add(ItemResult("u2", "B", ItemStatus.FAILED, error="boom"))
    words = {ItemStatus.COMPLETED: "tamamlandı", ItemStatus.FAILED: "başarısız"}
    assert summary.title_key() == "summary.partial"
    assert summary.title() == "Download partly failed"
    assert summary.headline(label=words.get) == "1 tamamlandı, 1 başarısız"
    assert summary.report(label=words.get).splitlines()[1] == "- başarısız: B: boom"


def test_translations_are_packaged():
    with open(os.path.join(ROOT, "Orbida.spec"), encoding="utf-8") as f:
        assert "('locales', 'locales')" in f.read()


@pytest.mark.parametrize("lang", sorted(i18n.LANGUAGES))
def test_trim_labels_drop_only_the_example_time(lang):
    # Android shows "Start" and "End" over its trim fields; Vietnamese
    # "Bắt đầu" has two words, so splitting at the first space cut it.
    i18n.set_language(lang)
    for key in ("trim.start", "trim.end"):
        label = i18n.tr_label(key)
        assert label and not any(ch.isdigit() for ch in label)
        assert i18n.tr(key).startswith(label)
    if lang == "vi":
        assert (i18n.tr_label("trim.start"), i18n.tr_label("trim.end")) == ("Bắt đầu", "Kết thúc")
