"""Orbida 1.2.4: the remaining suggestions of the code reviews (shared code, no window)."""

import http.server
import logging
import os
import threading

import pytest

import app_setup
import logic
import media_tools


class _Answer(http.server.BaseHTTPRequestHandler):
    """A site, and a plain HTTP proxy: a request names the full address (or only the path)."""

    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        _Answer.seen.append(self.path)
        self.send_response(204)
        self.end_headers()


@pytest.fixture
def local_site():
    _Answer.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    old = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    yield f"127.0.0.1:{server.server_port}"
    server.shutdown()
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# --- Settings › Test connection (review #31) -----------------------------------------

def test_connection_test_reports_the_time_taken(local_site):
    seconds, error = logic.check_connection("", f"http://{local_site}/generate_204")
    assert error is None and 0 <= seconds < 5
    assert _Answer.seen == ["/generate_204"]


def test_connection_test_goes_through_the_proxy(local_site):
    seconds, error = logic.check_connection(f"http://{local_site}", "http://example.invalid/generate_204")
    assert error is None
    assert _Answer.seen == ["http://example.invalid/generate_204"]  # the proxy was asked for the address


def test_connection_test_names_the_problem():
    seconds, error = logic.check_connection("http://127.0.0.1:9", "http://example.invalid/x", timeout=3)
    assert seconds is None and error


# --- Detailed log (review #13) -------------------------------------------------------

def test_detailed_log_turns_on_debug_output():
    try:
        logic.set_verbose(True)
        app_setup.set_verbose_logging(True)
        assert logic.base_ydl_options()["verbose"] is True
        assert logging.getLogger().level == logging.DEBUG
    finally:
        logic.set_verbose(False)
        app_setup.set_verbose_logging(False)
    assert "verbose" not in logic.base_ydl_options()
    assert logging.getLogger().level == logging.INFO


# --- Copy diagnostics (review #29) ---------------------------------------------------

def test_diagnostics_name_versions_settings_and_the_end_of_the_log(tmp_path):
    import settings as settings_store
    log = tmp_path / "app.log"
    log.write_text("\n".join(f"line {i}" for i in range(500)), encoding="utf-8")
    current = settings_store.Settings(proxy="http://user:secret@proxy:8080", download_folder="C:\\Users\\Me\\Videos")
    tools = media_tools.ToolStatus(True, directory="/bin", version="7.1", source="bundled")
    text = app_setup.diagnostics(current, tools, "2026.10.21", str(log), lines=100)
    assert text.startswith("Orbida ") and "yt-dlp 2026.10.21" in text and "FFmpeg 7.1" in text
    assert "secret" not in text and '"proxy": "(set)"' in text
    assert "Users" not in text  # the folder names the user
    assert "line 499" in text and "line 399" not in text and "line 400" in text


def test_log_tail_of_a_missing_file_is_empty(tmp_path):
    assert app_setup.log_tail(str(tmp_path / "none.log")) == ""


# --- Spotify: the right song, fewer requests (review #41, #42, #43) ------------------

def _found(video, duration, title):
    return {"id": video, "url": f"https://www.youtube.com/watch?v={video}", "duration": duration, "title": title}


def test_a_live_version_loses_to_the_song_even_when_it_comes_first():
    entries = [_found("live", 203, "Band - Song (Live at Wembley)"), _found("song", 207, "Band - Song")]
    assert logic.closest_by_duration(entries, 200, "Band - Song")["id"] == "song"
    assert logic.closest_by_duration(entries, 200)["id"] == "live"  # without a name: the length alone


def test_a_result_with_another_name_loses_to_the_song():
    entries = [_found("other", 240, "Someone Else - Other Song"), _found("song", 246, "BAND — Song (Official Audio)")]
    assert logic.closest_by_duration(entries, 241, "Band - Song")["id"] == "song"


def test_the_first_result_stays_when_it_is_the_song():
    entries = [_found("a", 212, "Band - Song"), _found("b", 200, "Band - Song")]
    assert logic.closest_by_duration(entries, 200, "Band - Song")["id"] == "a"


def test_a_version_named_in_the_song_itself_is_not_penalised():
    entries = [_found("a", 300, "Band - Song (Live)"), _found("b", 200, "Band - Song (Live)")]
    assert logic.closest_by_duration(entries, 205, "Band - Song (Live)")["id"] == "b"


def test_title_similarity():
    assert logic.title_similarity("Band - Song", "band song official audio") == 1
    assert logic.title_similarity("Band - Song", "Nothing alike") < 0.5
    assert logic.title_similarity("", "x") == 0


def test_timed_cache_forgets_old_entries(monkeypatch):
    cache = logic.TimedCache(10, size=2)
    clock = [100.0]
    monkeypatch.setattr(logic.time, "monotonic", lambda: clock[0])
    cache.put("a", 1)
    clock[0] = 105
    cache.put("b", 2)
    clock[0] = 108
    cache.put("c", 3)  # full: the oldest goes
    assert cache.get("a") is None and cache.get("b") == 2
    clock[0] = 116
    assert cache.get("b") is None and cache.get("c") == 3


def test_a_song_is_searched_for_once(manager, fake_ydl, tmp_path):
    fake_ydl.info = {"_type": "playlist", "entries": [
        {**_found("song", 201, "Band - Song"), "ext": "webm", "acodec": "opus", "vcodec": "none"}]}
    options = {"mode": "Audio Only", "format": "mp3", "save_path": str(tmp_path),
               "meta": {"artist": "Band", "track": "Song", "duration": 200}}
    for _ in range(2):
        assert manager.download_video("ytsearch1:Band - Song audio", dict(options)).ok
    asked = [url for ydl in fake_ydl.instances for url, _d in ydl.extract_calls]
    assert asked.count("ytsearch3:Band - Song audio") == 1


def test_a_spotify_list_is_read_once_in_half_an_hour(manager, monkeypatch):
    import spotify
    calls = []

    def fetch(url, open_url):
        calls.append(url)
        return {"_type": "playlist", "title": "L", "entries": [{"url": "ytsearch1:a audio", "title": "a"}]}
    monkeypatch.setattr(spotify, "fetch_info", fetch)
    first = manager.fetch_info("https://open.spotify.com/playlist/x")
    first["entries"].clear()  # a caller changing its copy does not change the cache
    second = manager.fetch_info("https://open.spotify.com/playlist/x")
    assert calls == ["https://open.spotify.com/playlist/x"] and len(second["entries"]) == 1


def test_playlist_pages_are_read_a_few_at_a_time_and_kept_in_order(monkeypatch):
    import json
    import time
    import spotify
    monkeypatch.setattr(spotify, "query_hash", lambda open_url, pid: "h")
    running, most = [0], [0]
    lock = threading.Lock()

    def open_url(url, headers=None, data=None):
        offset = json.loads(data)["variables"]["offset"]
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        time.sleep(0.05 if offset % 200 else 0.01)  # pages finish out of order
        with lock:
            running[0] -= 1
        items = [{"itemV2": {"data": {"__typename": "Track", "name": f"S{i}",
                                      "artists": {"items": [{"profile": {"name": "B"}}]}}}}
                 for i in range(offset, min(offset + 100, 1000))]
        return url, json.dumps({"data": {"playlistV2": {"content": {"items": items, "totalCount": 1000}}}})

    songs = spotify.rest_of_playlist("p", "T", open_url, 0)
    assert [s["title"] for s in songs] == [f"S{i}" for i in range(1000)]
    assert 1 < most[0] <= spotify.PARALLEL_PAGES
