"""The Android preview's UI-free parts: tool links, job worker, staging.

The Kivy screen itself (android/app/main.py) only runs on a device; the
emulator job in .github/workflows/android.yml covers it.
"""

import ast
import os
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
import stage  # noqa: E402
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


def test_not_on_android_in_tests():
    assert not android_env.on_android()


# --- worker -------------------------------------------------------------------------


def test_build_options():
    video = worker.build_options(worker.VIDEO_AUDIO, "720p", "/dl")
    assert video == {"mode": "Video + Audio", "format": "mp4", "quality": "720p", "save_path": "/dl",
                     "trim_start": None, "trim_end": None}
    audio = worker.build_options(worker.AUDIO_ONLY, "720p", "/dl", audio_format="m4a")
    assert (audio["format"], audio["quality"]) == ("m4a", "Best")
    assert worker.build_options(worker.AUDIO_ONLY, "Best", "/dl")["format"] == "mp3"
    with pytest.raises(ValueError):
        worker.build_options("Video Only", "Best", "/dl")


def test_offered_choices_are_valid_format_plans():
    import formats
    for quality in worker.VIDEO_QUALITIES:
        formats.build_format_plan(worker.VIDEO_AUDIO, "mp4", quality)
    for fmt in ("mp3", "m4a"):
        formats.build_format_plan(worker.AUDIO_ONLY, fmt, "Best")


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
    assert session.download(analysis, worker.build_options(worker.VIDEO_AUDIO, "Best", "/dl"))
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
    session.download(analysis, worker.build_options(worker.VIDEO_AUDIO, "Best", "/dl"))
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
    assert {"main.py", "worker.py", "android_env.py", "icon.png", "locales"} <= names
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
    packaged = {"kivy", "jnius", "android", "yt_dlp"}
    for name in os.listdir(dest):
        if not name.endswith(".py"):
            continue
        for module in _imports(os.path.join(dest, name)):
            assert module in local or module in packaged or module in sys.stdlib_module_names, (
                f"{name} imports {module}, which the APK does not contain")
