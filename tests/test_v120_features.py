"""Orbida 1.2.0: song tags and covers, closer song matches, subtitles, speed
limit, proxy, several links at once, the clipboard watch and the browser
extension."""

import json
import os
import re
import sys
import threading

import pytest

import app_setup
import formats
import logic
import playlist
import settings as settings_store
import spotify
import urls

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTENSION = os.path.join(ROOT, "browser_extension")

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


def _page(entity):
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


COVER = {"sources": [{"url": "https://i.scdn.co/image/small", "width": 64},
                     {"url": "https://i.scdn.co/image/big", "width": 640}]}


@pytest.fixture(autouse=True)
def reset_network():
    yield
    logic.set_network_options("")


# --- Song tags and covers ---------------------------------------------------------

def test_a_track_carries_its_names_and_cover():
    entity = {"type": "track", "name": "Blinding Lights", "artists": [{"name": "The Weeknd"}],
              "duration": 200040, "coverArt": COVER}
    info = spotify.info_from_embed(_page(entity), "track")
    assert info["meta"] == {"artist": "The Weeknd", "track": "Blinding Lights",
                            "cover": "https://i.scdn.co/image/big", "duration": 200.04}
    item = playlist.analyze(info, "https://open.spotify.com/track/x").items[0]
    assert item.meta["cover"].endswith("/big") and item.as_dict()["meta"] == info["meta"]


def test_album_songs_share_the_album_name_and_cover():
    entity = {"type": "album", "name": "After Hours", "coverArt": COVER,
              "trackList": [{"title": "Alone Again", "subtitle": "The Weeknd", "duration": 250000}]}
    info = spotify.info_from_embed(_page(entity), "album")
    meta = info["entries"][0]["meta"]
    assert meta["album"] == "After Hours" and meta["cover"].endswith("/big")
    assert playlist.analyze(info, "u").items[0].meta == meta


def test_playlist_songs_get_their_album_and_cover_from_pathfinder():
    data = {"data": {"playlistV2": {"content": {"totalCount": 1, "items": [{"itemV2": {"data": {
        "__typename": "Track", "name": "Song", "artists": {"items": [{"profile": {"name": "Band"}}]},
        "albumOfTrack": {"name": "Record", "coverArt": COVER},
        "trackDuration": {"totalMilliseconds": 180000}}}}]}}}}
    songs, total = spotify.songs_from_pathfinder(data)
    assert total == 1
    song = spotify._song(songs[0])
    assert song["meta"] == {"artist": "Band", "track": "Song", "album": "Record",
                            "cover": "https://i.scdn.co/image/big", "duration": 180}


def test_a_song_is_saved_under_spotify_names_with_the_album_cover(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"id": "v1", "title": "The Weeknd - Blinding Lights (Official Video)", "ext": "webm",
                     "acodec": "opus", "vcodec": "none", "thumbnails": [{"url": "https://i.ytimg.com/x.jpg"}]}
    meta = {"artist": "The Weeknd", "track": "Blinding Lights", "album": "After Hours",
            "cover": "https://i.scdn.co/image/big"}
    result = manager.download_video("https://www.youtube.com/watch?v=v1",
                                    {"mode": formats.AUDIO_ONLY, "format": "mp3", "save_path": str(tmp_path),
                                     "meta": meta})
    assert result.ok, result.error
    assert os.path.basename(result.path) == "The Weeknd - Blinding Lights.mp3"
    info = fake_ydl.instances[-1].process_calls[-1]
    assert (info["track"], info["artist"], info["album"]) == ("Blinding Lights", "The Weeknd", "After Hours")
    assert info["thumbnails"] == [{"url": "https://i.scdn.co/image/big", "id": "cover"}]


# --- The closest match ----------------------------------------------------------

def _entry(video, duration):
    return {"id": video, "url": f"https://www.youtube.com/watch?v={video}", "duration": duration}


@pytest.mark.parametrize("entries, chosen", [
    ([_entry("a", 212), _entry("b", 200)], "a"),           # the first is close enough
    ([_entry("a", 290), _entry("b", 203), _entry("c", 150)], "b"),  # a long music video loses
    ([_entry("a", None), _entry("b", 260)], "b"),           # no length: the closest known
    ([{"id": "x"}, _entry("b", 199)], "b"),                 # no link at all is never taken
])
def test_the_result_closest_in_length_wins(entries, chosen):
    assert logic.closest_by_duration(entries, 200)["id"] == chosen


def test_a_song_search_compares_three_results(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"_type": "playlist", "entries": [
        {**_entry("long", 300), "title": "Video", "ext": "webm", "acodec": "opus", "vcodec": "none"},
        {**_entry("song", 201), "title": "Audio", "ext": "webm", "acodec": "opus", "vcodec": "none"}]}
    result = manager.download_video("ytsearch1:Band - Song audio",
                                    {"mode": formats.AUDIO_ONLY, "format": "mp3", "save_path": str(tmp_path),
                                     "meta": {"artist": "Band", "track": "Song", "duration": 200}})
    assert result.ok, result.error
    asked = [url for ydl in fake_ydl.instances for url, _download in ydl.extract_calls]
    assert asked[:2] == ["ytsearch3:Band - Song audio", "https://www.youtube.com/watch?v=song"]
    flat = next(ydl for ydl in fake_ydl.instances if ydl.extract_calls)
    assert flat.params["extract_flat"] == "in_playlist"


# --- Subtitles ------------------------------------------------------------------

def test_subtitles_are_saved_in_a_separate_pass(manager, fake_ydl, tmp_path):
    fake_ydl.subtitles = ("tr", "en")
    logs = []
    result = manager.download_video("https://example.com/v", {
        "mode": formats.VIDEO_AUDIO, "format": "mp4", "save_path": str(tmp_path),
        "subtitles": True, "subtitle_langs": logic.subtitle_languages("tr")}, log_callback=logs.append)
    assert result.ok, result.error
    subs = fake_ydl.instances[-1].params
    assert subs["skip_download"] and subs["writesubtitles"] and subs["writeautomaticsub"]
    assert subs["subtitleslangs"] == ["tr.*", "en.*"]
    assert subs["ignoreerrors"] is True  # a refused subtitle never fails the video
    assert {"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"} in subs["postprocessors"]
    assert "Subtitles: 2 saved" in logs


def test_no_subtitle_pass_for_audio_or_when_off(manager, fake_ydl, tmp_path):
    for options in ({"mode": formats.AUDIO_ONLY, "format": "mp3", "subtitles": True},
                    {"mode": formats.VIDEO_AUDIO, "format": "mp4"}):
        fake_ydl.instances = []
        assert manager.download_video("https://example.com/v", dict(options, save_path=str(tmp_path))).ok
        assert not any(ydl.params.get("skip_download") for ydl in fake_ydl.instances)


def test_subtitle_languages_follow_the_app_language():
    assert logic.subtitle_languages("de") == ["de", "en"]
    assert logic.subtitle_languages("en") == ["en"]
    assert logic.subtitle_languages("nb") == ["nb", "no", "en"]


# --- Speed limit and proxy ----------------------------------------------------------

def test_the_speed_limit_reaches_yt_dlp(manager, fake_ydl, tmp_path):
    options = settings_store.download_speed_options(settings_store.Settings(speed_limit=5))
    assert options["ratelimit"] == 5 * 1024 * 1024
    assert "ratelimit" not in settings_store.download_speed_options(settings_store.Settings())
    assert manager.download_video("https://example.com/v", dict(
        options, mode=formats.VIDEO_AUDIO, format="mp4", save_path=str(tmp_path))).ok
    assert fake_ydl.instances[-1].params["ratelimit"] == 5 * 1024 * 1024


def test_the_proxy_is_used_for_every_request():
    logic.set_network_options("socks5://127.0.0.1:9050")
    assert logic.base_ydl_options()["proxy"] == "socks5://127.0.0.1:9050"
    logic.set_network_options("")
    assert "proxy" not in logic.base_ydl_options()


@pytest.mark.parametrize("text, proxy", [
    ("", ""),
    ("127.0.0.1:8080", "http://127.0.0.1:8080"),
    (" socks5://user:pw@proxy.example:1080 ", "socks5://user:pw@proxy.example:1080"),
    ("https://[::1]:3128", "https://[::1]:3128"),
])
def test_proxy_addresses(text, proxy):
    assert urls.proxy_url(text) == proxy


@pytest.mark.parametrize("text", ["proxy.example", "ftp://h:21", "h:0", "h:70000", "http://h:8080/path"])
def test_bad_proxy_addresses_are_refused(text):
    with pytest.raises(ValueError):
        urls.proxy_url(text)


def test_settings_keep_only_valid_new_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"speed_limit": 3, "proxy": "not a proxy", "watch_clipboard": True}))
    loaded = settings_store.load(str(path), "/d")
    assert loaded.speed_limit == 0 and loaded.proxy == "" and loaded.clipboard == "watch"
    assert loaded.with_clipboard("off").clipboard == "off"
    start = loaded.with_clipboard("start")
    assert start.auto_paste and not start.watch_clipboard


# --- Several links at once --------------------------------------------------------

def test_links_are_split_out_of_pasted_text():
    text = "1. https://youtu.be/a\n2) <https://x.com/u/status/1>, see https://youtu.be/a again youtube.com/b"
    assert urls.split_links(text) == ["https://youtu.be/a", "https://x.com/u/status/1"]
    assert urls.split_links("no links here") == []


# --- Links from the browser extension -----------------------------------------------

@pytest.mark.parametrize("args, link", [
    (["orbida://download?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc%26t%3D5"],
     "https://www.youtube.com/watch?v=abc&t=5"),
    (["orbida:download?url=https://youtu.be/x"], "https://youtu.be/x"),
    (["https://youtu.be/x"], "https://youtu.be/x"),
    (["orbida://download?url=javascript:alert(1)"], None),
    (["--flag"], None),
    ([], None),
])
def test_links_from_the_command_line(args, link):
    assert app_setup.link_from_args(args) == link


def test_a_second_start_hands_its_link_to_the_running_app(tmp_path):
    received = []
    got = threading.Event()
    server = app_setup.LinkServer(lambda url: (received.append(url), got.set()), folder=str(tmp_path))
    try:
        assert app_setup.send_link("https://youtu.be/x", folder=str(tmp_path))
        assert got.wait(5) and received == ["https://youtu.be/x"]
    finally:
        server.close()
    assert not os.path.exists(os.path.join(tmp_path, "ipc.json"))
    assert not app_setup.send_link("https://youtu.be/y", folder=str(tmp_path))


def test_a_message_without_the_token_is_ignored(tmp_path):
    import socket
    received = []
    server = app_setup.LinkServer(received.append, folder=str(tmp_path))
    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=5) as connection:
            connection.sendall(b'{"token": "guess", "url": "https://evil.example"}\n')
            assert connection.recv(16) == b""
        assert received == []
    finally:
        server.close()


def test_the_extension_is_a_valid_manifest_v3_extension():
    with open(os.path.join(EXTENSION, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {"contextMenus", "activeTab"}  # nothing more is needed
    for path in [*manifest["icons"].values(), manifest["background"]["service_worker"]]:
        assert os.path.isfile(os.path.join(EXTENSION, path)), path
    with open(os.path.join(EXTENSION, "background.js"), encoding="utf-8") as f:
        script = f.read()
    assert '"orbida://download?url=" + encodeURIComponent(link)' in script
    for name in ("menuPage", "menuLink"):
        assert f'getMessage("{name}")' in script


# Locale folder names Chrome accepts (others stop the extension from loading).
CHROME_LOCALES = {"bg", "cs", "da", "de", "el", "en", "es", "fi", "fr", "hu", "id", "it", "ja", "ko", "nl", "no",
                  "pl", "pt_BR", "pt_PT", "ro", "ru", "sv", "tr", "uk", "vi", "zh_CN"}
CHROME_CODE = {"nb": "no", "pt": "pt_BR", "zh": "zh_CN"}


def test_the_extension_speaks_the_app_languages():
    folders = set(os.listdir(os.path.join(EXTENSION, "_locales")))
    assert folders <= CHROME_LOCALES
    for name in os.listdir(os.path.join(ROOT, "locales")):
        lang = name[:-5]
        with open(os.path.join(ROOT, "locales", name), encoding="utf-8") as f:
            texts = json.load(f)
        with open(os.path.join(EXTENSION, "_locales", CHROME_CODE.get(lang, lang), "messages.json"),
                  encoding="utf-8") as f:
            messages = json.load(f)
        assert messages["menuPage"]["message"] == texts["extension.menu_page"]
        assert messages["menuLink"]["message"] == texts["extension.menu_link"]
        assert messages["description"]["message"] == texts["extension.description"]


def test_the_installer_registers_the_orbida_address_and_ships_the_extension():
    with open(os.path.join(ROOT, "installer", "Orbida.iss"), encoding="utf-8") as f:
        script = f.read()
    assert re.search(r'Subkey: "Software\\Classes\\orbida"; ValueType: string; ValueName: "URL Protocol"', script)
    assert '"""{app}\\{#AppExe}"" ""%1"""' in script
    with open(os.path.join(ROOT, "Orbida.spec"), encoding="utf-8") as f:
        assert "('browser_extension', 'browser_extension')" in f.read()


# --- The window ------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch, tmp_path):
    pytest.importorskip("customtkinter")
    from ui_helpers import make_app
    from test_ui_queue import QueueManager
    window = make_app(monkeypatch)
    window.manager = QueueManager(window.tools)
    window.manager.release.set()
    window.settings.show_summary = False
    window.download_folder = str(tmp_path)
    yield window
    window.destroy()


@needs_display
def test_several_pasted_links_download_one_after_another(app):
    from ui_helpers import pump
    app.url_entry.insert(0, "https://example.com/one https://example.com/two\nhttps://example.com/three")
    app.start_analysis_thread()
    assert app.url_entry.get() == "https://example.com/one"  # the first is under way
    assert pump(app, lambda: len(app.manager.downloaded) == 3 and not app.is_busy(), timeout=10)
    assert app.manager.downloaded == ["https://example.com/one", "https://example.com/two",
                                      "https://example.com/three"]


@needs_display
def test_a_copied_link_is_offered_while_watching(app):
    import ui
    from ui_helpers import pump
    app.clipboard_clear()
    app.clipboard_append("old text")
    pump(app, timeout=0.5)  # past the paste at start
    app._on_setting_changed("clipboard", "watch")
    assert app.settings.watch_clipboard and app.settings.auto_paste
    assert not app.copied_row.grid_info()
    app.clipboard_clear()
    app.clipboard_append("https://example.com/copied")
    assert pump(app, lambda: app.copied_row.grid_info(), timeout=3)
    assert app.lbl_copied.cget("text") == ui.tr("clipboard.copied", link="https://example.com/copied")
    app.use_copied()
    assert not app.copied_row.grid_info()
    assert pump(app, lambda: app.download_queue, timeout=5)
    assert app.analyzed_url == "https://example.com/copied"
    app._on_setting_changed("clipboard", "off")
    assert app._clip_poll is None and not app.settings.auto_paste


@needs_display
def test_a_link_from_the_browser_is_analyzed(app):
    from ui_helpers import pump
    app.open_settings()
    app.events.post("link_received", url="https://example.com/from-browser")
    assert pump(app, lambda: app.download_queue, timeout=5)
    assert app.settings_view is None
    assert app.url_entry.get() == "https://example.com/from-browser"


@needs_display
def test_subtitles_switch_is_off_for_audio_and_remembered(app):
    app._apply_mode(formats.AUDIO_ONLY)
    assert app.chk_subtitles.cget("state") == "disabled"
    app._apply_mode(formats.VIDEO_AUDIO)
    assert app.chk_subtitles.cget("state") == "normal"
    app.chk_subtitles.toggle()
    assert app.settings.subtitles


@needs_display
def test_the_proxy_field_saves_only_valid_addresses(app):
    app.open_settings()
    view = app.settings_view
    view.ent_proxy.insert(0, "nonsense")
    view._save_proxy()
    assert app.settings.proxy == "" and view.ent_proxy.cget("border_width") == 2
    view.ent_proxy.delete(0, "end")
    view.ent_proxy.insert(0, "127.0.0.1:8080")
    view._save_proxy()
    assert app.settings.proxy == "http://127.0.0.1:8080"
    assert logic.base_ydl_options()["proxy"] == "http://127.0.0.1:8080"


def test_the_extension_version_follows_the_app():
    from version import __version__
    with open(os.path.join(EXTENSION, "manifest.json"), encoding="utf-8") as f:
        assert json.load(f)["version"] == __version__


def test_a_page_cut_off_midway_is_read_again(monkeypatch):
    from http.client import IncompleteRead

    class Response:
        url = "https://open.spotify.com/embed/track/x"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            calls.append(1)
            if len(calls) == 1:
                raise IncompleteRead(b"x" * 17388)
            return b"<html>ok</html>"

    class YDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def urlopen(self, request):
            return Response()

    calls = []
    monkeypatch.setattr(logic.yt_dlp, "YoutubeDL", YDL)
    assert logic._read_page("https://open.spotify.com/embed/track/x", {}) == (Response.url, "<html>ok</html>")
    assert len(calls) == 2
