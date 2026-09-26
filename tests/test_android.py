"""The Android app's UI-free parts: tool links, job worker, settings,
history, texts and staging.

The KivyMD screens themselves (android/app/main.py) only run on a device;
the emulator job in .github/workflows/android.yml covers them.
"""

import ast
import os
import re
import sys
import threading

import pytest

import events
import logic
from playlist import AnalysisResult, QueueItem
from results import ItemResult, ItemStatus

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "android", "app"))
sys.path.insert(0, os.path.join(ROOT, "android"))

import android_env  # noqa: E402
import app_settings  # noqa: E402
import history  # noqa: E402
import i18n  # noqa: E402
import stage  # noqa: E402
import texts  # noqa: E402
import worker  # noqa: E402


@pytest.fixture(autouse=True)
def reset_platform_options():
    yield
    logic.set_platform_options({})


# --- logic.set_platform_options ---------------------------------------------------


def test_platform_options_reach_every_ydl_instance():
    logic.set_platform_options({"js_runtimes": {"quickjs": {"path": "/x/qjs"}}})
    first = logic.base_ydl_options()
    assert first["js_runtimes"] == {"quickjs": {"path": "/x/qjs"}}
    # Each instance gets its own copy, so yt-dlp changing one leaves the next intact.
    first["js_runtimes"]["quickjs"]["path"] = "changed"
    assert logic.base_ydl_options()["js_runtimes"]["quickjs"]["path"] == "/x/qjs"


def test_platform_options_cannot_override_core_options():
    logic.set_platform_options({"socket_timeout": 1})
    assert logic.base_ydl_options()["socket_timeout"] == logic.SOCKET_TIMEOUT


@pytest.mark.parametrize("key", ["nocheckcertificate", "legacyserverconnect"])
def test_platform_options_refuse_disabling_https_checks(key):
    with pytest.raises(ValueError):
        logic.set_platform_options({key: True})
    assert key not in logic.base_ydl_options()


def test_no_platform_options_by_default():
    assert "js_runtimes" not in logic.base_ydl_options()


# --- android_env --------------------------------------------------------------------


def _fake_native_dir(tmp_path, names):
    native = tmp_path / "lib"
    native.mkdir()
    for name in names:
        (native / name).write_text("#!/bin/sh\n")
    return native


def test_link_tools_links_the_bundled_programs(tmp_path):
    native = _fake_native_dir(tmp_path, ["libffmpeg.so", "libffprobe.so", "libqjs.so"])
    links = android_env.link_tools(str(native), str(tmp_path / "tools"))
    assert set(links) == {"ffmpeg", "ffprobe", "qjs"}
    for name, link in links.items():
        assert os.path.basename(link) == name
        assert os.path.realpath(link) == str(native / android_env.TOOLS[name])


def test_link_tools_follows_a_moved_library_folder(tmp_path):
    # Android moves the native library folder when the app is updated.
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    old = _fake_native_dir(tmp_path / "old", ["libffmpeg.so"])
    new = _fake_native_dir(tmp_path / "new", ["libffmpeg.so"])
    tools = str(tmp_path / "tools")
    android_env.link_tools(str(old), tools)
    links = android_env.link_tools(str(new), tools)
    assert os.path.realpath(links["ffmpeg"]) == str(new / "libffmpeg.so")


def test_link_tools_drops_links_to_missing_programs(tmp_path):
    native = _fake_native_dir(tmp_path, ["libffmpeg.so", "libffprobe.so", "libqjs.so"])
    tools = str(tmp_path / "tools")
    android_env.link_tools(str(native), tools)
    os.remove(native / "libqjs.so")
    links = android_env.link_tools(str(native), tools)
    assert "qjs" not in links
    assert not os.path.lexists(os.path.join(tools, "qjs"))


def test_js_runtime_options():
    assert android_env.js_runtime_options({"ffmpeg": "/t/ffmpeg"}) == {}
    assert android_env.js_runtime_options({"qjs": "/t/qjs"}) == {"js_runtimes": {"quickjs": {"path": "/t/qjs"}}}


def test_choose_download_dir_falls_back():
    refused = {"/public": "Cannot write to /public"}
    folder, errors = android_env.choose_download_dir([None, "/public", "/app"], refused.get)
    assert folder == "/app"
    assert errors == ["Cannot write to /public"]
    assert android_env.choose_download_dir(["/public"], refused.get) == (None, ["Cannot write to /public"])


@pytest.mark.parametrize("text, link", [
    ("https://youtu.be/abc", "https://youtu.be/abc"),
    ("Watch this on TikTok: https://vm.tiktok.com/ZM123/ #fyp", "https://vm.tiktok.com/ZM123/"),
    ("Look (https://www.instagram.com/reel/xyz/?igsh=1).", "https://www.instagram.com/reel/xyz/?igsh=1"),
    ("HTTP://Example.com/v, and more", "HTTP://Example.com/v"),
    ("no link here", None),
    ("", None),
    (None, None),
])
def test_find_link(text, link):
    assert android_env.find_link(text) == link


def test_library_path_env_puts_the_native_folder_first():
    environ = {"LD_LIBRARY_PATH": "/other:/native"}
    android_env.library_path_env("/native", environ)
    assert environ["LD_LIBRARY_PATH"] == "/native:/other"
    environ = {}
    android_env.library_path_env("/native", environ)
    assert environ["LD_LIBRARY_PATH"] == "/native"


def test_certificate_env(tmp_path):
    bundle = tmp_path / "cacert.pem"
    bundle.write_text("x")
    environ = {}
    android_env.certificate_env(str(tmp_path / "missing.pem"), environ)
    assert environ == {}
    android_env.certificate_env(str(bundle), environ)
    assert environ == {"SSL_CERT_FILE": str(bundle)}


def test_not_on_android_in_tests():
    assert not android_env.on_android()


# --- worker -------------------------------------------------------------------------


def test_build_options():
    video = worker.build_options(worker.VIDEO_AUDIO, "/dl", quality="720p")
    assert video == {"mode": "Video + Audio", "format": "mp4", "quality": "720p", "save_path": "/dl",
                     "trim_start": None, "trim_end": None}
    audio = worker.build_options(worker.AUDIO_ONLY, "/dl", fmt="m4a", quality="192 kbps")
    assert (audio["format"], audio["quality"]) == ("m4a", "192 kbps")
    # A choice from the other mode (or an old setting) falls back to the default.
    assert worker.build_options(worker.AUDIO_ONLY, "/dl", fmt="mp4", quality="720p")["format"] == "mp3"
    assert worker.build_options(worker.AUDIO_ONLY, "/dl", quality="720p")["quality"] == "Best"
    assert worker.build_options(worker.VIDEO_AUDIO, "/dl", fmt="opus")["format"] == "mp4"
    with pytest.raises(ValueError):
        worker.build_options("Video Only", "/dl")


def test_build_options_trim():
    options = worker.build_options(worker.VIDEO_AUDIO, "/dl", trim_start=" 0:10 ", trim_end="")
    assert (options["trim_start"], options["trim_end"]) == ("0:10", None)
    assert logic.parse_trim_range(options["trim_start"], options["trim_end"], 60) == (10.0, 60.0)


def test_offered_choices_are_valid_format_plans():
    import formats
    for quality in worker.VIDEO_QUALITIES:
        for fmt in worker.MODE_FORMATS[worker.VIDEO_AUDIO]:
            formats.build_format_plan(worker.VIDEO_AUDIO, fmt, quality)
    for quality in worker.AUDIO_QUALITIES:
        for fmt in worker.MODE_FORMATS[worker.AUDIO_ONLY]:
            formats.build_format_plan(worker.AUDIO_ONLY, fmt, quality)


def test_no_formats_that_need_encoders_the_apk_lacks():
    # The bundled FFmpeg has no VP9 or Opus encoder (see android/native/build_tools.sh).
    offered = {fmt for fmts in worker.MODE_FORMATS.values() for fmt in fmts}
    assert not offered & {"webm", "opus"}


class FakeManager:
    def __init__(self, info=None, fail=()):
        self.info = info or {"title": "Clip", "webpage_url": "https://example.com/v"}
        self.fail = set(fail)
        self.calls = []
        self.infos = []

    def fetch_info(self, url, log_callback=None):
        log_callback("fetching")
        return self.info

    def download_video(self, url, options, progress_hook=None, log_callback=None, title=None, cancel_event=None,
                       info=None):
        self.calls.append((url, options))
        self.infos.append(info)
        progress_hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
        progress_hook({"status": "started", "postprocessor": "Merger"})
        if url in self.fail:
            raise RuntimeError("boom")
        return ItemResult(url, title, ItemStatus.COMPLETED, path=f"/dl/{title}.mp4")


def _drain(queue):
    seen = []
    for kind in (events.LOG, events.ANALYSIS_DONE, events.ANALYSIS_FAILED, events.ITEM_STARTED,
                 events.PROGRESS, events.STAGE, events.ITEM_DONE, events.JOB_DONE):
        queue.register(kind, lambda _kind=kind, **payload: seen.append((_kind, payload)))
    queue.dispatch_pending(max_events=1000)
    return seen


def test_session_analyzes_a_link():
    queue = events.EventQueue()
    session = worker.Session(FakeManager(), queue)
    assert session.analyze("example.com/v")
    session.wait(5)
    seen = _drain(queue)
    assert seen[0] == (events.LOG, {"message": "fetching"})
    kind, payload = seen[-1]
    assert kind == events.ANALYSIS_DONE
    assert payload["url"] == "https://example.com/v"
    assert [item.title for item in payload["analysis"].items] == ["Clip"]


def test_session_reports_analysis_errors():
    queue = events.EventQueue()
    session = worker.Session(FakeManager(info={"error": "Private video", "error_type": "DownloadError"}), queue)
    session.analyze("https://example.com/v")
    session.wait(5)
    assert _drain(queue)[-1] == (events.ANALYSIS_FAILED, {"message": "Private video"})


def test_session_rejects_bad_links_before_any_work():
    import urls
    session = worker.Session(FakeManager(), events.EventQueue())
    with pytest.raises(urls.UrlError):
        session.analyze("not a link")
    assert not session.busy


def test_session_downloads_each_item_and_reports_results():
    queue = events.EventQueue()
    manager = FakeManager(fail={"u2"})
    analysis = AnalysisResult(title="List", is_playlist=True, items=[
        QueueItem(url="u1", title="One", index=1, playlist="List"),
        QueueItem(url="u2", title="Two", index=2, playlist="List"),
    ], skipped=[QueueItem(url="", title="Gone", index=3, playlist="List", skip_reason="private video")])
    session = worker.Session(manager, queue)
    assert session.download(analysis, worker.build_options(worker.VIDEO_AUDIO, "/dl"))
    session.wait(5)
    seen = _drain(queue)

    assert [c[1]["playlist_index"] for c in manager.calls] == [1, 2]
    assert all(c[1]["playlist_title"] == "List" for c in manager.calls)
    kinds = [kind for kind, _ in seen]
    assert events.PROGRESS in kinds and events.STAGE in kinds
    done = [payload["result"] for kind, payload in seen if kind == events.ITEM_DONE]
    assert [(r.title, r.status) for r in done] == [
        ("One", ItemStatus.COMPLETED), ("Two", ItemStatus.FAILED), ("Gone", ItemStatus.SKIPPED)]
    assert done[1].error == "boom"
    summary = seen[-1][1]["summary"]
    assert seen[-1][0] == events.JOB_DONE and len(summary.results) == 3


def test_session_cancel_marks_remaining_items_cancelled():
    queue = events.EventQueue()
    release = threading.Event()

    class SlowManager(FakeManager):
        def download_video(self, url, options, progress_hook=None, log_callback=None, title=None,
                           cancel_event=None, info=None):
            release.wait(5)
            status = ItemStatus.CANCELLED if cancel_event.is_set() else ItemStatus.COMPLETED
            return ItemResult(url, title, status)

    analysis = AnalysisResult(title="List", is_playlist=True,
                              items=[QueueItem(url="u1", title="One"), QueueItem(url="u2", title="Two")])
    session = worker.Session(SlowManager(), queue)
    session.download(analysis, worker.build_options(worker.VIDEO_AUDIO, "/dl"))
    assert session.busy
    assert not session.download(analysis, {})  # one job at a time
    session.cancel()
    release.set()
    session.wait(5)
    done = [payload["result"].status for kind, payload in _drain(queue) if kind == events.ITEM_DONE]
    assert done == [ItemStatus.CANCELLED, ItemStatus.CANCELLED]


VIDEO_INFO = {"title": "Clip", "webpage_url": "https://example.com/v", "formats": [{"format_id": "18"}]}


def _analyse_and_download(manager, queue=None):
    queue = queue or events.EventQueue()
    session = worker.Session(manager, queue)
    session.analyze("https://example.com/v")
    session.wait(5)
    analysis = [p for k, p in _drain(queue) if k == events.ANALYSIS_DONE][0]["analysis"]
    session.download(analysis, worker.build_options(worker.VIDEO_AUDIO, "/dl"))
    session.wait(5)
    return session, analysis


def test_download_reuses_the_analysed_video():
    manager = FakeManager(info=VIDEO_INFO)
    _analyse_and_download(manager)
    assert manager.infos == [VIDEO_INFO]


def test_old_analysis_is_asked_again(monkeypatch):
    manager = FakeManager(info=VIDEO_INFO)
    clock = [1000.0]
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    queue = events.EventQueue()
    session = worker.Session(manager, queue)
    session.analyze("https://example.com/v")
    session.wait(5)
    analysis = [p for k, p in _drain(queue) if k == events.ANALYSIS_DONE][0]["analysis"]
    clock[0] += worker.REUSE_SECONDS + 1
    session.download(analysis, worker.build_options(worker.VIDEO_AUDIO, "/dl"))
    session.wait(5)
    assert manager.infos == [None]


def test_failed_download_with_saved_info_is_retried_fresh():
    class ExpiredLinks(FakeManager):
        def download_video(self, url, options, progress_hook=None, log_callback=None, title=None,
                           cancel_event=None, info=None):
            self.infos.append(info)
            status = ItemStatus.FAILED if info is not None else ItemStatus.COMPLETED
            return ItemResult(url, title, status, error="HTTP Error 403")

    manager = ExpiredLinks(info=VIDEO_INFO)
    queue = events.EventQueue()
    session, _analysis = _analyse_and_download(manager, queue)
    assert manager.infos == [VIDEO_INFO, None]
    done = [p["result"] for k, p in _drain(queue) if k == events.ITEM_DONE]
    assert done[0].status is ItemStatus.COMPLETED
    assert session._analysed is None  # not reused again


def test_playlists_are_not_reused():
    manager = FakeManager(info={"_type": "playlist", "title": "List",
                                "entries": [{"url": "https://example.com/a", "title": "A"}]})
    _analyse_and_download(manager)
    assert manager.infos == [None]


def test_progress_reaches_the_screen_a_few_times_a_second(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    queue = events.EventQueue()
    session = worker.Session(FakeManager(), queue)
    for _ in range(20):  # 20 chunks within 0.2 s
        session._progress({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
        clock[0] += 0.01
    clock[0] += 1
    session._progress({"status": "downloading", "downloaded_bytes": 6, "total_bytes": 10})
    session._progress({"status": "finished"})
    progress = [p["fraction"] for k, p in _drain(queue) if k == events.PROGRESS]
    assert progress == [0.5, 0.6, 1.0]


def _png_header(path):
    """(width, height, colour type) of a PNG file."""
    import struct
    with open(path, "rb") as f:
        head = f.read(26)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    width, height = struct.unpack(">II", head[16:24])
    return width, height, head[25]


def test_icon_files_match_the_build_settings():
    spec = open(os.path.join(ROOT, "android", "buildozer.spec"), encoding="utf-8").read()
    for key in ("icon.filename", "icon.adaptive_foreground.filename", "icon.adaptive_background.filename",
                "presplash.filename"):
        path = re.search(rf"^{re.escape(key)} = (.+)$", spec, re.M).group(1).strip()
        assert _png_header(os.path.join(ROOT, "android", path))[:2] == (512, 512), key
    # The launcher draws the background; the foreground layer needs transparency.
    assert _png_header(os.path.join(ROOT, "android", "icon", "icon_fg.png"))[2] == 6  # RGBA
    colour = re.search(r"^android.presplash_color = (#\w+)$", spec, re.M).group(1)
    render = open(os.path.join(ROOT, "android", "icon", "render.py"), encoding="utf-8").read()
    assert f'SPLASH_COLOUR = "{colour}"' in render


# --- staging ------------------------------------------------------------------------


def test_stage_copies_app_and_shared_modules(tmp_path):
    dest = stage.stage(str(tmp_path / "src"))
    names = set(os.listdir(dest))
    assert {"main.py", "worker.py", "android_env.py", "layout.py", "whats_new.json",
            "locales"} <= names
    assert set(stage.SHARED_MODULES) <= names
    assert "ui.py" not in names and "app_setup.py" not in names


def _imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module.split(".")[0]


def test_staged_modules_import_only_what_is_packaged(tmp_path):
    dest = stage.stage(str(tmp_path / "src"))
    local = {name[:-3] for name in os.listdir(dest) if name.endswith(".py")}
    packaged = {"kivy", "kivymd", "jnius", "android", "yt_dlp", "certifi"}
    for name in os.listdir(dest):
        if not name.endswith(".py"):
            continue
        for module in _imports(os.path.join(dest, name)):
            assert module in local or module in packaged or module in sys.stdlib_module_names, (
                f"{name} imports {module}, which the APK does not contain")


# --- settings -----------------------------------------------------------------------


def test_settings_round_trip(tmp_path):
    path = str(tmp_path / "settings.json")
    assert app_settings.load(path) == app_settings.AppSettings()
    changed = app_settings.AppSettings(theme="dark", accent="Teal", language="tr", fragments=8,
                                       audio_format="flac", auto_paste=False)
    app_settings.save(path, changed)
    assert app_settings.load(path) == changed
    assert not os.path.exists(path + ".tmp")


def test_settings_repair_bad_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"theme": "neon", "fragments": 99, "auto_paste": "yes", "language": "xx",'
                    ' "video_container": "webm", "audio_format": "opus", "unknown": 1}')
    settings = app_settings.load(str(path))
    default = app_settings.AppSettings()
    assert settings.theme == default.theme
    assert settings.fragments == app_settings.FRAGMENTS_MAX
    assert settings.auto_paste is default.auto_paste
    assert settings.language == default.language
    assert (settings.video_container, settings.audio_format) == ("mp4", "mp3")


@pytest.mark.parametrize("content", ["", "not json", "[1, 2]", "null"])
def test_settings_survive_a_broken_file(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content)
    assert app_settings.load(str(path)) == app_settings.AppSettings()


def test_settings_choices_match_the_worker():
    assert set(app_settings.VIDEO_CONTAINERS) == set(worker.MODE_FORMATS[worker.VIDEO_AUDIO])
    assert set(app_settings.AUDIO_FORMATS) == set(worker.MODE_FORMATS[worker.AUDIO_ONLY])
    default = app_settings.AppSettings()
    assert default.video_quality in worker.VIDEO_QUALITIES
    assert default.audio_quality in worker.AUDIO_QUALITIES


def test_download_speed_options_reach_yt_dlp():
    options = app_settings.download_speed_options(app_settings.AppSettings(fragments=6))
    logic.set_platform_options(options)
    ydl = logic.base_ydl_options()
    assert ydl["concurrent_fragment_downloads"] == 6
    assert ydl["http_chunk_size"] == 10 * 1024 * 1024


# --- history ------------------------------------------------------------------------


def test_history_newest_first_without_duplicates(tmp_path):
    path = str(tmp_path / "history.json")
    h = history.History(path)
    h.add("One", "/dl/one.mp4", now=1)
    h.add("Two", "/dl/two.mp3", kind="audio", now=2)
    h.add("One again", "/dl/one.mp4", now=3)
    assert [(e.title, e.time) for e in h.entries] == [("One again", 3), ("Two", 2)]
    reloaded = history.History(path)
    assert reloaded.entries == h.entries
    reloaded.remove("/dl/two.mp3")
    assert [e.path for e in history.History(path).entries] == ["/dl/one.mp4"]
    reloaded.clear()
    assert history.History(path).entries == []


def test_history_keeps_the_newest_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "LIMIT", 3)
    h = history.History(str(tmp_path / "history.json"))
    for n in range(5):
        h.add(f"T{n}", f"/dl/{n}.mp4", now=n)
    assert [e.title for e in h.entries] == ["T4", "T3", "T2"]


def test_history_existing_and_broken_files(tmp_path):
    kept = tmp_path / "kept.mp4"
    kept.write_text("x")
    h = history.History(str(tmp_path / "history.json"))
    h.add("Kept", str(kept))
    h.add("Gone", str(tmp_path / "gone.mp4"))
    assert [e.title for e in h.existing()] == ["Kept"]
    (tmp_path / "broken.json").write_text('[{"title": "x"}, "junk", {"title": "ok", "path": "/p"}]')
    assert [e.title for e in history.History(str(tmp_path / "broken.json")).entries] == ["ok"]


# --- texts and release notes ---------------------------------------------------------


def test_android_texts_exist_in_every_bundled_language():
    english = set(texts.TEXTS["en"])
    for code, catalog in texts.TEXTS.items():
        assert set(catalog) == english, f"{code} texts differ from English"
        assert code in i18n.LANGUAGES


def test_android_texts_fall_back_to_english_and_the_shared_catalog():
    try:
        i18n.set_language("tr")
        assert texts.t("nav.settings") == "Ayarlar"
        i18n.set_language("de")
        assert texts.t("nav.settings") == "Settings"
        assert texts.t("link.analyze") == i18n.tr("link.analyze")  # shared key
        assert texts.t("settings.fragments_hint", count=3).startswith("3 ")
    finally:
        i18n.set_language("en")


def test_texts_used_by_the_app_exist():
    import re
    app = os.path.join(ROOT, "android", "app")
    source = "".join(open(os.path.join(app, name), encoding="utf-8").read()
                     for name in ("main.py", "layout.py"))
    for key in set(re.findall(r'\bt\("([a-z_]+\.[A-Za-z_]+)"', source)):
        assert key in texts.TEXTS["en"] or key in i18n.load_catalog("en"), key
    for key in set(re.findall(r'\btr\("([a-z_]+\.[A-Za-z_]+)"', source)):
        assert key in i18n.load_catalog("en"), key


def test_release_notes_cover_the_app_version():
    import json
    with open(os.path.join(ROOT, "android", "app", "whats_new.json"), encoding="utf-8") as f:
        notes = json.load(f)
    spec = open(os.path.join(ROOT, "android", "buildozer.spec"), encoding="utf-8").read()
    version = re.search(r"^version = (\S+)", spec, re.M).group(1)
    main = open(os.path.join(ROOT, "android", "app", "main.py"), encoding="utf-8").read()
    assert f'APP_VERSION = "{version}"' in main
    assert notes[0]["version"] == version
    for release in notes:
        assert release["en"] and len(release["tr"]) == len(release["en"])


@pytest.mark.skipif(sys.platform == "win32", reason="Android is POSIX")
def test_forward_native_stderr_catches_child_programs(tmp_path):
    # In a separate process, because it takes over file descriptor 2.
    import subprocess
    script = tmp_path / "probe.py"
    script.write_text(
        "import subprocess, sys, time\n"
        f"sys.path.insert(0, {os.path.join(ROOT, 'android', 'app')!r})\n"
        "import android_env\n"
        "seen = []\n"
        "android_env.forward_native_stderr(seen.append)\n"
        "subprocess.run([sys.executable, '-c', 'import sys; sys.stderr.write(\"boom\\\\n\\\\n\")'])\n"
        "for _ in range(50):\n"
        "    if seen: break\n"
        "    time.sleep(0.05)\n"
        "print(seen)\n")
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "['boom']"


# --- crash_report -----------------------------------------------------------------

def test_crash_report_is_empty_after_a_clean_run(tmp_path):
    import crash_report
    assert crash_report.CrashReport(str(tmp_path)).take_previous() == ""


def test_crash_report_keeps_python_errors_until_the_next_start(tmp_path):
    import crash_report
    report = crash_report.CrashReport(str(tmp_path / "data"))
    try:
        {}["missing"]
    except KeyError as e:
        text = report.record(e, where="main loop")
    assert "KeyError: 'missing'" in text and "main loop" in text
    again = crash_report.CrashReport(str(tmp_path / "data"))
    previous = again.take_previous()
    assert "KeyError: 'missing'" in previous
    assert again.take_previous() == ""  # shown once


@pytest.mark.skipif(sys.platform == "win32", reason="Android is POSIX")
def test_crash_report_catches_a_native_crash(tmp_path):
    # In a separate process, because the process has to die.
    import subprocess
    script = tmp_path / "probe.py"
    script.write_text(
        "import ctypes, sys\n"
        f"sys.path.insert(0, {os.path.join(ROOT, 'android', 'app')!r})\n"
        "import crash_report\n"
        f"crash_report.CrashReport({str(tmp_path)!r}).watch_native()\n"
        "def deep_in_a_library():\n"
        "    ctypes.string_at(0)\n"
        "deep_in_a_library()\n")
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=30)
    assert out.returncode != 0
    import crash_report
    previous = crash_report.CrashReport(str(tmp_path)).take_previous()
    assert "Segmentation fault" in previous and "deep_in_a_library" in previous


def test_new_log_lines_starts_after_the_last_reported_line():
    import crash_report
    log = "--------- beginning of crash\nE one\nE two\nE three\n"
    assert crash_report.new_log_lines(log, "") == ("E one\nE two\nE three", "E three")
    assert crash_report.new_log_lines(log, "E two") == ("E three", "E three")
    assert crash_report.new_log_lines(log, "E three") == ("", "E three")
    assert crash_report.new_log_lines(log, "gone from the buffer") == ("E one\nE two\nE three", "E three")
    assert crash_report.new_log_lines("", "E three") == ("", "E three")


def test_system_crashes_are_reported_once(tmp_path):
    import crash_report
    report = crash_report.CrashReport(str(tmp_path))
    assert report.new_system_crashes("F libc: Fatal signal 11") == "F libc: Fatal signal 11"
    assert report.new_system_crashes("F libc: Fatal signal 11") == ""
    assert report.new_system_crashes("F libc: Fatal signal 11\nE AndroidRuntime: FATAL EXCEPTION") == \
        "E AndroidRuntime: FATAL EXCEPTION"
    assert "FATAL EXCEPTION" in report.take_previous(extra="E AndroidRuntime: FATAL EXCEPTION")
    assert crash_report.tail("a\nb\nc", 2) == "b\nc"


def test_diagnostics_put_the_app_log_first_without_unpacking_noise():
    import crash_report
    android = "\n".join([f"09-26 16:26:26.914 1 2 V python  : extracting _python_bundle/x{i}.pyc"
                          for i in range(5000)] + ["09-26 16:27:00.000 1 2 I python  : UDSELFTEST tools ok"])
    text = crash_report.diagnostics("0.2.5", ["Fetching...", "Sign in to confirm you're not a bot"], android)
    assert text.startswith("UniversalDownloader 0.2.5\n\nApp log:\nFetching...")
    assert "extracting" not in text
    assert text.rstrip().endswith("UDSELFTEST tools ok")



# --- YouTube sign-in ----------------------------------------------------------------

SIGNED_IN = "PREF=f6=40000000; SID=abc; SAPISID=xyz/123; __Secure-3PAPISID=xyz/123; LOGIN_INFO=AFm:QUQ="


def test_youtube_cookie_header_is_parsed():
    import youtube_login
    cookies = youtube_login.parse_cookie_header(SIGNED_IN)
    assert cookies["SAPISID"] == "xyz/123" and cookies["LOGIN_INFO"] == "AFm:QUQ="
    assert youtube_login.signed_in(cookies)
    assert not youtube_login.signed_in(youtube_login.parse_cookie_header("PREF=1; VISITOR_INFO1_LIVE=x"))
    assert youtube_login.parse_cookie_header(None) == {}


def test_youtube_cookies_are_saved_for_yt_dlp(tmp_path):
    import http.cookiejar
    import youtube_login
    assert youtube_login.saved(str(tmp_path)) is None
    assert youtube_login.save(str(tmp_path), SIGNED_IN)
    path = youtube_login.saved(str(tmp_path))
    jar = http.cookiejar.MozillaCookieJar(path)
    jar.load()  # the format yt-dlp's cookiefile reads
    values = {c.name: (c.value, c.domain, c.secure) for c in jar}
    assert values["SAPISID"] == ("xyz/123", ".youtube.com", True)
    assert len(values) == 5
    youtube_login.forget(str(tmp_path))
    assert youtube_login.saved(str(tmp_path)) is None


def test_signed_out_session_is_not_saved(tmp_path):
    import youtube_login
    assert not youtube_login.save(str(tmp_path), "PREF=1; YSC=abc")
    assert not os.path.exists(youtube_login.cookie_path(str(tmp_path)))


def test_cookie_file_reaches_yt_dlp(tmp_path, fake_ydl, manager):
    import youtube_login
    youtube_login.save(str(tmp_path), SIGNED_IN)
    logic.set_platform_options({"cookiefile": youtube_login.saved(str(tmp_path))})
    manager.fetch_info("https://youtu.be/abc")
    assert fake_ydl.instances[0].opts["cookiefile"].endswith(youtube_login.COOKIE_FILE)


# --- browser_route: YouTube through the phone's browser engine -----------------------


class FakeBridge:
    """Answers like BrowserFetch.java would, without a WebView."""

    def __init__(self, status=200, body=b"<html>ok</html>", headers=None, token="TOKEN"):
        self.status, self.body, self.token = status, body, token
        self.headers = headers or {"content-type": "text/html", "content-encoding": "gzip"}
        self.requests, self.bindings = [], []

    def fetch(self, method, url, headers, body_base64, timeout, credentials="include"):
        import base64
        import json
        self.requests.append((method, url, headers, body_base64, credentials))
        return [str(self.status), json.dumps(self.headers), base64.b64encode(self.body).decode(), url]

    def mint(self, binding, timeout):
        self.bindings.append(binding)
        return ["1", self.token] if self.token else ["0", "mint: BotGuard did not load"]


@pytest.fixture
def route():
    import browser_route
    yield browser_route
    browser_route.disable()


def test_route_takes_only_youtube_pages_and_api(route):
    assert route.wants("https://www.youtube.com/watch?v=abc")
    assert route.wants("https://www.youtube.com/youtubei/v1/player?prettyPrint=false")
    assert not route.wants("https://www.youtube.com/s/player/abc/player_ias.vflset/en_US/base.js")
    assert not route.wants("https://rr3---sn-abc.googlevideo.com/videoplayback?id=1")
    assert not route.wants("https://m.youtube.com/watch?v=abc")
    assert not route.wants("http://www.youtube.com/watch?v=abc")


def test_route_leaves_browser_headers_to_the_browser(route):
    headers = route.browser_headers({"User-Agent": "yt-dlp", "Cookie": "a=b", "Origin": "https://www.youtube.com",
                                     "Sec-Fetch-Mode": "navigate", "X-YouTube-Client-Name": "1",
                                     "Content-Type": "application/json"})
    assert headers == {"X-YouTube-Client-Name": "1", "Content-Type": "application/json"}
    assert route.response_headers('{"content-encoding": "br", "content-length": "9", "x-a": "1"}') == {"x-a": "1"}


def test_route_fetches_the_watch_page_without_old_cookies(route):
    assert route.credentials("https://www.youtube.com/watch?v=abc&bpctr=1") == "omit"
    assert route.credentials("https://www.youtube.com/youtubei/v1/player") == "include"


def test_desktop_user_agent_keeps_the_webview_version(route):
    agent = ("Mozilla/5.0 (Linux; Android 13; 22111317PG Build/TKQ1; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Version/4.0 Chrome/129.0.6668.100 Mobile Safari/537.36")
    desktop = route.desktop_user_agent(agent)
    assert "Chrome/129.0.6668.100" in desktop and "Android" not in desktop and "Mobile" not in desktop
    assert "Chrome/" in route.desktop_user_agent(None)


def test_yt_dlp_sends_youtube_requests_through_the_route_only_when_enabled(route):
    import yt_dlp
    from yt_dlp.networking import Request
    bridge = FakeBridge()
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        route.enable(bridge)
        before = route.request_count()
        with ydl.urlopen(Request("https://www.youtube.com/youtubei/v1/player", data=b'{"videoId": "abc"}',
                                 headers={"User-Agent": "x", "X-YouTube-Client-Name": "1"})) as response:
            assert response.read() == b"<html>ok</html>"
            assert response.status == 200
            assert "content-encoding" not in {k.lower() for k in response.headers.keys()}
        method, url, headers, body, credentials = bridge.requests[0]
        assert method == "POST" and url.endswith("/youtubei/v1/player")
        assert headers.get("X-Youtube-Client-Name", headers.get("X-YouTube-Client-Name")) == "1"
        assert not any(name.lower() == "user-agent" for name in headers)
        assert body == "eyJ2aWRlb0lkIjogImFiYyJ9" and credentials == "include"
        assert route.request_count() == before + 1
        route.disable()
        handler = ydl._request_director.handlers["UDBrowser"]
        with pytest.raises(Exception):
            handler.validate(Request("https://www.youtube.com/watch?v=abc"))
    assert len(bridge.requests) == 1


def test_route_reports_http_errors_like_yt_dlp_does(route):
    import yt_dlp
    from yt_dlp.networking.exceptions import HTTPError
    route.enable(FakeBridge(status=429, body=b"slow down"))
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl, pytest.raises(HTTPError) as error:
        ydl.urlopen("https://www.youtube.com/watch?v=abc")
    assert error.value.status == 429


def test_route_failure_is_a_transport_error(route):
    import yt_dlp
    from yt_dlp.networking.exceptions import TransportError

    class Broken(FakeBridge):
        def fetch(self, *args, **kwargs):
            return ["0", "fetch: TypeError: Failed to fetch"]

    route.enable(Broken())
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl, pytest.raises(TransportError, match="Failed to fetch"):
        ydl.urlopen("https://www.youtube.com/watch?v=abc")


def _pot_request(route, client="WEB", video_id="dQw4w9WgXcQ"):
    from yt_dlp.extractor.youtube.pot.provider import PoTokenContext, PoTokenRequest
    return PoTokenRequest(context=PoTokenContext.GVS, innertube_context={"client": {"clientName": client}},
                          video_id=video_id, visitor_data="Cgt2aXNpdG9y", _gvs_bind_to_video_id=True)


def _provider(route):
    return route.BrowserPTP(ie=None, logger=None, settings={})


def test_po_tokens_come_from_the_browser_page_uncached(route):
    bridge = FakeBridge(token="MlTOKEN")
    route.enable(bridge)
    provider = _provider(route)
    assert provider.is_available()
    response = provider._real_request_pot(_pot_request(route))
    assert response.po_token == "MlTOKEN" and response.expires_at == 0
    assert bridge.bindings == ["dQw4w9WgXcQ"]


def test_po_token_provider_is_off_without_the_route_and_reports_failures(route):
    from yt_dlp.extractor.youtube.pot.provider import PoTokenProviderError
    provider = _provider(route)
    assert not provider.is_available()
    route.enable(FakeBridge(token=None))
    with pytest.raises(PoTokenProviderError, match="BotGuard"):
        provider._real_request_pot(_pot_request(route))


def test_browser_page_defines_what_the_bridges_call(route):
    for name in ("window.__udFetch", "window.__udMint", "UdBridge.done", "UdBridge.fail", "GenerateIT"):
        assert name in route.PAGE_HTML
    assert route.PAGE_HTML.startswith("<!doctype html>")


def test_browser_fetch_java_matches_the_python_side(route):
    java = open(os.path.join(ROOT, "android", "java", "io", "github", "dordeorz", "universaldownloader",
                             "BrowserFetch.java"), encoding="utf-8").read()
    assert "package io.github.dordeorz.universaldownloader;" in java
    assert '"UdBridge"' in java and "@JavascriptInterface" in java
    assert "public static boolean start(" in java and "public static String[] run(" in java
    spec = open(os.path.join(ROOT, "android", "buildozer.spec"), encoding="utf-8").read()
    assert re.search(r"^android\.add_src = java$", spec, re.M)
    assert "io.github.dordeorz.universaldownloader.BrowserFetch" in open(
        os.path.join(ROOT, "android", "app", "browser_route.py"), encoding="utf-8").read()


def test_browser_route_texts_are_translated():
    for language in ("en", "tr"):
        table = texts.TEXTS[language]
        for key in ("youtube.via_browser", "youtube.browser_count", "youtube.ok_button"):
            assert table[key]
        assert "{count}" in table["youtube.browser_count"]


def test_webview_minidump_does_not_push_the_crash_out_of_the_report():
    import crash_report
    log = "\n".join(["09-26 17:54:06.100  6423  6423 E AndroidRuntime: FATAL EXCEPTION: main",
                     "09-26 17:54:07.188  6423  6423 F crashpad: -----BEGIN CRASHPAD MINIDUMP-----"]
                    + ["09-26 17:54:07.206  6423  6423 F crashpad: )iyJD'EEst-x1NwT~jeR&N7T$ut]4(O7"] * 500
                    + ["09-26 17:54:07.300  6423  6423 F crashpad: -----END CRASHPAD MINIDUMP-----"])
    new, last = crash_report.new_log_lines(log, "")
    assert "FATAL EXCEPTION" in crash_report.tail(new, 150)
    assert len(new.splitlines()) == 3 and "END CRASHPAD" in last
