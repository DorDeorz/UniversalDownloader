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
    assert i18n.tr_message("HTTP Error 403: Forbidden") == "HTTP Error 403: Forbidden"


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
    with open(os.path.join(ROOT, "UniversalDownloader.spec"), encoding="utf-8") as f:
        assert "('locales', 'locales')" in f.read()
