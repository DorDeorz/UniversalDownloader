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

    def fetch_info(self, url, log_callback=None):
        log_callback("fetching")
        return self.info

    def download_video(self, url, options, progress_hook=None, log_callback=None, title=None, cancel_event=None):
        self.calls.append((url, options))
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
                           cancel_event=None):
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


# --- staging ------------------------------------------------------------------------


def test_stage_copies_app_and_shared_modules(tmp_path):
    dest = stage.stage(str(tmp_path / "src"))
    names = set(os.listdir(dest))
    assert {"main.py", "worker.py", "android_env.py", "layout.py", "whats_new.json", "icon.png",
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
