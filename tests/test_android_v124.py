"""Orbida 1.2.4 on Android: the review suggestions AN-7 and B3-B6.

The pure-Python parts are tested directly; the screens run in a KivyMD
window (a Linux display is needed) in a child process, like the probes in
test_android.py, so a Kivy window never opens inside the test process.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys

import pytest

import events
from playlist import AnalysisResult, QueueItem

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "android", "app")
sys.path.insert(0, APP)

import app_settings  # noqa: E402
import history  # noqa: E402
import i18n  # noqa: E402
import self_update  # noqa: E402
import texts  # noqa: E402
import worker  # noqa: E402

needs_display = pytest.mark.skipif(sys.platform == "win32" or not os.environ.get("DISPLAY"),
                                   reason="needs a Linux display")


# --- History: one write per job, saved sizes, search, undo (B5-1, B5-3, B3-10) ----------------


def test_history_saves_once_per_job_and_every_few_entries(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    log = history.History(str(path))
    writes = []
    real = log.save
    monkeypatch.setattr(log, "save", lambda: (writes.append(1), real()))
    for n in range(history.SAVE_EVERY + 3):
        log.add(f"T{n}", f"/dl/{n}.mp4", save=False)
    assert len(writes) == 1  # the SAVE_EVERY-th entry wrote the file
    log.flush()
    assert len(writes) == 2 and log.unsaved == 0
    log.flush()  # nothing new: nothing written
    assert len(writes) == 2
    assert len(history.History(str(path)).entries) == history.SAVE_EVERY + 3


def test_history_keeps_the_size_so_the_week_needs_no_file_lookups(tmp_path, monkeypatch):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x" * 1234)
    log = history.History(str(tmp_path / "history.json"))
    entry = log.add("Clip", str(clip), now=1000)
    assert entry.size == 1234
    assert history.History(str(tmp_path / "history.json")).entries[0].size == 1234
    looked = []
    monkeypatch.setattr(history.os.path, "getsize", lambda p: looked.append(p) or 0)
    assert log.recent(7, now=2000) == (1, 1234) and looked == []


def test_history_search_and_restore(tmp_path):
    log = history.History(str(tmp_path / "history.json"))
    log.add("Band - Song (Live)", "/dl/song.mp3", url="https://youtu.be/a", kind="audio", now=1)
    log.add("Cat video", "/dl/cat.mp4", url="https://example.com/cat", now=2)
    assert [e.title for e in log.search("song live")] == ["Band - Song (Live)"]
    assert [e.title for e in log.search("CAT")] == ["Cat video"]
    assert len(log.search("  ")) == 2
    removed = log.remove("/dl/song.mp3")
    assert removed[1] == 1 and [e.title for e in log.entries] == ["Cat video"]
    assert log.remove("/dl/none.mp4") is None
    log.restore(*removed)
    assert [e.title for e in history.History(str(tmp_path / "history.json")).entries] == [
        "Cat video", "Band - Song (Live)"]


# --- Updates: channel and "Skip this version" (B4-9) --------------------------------------------


def _release(tag, prerelease=False):
    return {"tag_name": tag, "prerelease": prerelease, "draft": False, "body": "", "html_url": "",
            "assets": [{"name": f"Orbida-{tag[8:]}.apk", "size": 1, "browser_download_url": "https://x/a.apk"}]}


def test_beta_channel_offers_pre_releases_and_a_skipped_version_is_passed_over():
    releases = [_release("orbida-v1.3.0", prerelease=True), _release("orbida-v1.2.5"), _release("orbida-v1.2.4"),
                _release("orbida-test-77", prerelease=True)]
    assert self_update.pick(releases, "1.2.3").version == "1.2.5"
    beta = self_update.pick(releases, "1.2.3", channel="beta")
    assert beta.version == "1.3.0" and beta.prerelease
    assert self_update.pick(releases, "1.2.3", skipped="1.2.5").version == "1.2.4"
    assert self_update.pick(releases[1:2], "1.2.3", skipped="1.2.5") is None


def test_update_settings_are_kept_valid(tmp_path):
    path = str(tmp_path / "settings.json")
    app_settings.save(path, app_settings.AppSettings(update_channel="beta", skipped_version="1.2.5"))
    loaded = app_settings.load(path)
    assert (loaded.update_channel, loaded.skipped_version) == ("beta", "1.2.5")
    assert app_settings.AppSettings(update_channel="nightly").normalized().update_channel == "stable"


# --- Subtitle languages, SponsorBlock parts (B4-6, B4-7) -----------------------------------------


def test_sponsorblock_parts_and_subtitle_settings(tmp_path):
    settings = app_settings.AppSettings(sponsorblock_categories="intro,nonsense,sponsor", subtitle_langs="tr, en",
                                        subtitle_embed=True).normalized()
    assert settings.sponsorblock_categories == "sponsor,intro"  # known ones, in the usual order
    path = str(tmp_path / "settings.json")
    app_settings.save(path, settings)
    loaded = app_settings.load(path)
    assert (loaded.subtitle_langs, loaded.subtitle_embed) == ("tr, en", True)
    assert app_settings.AppSettings().sponsorblock_categories.split(",")[0] == "sponsor"


# --- Remembered playlist selection (B4-8) --------------------------------------------------------


def test_a_playlist_remembers_the_entries_ticked_last_time(tmp_path):
    path = str(tmp_path / "choices.json")
    items = [QueueItem(url=f"https://e.com/{n}", title=str(n)) for n in range(4)]
    assert app_settings.remembered_choice(None, items) is None
    app_settings.save_playlist_choice(path, "https://e.com/list", [i.url for i in items[:3]], [items[1].url])
    saved = app_settings.load_playlist_choices(path)["https://e.com/list"]
    # 0 and 2 were unticked, 1 ticked; 3 is new (ticked unless downloaded before).
    assert [i.title for i in app_settings.remembered_choice(saved, items)] == ["1", "3"]
    assert [i.title for i in app_settings.remembered_choice(saved, items, downloaded_before=[items[3]])] == ["1"]


def test_only_the_newest_playlists_are_remembered(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "PLAYLIST_CHOICES_KEPT", 2)
    path = str(tmp_path / "choices.json")
    for name in ("a", "b", "c"):
        app_settings.save_playlist_choice(path, name, [], [])
    assert list(app_settings.load_playlist_choices(path)) == ["b", "c"]


# --- Analysis: progress, picture and size (B4-12) ------------------------------------------------


class _Manager:
    def __init__(self, info):
        self.info = info

    def fetch_info(self, url, log_callback=None, cancel_event=None, progress=None):
        progress(100, 850)
        return self.info


def _drain(queue):
    out = []
    while queue.pending():
        out.append(queue._queue.get_nowait())
    return out


def test_analysis_reports_how_far_a_long_list_is_read_and_a_preview():
    info = {"title": "Clip", "webpage_url": "https://e.com/v", "duration": 100, "thumbnail": "https://i/x.jpg",
            "formats": [{"format_id": "v", "vcodec": "avc1", "acodec": "none", "height": 720, "filesize": 9_000_000},
                        {"format_id": "a", "vcodec": "none", "acodec": "mp4a", "filesize": 1_000_000}]}
    queue = events.EventQueue()
    session = worker.Session(_Manager(info), queue)
    assert session.analyze("https://e.com/v")
    session.wait(5)
    got = _drain(queue)
    assert got[0].kind == events.ANALYSIS_PROGRESS and got[0].payload == {"count": 100, "total": 850}
    done = got[-1]
    assert done.kind == events.ANALYSIS_DONE
    assert done.payload["preview"]["thumbnail"] == "https://i/x.jpg"
    assert worker.estimate_size(done.payload["preview"]["info"], worker.VIDEO_AUDIO) == 10_000_000


def test_size_estimates():
    formats = [
        {"vcodec": "avc1", "acodec": "none", "height": 1080, "filesize": 50_000_000},
        {"vcodec": "avc1", "acodec": "none", "height": 720, "filesize_approx": 20_000_000},
        {"vcodec": "none", "acodec": "opus", "tbr": 128},
        {"vcodec": "avc1", "acodec": "mp4a", "height": 360, "filesize": 8_000_000},
    ]
    info = {"duration": 100, "formats": formats}
    audio = 128 * 1000 // 8 * 100  # from the bitrate: 1.6 MB
    assert worker.estimate_size(info, worker.VIDEO_AUDIO) == 50_000_000 + audio
    assert worker.estimate_size(info, worker.VIDEO_AUDIO, "720p") == 20_000_000 + audio
    assert worker.estimate_size(info, worker.VIDEO_AUDIO, "360p") == 8_000_000  # one file with both
    assert worker.estimate_size(info, worker.AUDIO_ONLY, "192 kbps") == 192 * 1000 // 8 * 100
    assert worker.estimate_size(info, worker.AUDIO_ONLY) == audio  # Best: the largest audio stream
    assert worker.estimate_size({"formats": []}, worker.VIDEO_AUDIO) == 0
    playlist_result = AnalysisResult(title="L", items=[QueueItem("u", "a")], is_playlist=True)
    assert worker.preview(info, playlist_result) is None
    single = AnalysisResult(title="V", items=[QueueItem("u", "a")])
    assert worker.preview({**info, "thumbnail": "http://plain"}, single)["thumbnail"] == ""


# --- Version in one place (B5-8) and the build ------------------------------------------------------


def test_landscape_and_battery_permission_are_in_the_build():
    spec = open(os.path.join(ROOT, "android", "buildozer.spec"), encoding="utf-8").read()
    assert re.search(r"^orientation = portrait, landscape", spec, re.M)
    assert re.search(r"^android\.permissions = .*\bREQUEST_IGNORE_BATTERY_OPTIMIZATIONS\b", spec, re.M)
    workflow = open(os.path.join(ROOT, ".github", "workflows", "android.yml"), encoding="utf-8").read()
    assert "from version import __version__" in workflow


def test_insets_use_the_new_api_from_android_11():
    import android_env

    class Bars:
        left, top, right, bottom = 1, 2, 3, 4

    class Old:
        def getSystemWindowInsetLeft(self): return 5
        def getSystemWindowInsetTop(self): return 6
        def getSystemWindowInsetRight(self): return 7
        def getSystemWindowInsetBottom(self): return 8

    assert android_env.insets_of(Old(), 29) == (5, 6, 7, 8)
    source = open(os.path.join(APP, "android_env.py"), encoding="utf-8").read()
    assert "types.systemBars() | types.displayCutout()" in source
    login = open(os.path.join(APP, "youtube_login.py"), encoding="utf-8").read()
    assert "getSystemWindowInset" not in login and "android_env.insets_of(" in login
    assert "setAlgorithmicDarkeningAllowed" in login and "setForceDark" in login


def test_licenses_name_what_the_apk_carries():
    import licenses
    text = licenses.text()
    for name in ("yt-dlp", "FFmpeg", "QuickJS", "Kivy", "KivyMD", "certifi", "mutagen", "Python"):
        assert name in text
    assert "LGPL v3" in text


def test_new_android_texts_exist_in_every_language():
    with open(os.path.join(APP, "texts_languages.json"), encoding="utf-8") as f:
        more = json.load(f)
    keys = ("battery.title", "battery.hint", "battery.free", "history.cleared", "history.no_link",
            "home.more_options", "home.fewer_options", "home.options_hint", "home.skipped_title",
            "home.skipped_why", "log.copied", "settings.search", "settings.sponsor_parts",
            "settings.sponsor_all", "settings.sponsor_none", "settings.sub_langs_auto")
    for code in i18n.LANGUAGES:
        found = texts.TEXTS.get(code) or more.get(code, {})
        missing = [k for k in keys if not found.get(k)]
        assert not missing, (code, missing)


def test_emulator_test_taps_by_name_on_several_android_versions():
    script = open(os.path.join(ROOT, "android", "emulator_ui_test.sh"), encoding="utf-8").read()
    taps = re.findall(r"^\s*tap_id \"?([\w.]+)", script, re.M)
    assert {"btn_paste", "nav.history", "nav.settings", "settings.theme", "choice.light", "nav.home",
            "url"} <= set(taps)
    assert not re.search(r"^\s*tap \"", script, re.M)  # no coordinate taps left
    workflow = open(os.path.join(ROOT, ".github", "workflows", "android.yml"), encoding="utf-8").read()
    assert re.search(r"api-level: \[24, 33, 34, 35\]", workflow)


# --- The screens (KivyMD in a child process) ------------------------------------------------------


def _run_probe(tmp_path, probe, env_extra=None, timeout=240):
    if importlib.util.find_spec("kivymd") is None:  # found, not imported: that would open a window here
        pytest.skip("KivyMD (the Android UI toolkit) is not installed")
    script = tmp_path / "probe.py"
    script.write_text(probe.replace("{APP}", repr(APP)).replace("{ROOT}", repr(ROOT)), encoding="utf-8")
    (tmp_path / "config").mkdir(exist_ok=True)
    env = dict(os.environ, KIVY_HOME=str(tmp_path / "kivy"), XDG_CONFIG_HOME=str(tmp_path / "config"),
               HOME=str(tmp_path), KIVY_NO_ARGS="1", **(env_extra or {}))
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=timeout, env=env,
                         cwd=tmp_path)
    line = next((x for x in out.stdout.splitlines() if x.startswith("UIPROBE ")), None)
    assert line, out.stdout[-4000:] + out.stderr[-4000:]
    return json.loads(line[len("UIPROBE "):]), out.stdout


_START = """
import json, os, sys, time
sys.path[:0] = [{APP}, {ROOT}]
from kivy.config import Config
Config.set("graphics", "width", "412")
Config.set("graphics", "height", "892")
import md_patches
md_patches.disable_hover()
import main
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivymd.uix.dialog import MDDialog
from lite import LiteRow
from playlist import AnalysisResult, QueueItem
from results import ItemResult, ItemStatus, JobSummary

app = main.UniversalDownloaderApp()
result = {}

def dialogs():
    return [w for w in Window.children if isinstance(w, MDDialog) and w._is_open]

def close_dialogs():
    for d in dialogs():
        d.dismiss()

def rows_of(widget):
    return [w for w in widget.walk() if isinstance(w, LiteRow)]

def ancestors(widget):
    out = []
    while widget.parent is not None and widget.parent is not widget:
        widget = widget.parent
        out.append(widget)
    return out

announced = []
main.android_env.announce = lambda text: announced.append(text)

def finish(*_):
    print("UIPROBE " + json.dumps(result), flush=True)
    app.stop()

orig = app.on_start
def on_start():
    orig()
    Clock.schedule_once(probe, 2)
app.on_start = on_start
"""

_HOME_PROBE = _START + """
class Session:
    paused = False
    def __init__(self):
        self.downloads = []
        self.cancelled = False
    def download(self, analysis, options):
        self.downloads.append(([i.url for i in analysis.items], options))
        return True
    def cancel(self):
        self.cancelled = True
    def pause(self):
        self.paused = True
    def resume(self):
        self.paused = False
    def analyze(self, text, keep_mix=False):
        return True
    busy = False

def probe(*_):
    ids = app.ids
    # B3-1: Download stays outside the scrolling page.
    result["fixed_bar"] = ids.home_scroll not in ancestors(ids.btn_download)
    # B3-2: the options are folded until opened, and that is remembered.
    result["options_folded"] = ids.options_box.parent is None
    app.toggle_options()
    result["options_open"] = ids.options_box.parent is not None and app.settings.show_options
    app.toggle_options()
    # B3-6: an error stays in a card until it is closed or the next link.
    app._on_analysis_failed("HTTP Error 404: Not Found")
    result["error_card"] = (ids.error_card.parent is not None, ids.error_card.ids.error_text.text)
    app.hide_error()
    result["error_closed"] = ids.error_card.parent is None
    # AN-7, B5-6: the log keeps LOG_LINES, draws the newest LOG_SHOWN in small labels, copies all.
    for n in range(main.LOG_LINES + 200):
        app.log(f"line {n}")
    app.toggle_details()
    chunks = [w for w in ids.log.children]
    result["log"] = {"kept": len(app._log_lines), "chunks": len(chunks),
                     "last": chunks[0].text.splitlines()[-1], "first_shown": chunks[-1].text.splitlines()[0],
                     "wraps": all(c.text_size[0] == c.width for c in chunks)}
    app.log("one more")
    app._render_log()
    result["log_appended"] = ids.log.children[0].text.splitlines()[-1]
    app.copy_log()
    copied = Clipboard.paste().splitlines()
    result["copied"] = [len(copied), copied[-1]]
    app.clear_log()
    result["cleared"] = [len(app._log_lines), len(ids.log.children)]
    app.toggle_details()
    # B3-4: a playlist's left-out entries, with the reason.
    session = app.session = Session()
    items = [QueueItem(url=f"https://e.com/{n}", title=f"Video {n}") for n in range(3)]
    gone = QueueItem(url="https://e.com/x", title="Gone", skip_reason="Private video")
    app.ids.url.text = "https://e.com/list"
    app._on_analysis_done(AnalysisResult(title="List", items=items, skipped=[gone], is_playlist=True), "")
    result["skipped_button"] = (ids.btn_skipped.parent is not None, ids.skipped_text.text)
    app.show_skipped()
    result["skipped_rows"] = [(r.headline, r.supporting) for r in rows_of(dialogs()[0])]
    close_dialogs()
    # B3-8: the waiting links, moved up and taken out.
    app.link_queue = ["https://a.com/1", "https://a.com/2", "https://a.com/3"]
    app._show_link_queue()
    app.show_link_queue()
    result["queue_rows"] = [r.headline for r in rows_of(dialogs()[0])]
    app._named["choice.2"].dispatch("on_release")  # the third link...
    app._named["choice.up"].dispatch("on_release")  # ...moves up
    result["queue_moved"] = list(app.link_queue)
    close_dialogs()
    app.show_link_queue()
    app._named["choice.0"].dispatch("on_release")
    app._named["choice.remove"].dispatch("on_release")
    result["queue_removed"] = list(app.link_queue)
    close_dialogs()
    app.link_queue = []
    app._show_link_queue()
    # B3-5, B4-5: after a download: open, share, retry the failed one, download again.
    app.download_dir = os.getcwd()
    open("done.mp4", "wb").write(b"x")
    app.chosen = list(items[:2])
    app.analysis_url = "https://e.com/list"
    app.download()
    result["started"] = session.downloads[-1][0]
    app._on_item_done(ItemResult(url=items[0].url, title="Video 0", status=ItemStatus.COMPLETED,
                                 path=os.path.abspath("done.mp4")))
    summary = JobSummary()
    ok = ItemResult(url=items[0].url, title="Video 0", status=ItemStatus.COMPLETED, path="done.mp4")
    bad = ItemResult(url=items[1].url, title="Video 1", status=ItemStatus.FAILED, error="HTTP Error 403: Forbidden")
    bad.source = items[1].as_dict()
    summary.add(ok)
    summary.add(bad)
    app._on_job_done(summary)
    result["done_row"] = {n: getattr(ids, n).parent is not None
                          for n in ("done_row", "btn_open_file", "btn_share_file", "btn_retry", "btn_again")}
    result["retry_text"] = ids.retry_text.text
    result["failed_card"] = ids.error_card.parent is not None
    result["history_saved"] = [e.title for e in main.history.History(app.history.path).entries]
    app.retry_failed()
    result["retried"] = session.downloads[-1][0]
    result["retry_options_kept"] = session.downloads[-1][1] == session.downloads[0][1]
    # B4-1: the notification's buttons pause, resume and cancel.
    class Notice:
        running = True
        action = ""
        def take_action(self):
            action, self.action = self.action, ""
            return action
        def update(self, *a, **k):
            pass
        def stop(self, *a, **k):
            self.running = False
    app._notice = notice = Notice()
    app.job, app._cancelled = "download", False
    notice.action = "pause"
    app._poll_notice()
    paused = session.paused
    notice.action = "resume"
    app._poll_notice()
    resumed = not session.paused
    notice.action = "cancel"
    app._poll_notice()
    result["notice_buttons"] = [paused, resumed, session.cancelled]
    app._notice = None
    app.job = None
    app.set_busy(False)
    # B6-2: notification permission is asked once.
    asked = []
    main.android_env.ask_notification_permission = lambda: asked.append(1)
    app._notice = Notice()
    app._asked_notifications = False
    app._ask_notifications()
    app._ask_notifications()
    result["permission_asked"] = len(asked)
    app._notice = None
    # B4-12: picture and size of a single video.
    single = AnalysisResult(title="Clip", items=[QueueItem(url="https://e.com/v", title="Clip")])
    preview = {"thumbnail": "https://127.0.0.1:9/x.jpg", "duration": 100,
               "info": {"duration": 100, "formats": [{"vcodec": "avc1", "acodec": "mp4a", "filesize": 45_000_000}]}}
    app.settings.proxy = "http://127.0.0.1:8080"
    app._on_analysis_done(single, "", preview=preview)
    result["size_shown"] = app.ids.media_sub.text
    result["no_picture_through_proxy"] = ids.media_thumb.parent is None
    app.settings.proxy = ""
    app.set_mode("audio")
    result["size_follows_mode"] = app.ids.media_sub.text
    # B3-13: a wide screen keeps the page a readable width.
    Window.size = (1280, 800)
    Clock.schedule_once(wide, 0.5)

def wide(*_):
    side = app.ids.home_box.padding[0]
    result["wide_side"] = [side, (Window.width - main.dp(main.CONTENT_WIDTH)) / 2]
    result["announced"] = announced[:]
    finish()

app.run()
"""


@needs_display
def test_download_tab_bar_options_errors_log_queue_done_row_and_notification(tmp_path):
    r, _out = _run_probe(tmp_path, _HOME_PROBE)
    assert r["fixed_bar"] and r["options_folded"] and r["options_open"]
    shown, text = r["error_card"]
    assert shown and "404" in text and r["error_closed"]
    log = r["log"]
    assert log["kept"] == 1000 and log["last"] == "line 1199" and log["first_shown"] == "line 900"
    assert log["chunks"] <= 300 // 25 + 1 and log["wraps"]
    assert r["log_appended"] == "one more"
    assert r["copied"] == [1000, "one more"]
    assert r["cleared"] == [0, 0]
    assert r["skipped_button"][0] and "1" in r["skipped_button"][1]
    assert r["skipped_rows"] == [["Gone", i18n.tr_message("Private video")]]
    assert r["queue_rows"] == ["https://a.com/1", "https://a.com/2", "https://a.com/3"]
    assert r["queue_moved"] == ["https://a.com/1", "https://a.com/3", "https://a.com/2"]
    assert r["queue_removed"] == ["https://a.com/3", "https://a.com/2"]
    assert r["started"] == ["https://e.com/0", "https://e.com/1"]
    assert all(r["done_row"].values()), r["done_row"]
    assert r["retry_text"] == i18n.tr("action.retry_n", count=1)
    assert r["failed_card"]
    assert r["history_saved"] == ["Video 0"]  # written at the end of the job
    assert r["retried"] == ["https://e.com/1"] and r["retry_options_kept"]
    assert r["notice_buttons"] == [True, True, True]
    assert r["permission_asked"] == 1
    assert "≈ 45 MB" in r["size_shown"] and r["no_picture_through_proxy"]
    assert "≈" not in r["size_follows_mode"]  # audio: no audio-only stream listed, no estimate
    assert r["wide_side"][0] == pytest.approx(r["wide_side"][1])
    assert r["announced"]  # the screen reader heard what changed


_LISTS_PROBE = _START + """
def probe(*_):
    ids = app.ids
    # B3-9, B5-5: a playlist of 5000 opens with one page of rows; search; Select all ticks what is shown.
    items = [QueueItem(url=f"https://e.com/{n}", title=f"Video {n}") for n in range(5000)]
    app.ids.url.text = "https://e.com/big"
    started = time.monotonic()
    app._on_analysis_done(AnalysisResult(title="Big", items=items, is_playlist=True), "")
    app.choose_videos()
    result["picker_seconds"] = time.monotonic() - started
    dialog = dialogs()[0]
    result["picker_rows"] = len(rows_of(dialog))
    field = [w for w in dialog.walk() if type(w).__name__ == "MDTextField"][0]
    field.text = "Video 4999"
    result["searched"] = [r.headline for r in rows_of(dialog)]
    buttons = [w for w in dialog.walk() if type(w).__name__ == "MDButton"]
    buttons[1].dispatch("on_release")  # Select none (of what is shown)
    buttons[-1].dispatch("on_release")  # Done
    result["chosen"] = len(app.chosen)
    # B4-8: the same list again: the selection comes back.
    app._on_analysis_done(AnalysisResult(title="Big", items=items, is_playlist=True), "")
    result["remembered"] = len(app.chosen)
    # B3-10, B5-2, B5-4: History in steps of 50, search, local dates, undo, download again.
    for n in range(120):
        app.history.add(f"Song {n}", os.path.abspath(f"song{n}.mp3"), url=f"https://e.com/s{n}", kind="audio",
                        now=1_760_000_000 + n, save=False)
    app.history.flush()
    app.go_to("history")
    lst = ids.history_list
    result["history_rows"] = len(lst.children)
    result["history_more"] = rows_of(lst)[-1].headline
    result["date"] = rows_of(lst)[0].supporting
    result["date_expected"] = "MP3 · " + main.android_env.format_date(1_760_000_000 + 119)
    rows_of(lst)[-1].dispatch("on_release")
    result["history_more_rows"] = len(lst.children)
    first = rows_of(lst)[1]
    app.history.add("New one", os.path.abspath("new.mp3"), url="https://e.com/new", kind="audio")
    app._history_added(app.history.entries[0])
    result["added_on_top"] = [rows_of(lst)[0].headline, rows_of(lst)[2] is first]
    ids.history_search.text = "song 11"
    result["history_search"] = sorted(r.headline for r in rows_of(lst))
    ids.history_search.text = "nothing like this"
    result["no_match"] = [w.text for w in lst.children][0]
    ids.history_search.text = ""
    entry = app.history.entries[0]
    app._history_menu(None, entry)
    result["history_menu"] = [r.headline for r in rows_of(dialogs()[0])]
    app._named["choice.remove"].dispatch("on_release")
    result["removed"] = entry.path not in [e.path for e in app.history.entries]
    bars = [w for w in Window.children if type(w).__name__ == "MDSnackbar"]
    undo = [w for w in bars[-1].walk() if type(w).__name__ == "MDSnackbarActionButton"][0]
    undo.dispatch("on_release")
    result["undone"] = app.history.entries[0].path == entry.path
    analysed = []
    real_analyze, app.analyze = app.analyze, lambda keep_mix=False: analysed.append(app.ids.url.text)
    app._history_menu(None, app.history.entries[3])
    app._named["choice.again"].dispatch("on_release")
    app.analyze = real_analyze
    result["again"] = [analysed, app.ids.screens.current]
    finish()

app.run()
"""


@needs_display
def test_playlist_picker_and_history_handle_long_lists(tmp_path):
    for n in range(0, 120, 7):  # some files are there; the rest count as moved
        (tmp_path / f"song{n}.mp3").write_bytes(b"x")
    r, _out = _run_probe(tmp_path, _LISTS_PROBE)
    assert r["picker_rows"] <= 100 and r["picker_seconds"] < 10
    assert r["searched"] == ["4999. Video 4999"] or r["searched"] == ["Video 4999"]
    assert r["chosen"] == 4999 and r["remembered"] == 4999
    assert r["history_rows"] == 51 and r["history_more"] == i18n.tr("history.more", count=70)
    assert r["date"].startswith(r["date_expected"])
    assert r["history_more_rows"] == 101
    assert r["added_on_top"] == ["New one", True]
    assert r["history_search"] == ["Song 11"] + [f"Song {n}" for n in range(110, 120)]
    assert r["no_match"] == i18n.tr("history.no_match")
    assert r["history_menu"] == [texts.t("home.open"), texts.t("history.share"), i18n.tr("history.again"),
                                 texts.t("history.delete")]
    assert r["removed"] and r["undone"]
    assert r["again"][0] and r["again"][0][0].startswith("https://e.com/s") and r["again"][1] == "home"


_SETTINGS_PROBE = _START + """
def probe(*_):
    app.go_to("settings")
    Clock.schedule_once(on_settings, 0.6)  # after the slide

def on_settings(*_):
    ids = app.ids
    names = sorted(n for n in app._named if n.startswith("settings."))
    result["rows"] = names
    ids.settings_search.text = "proxy"
    shown = [w for w in ids.settings_list.children[::-1]]
    result["search_proxy"] = [getattr(w, "headline", None) or w.text for w in shown]
    ids.settings_search.text = "zzzz nothing"
    result["search_none"] = [w.text for w in ids.settings_list.children]
    ids.settings_search.text = ""
    # B4-7: the SponsorBlock parts.
    app.choose_sponsor_categories()
    app._named["choice.intro"].dispatch("on_release")  # untick
    buttons = [w for w in dialogs()[0].walk() if type(w).__name__ == "MDButton"]
    buttons[-1].dispatch("on_release")
    result["sponsor"] = app.settings.sponsorblock_categories
    # B4-6: subtitle languages; unusable ones are dropped.
    app.edit_subtitle_langs()
    field = [w for w in dialogs()[0].walk() if type(w).__name__ == "MDTextField"][0]
    field.text = "tr, x!, en"
    [w for w in dialogs()[0].walk() if type(w).__name__ == "MDButton"][-1].dispatch("on_release")
    result["sub_langs"] = app.settings.subtitle_langs
    # The download gets them.
    options = {}
    class Session:
        paused = False
        busy = False
        def download(self, analysis, opts):
            options.update(opts)
            return True
    app.session = Session()
    app.settings.subtitles = app.settings.sponsorblock = True
    app.analysis = AnalysisResult(title="Clip", items=[QueueItem(url="https://e.com/c", title="Clip")])
    app.chosen = list(app.analysis.items)
    app.download_dir = os.getcwd()
    app.download()
    result["options"] = [options.get("subtitle_langs"), options.get("sponsorblock_categories")]
    app.job = None
    app.set_busy(False)
    # B3-11: licenses.
    app.show_licenses()
    result["licenses"] = "FFmpeg" in [w for w in dialogs()[0].walk() if type(w).__name__ == "MDLabel"][-1].text
    close_dialogs()
    # B4-9: Skip this version.
    update = main.self_update.Update("9.9.9", "orbida-v9.9.9", "notes", "", "https://x/a.apk", 1, "", "a.apk")
    app._offer_update(update)
    buttons = [w for w in dialogs()[0].walk() if type(w).__name__ == "MDButton"]
    buttons[0].dispatch("on_release")
    result["skipped"] = app.settings.skipped_version
    # B6-1: where the named widgets are, for the emulator test.
    printed = []
    main.selftest = lambda line: printed.append(line)
    Clock.schedule_once(lambda *_: where_settings(printed), 0.6)  # the dialogs closed

def where_settings(printed):
    app._report_where()
    app.go_to("home")
    Clock.schedule_once(lambda *_: where_home(printed), 0.6)

def where_home(printed):
    app._report_where()
    result["where"] = printed[:]
    finish()

app.run()
"""


@needs_display
def test_settings_search_new_rows_licenses_skip_and_named_widgets(tmp_path):
    r, _out = _run_probe(tmp_path, _SETTINGS_PROBE)
    for name in ("settings.theme", "settings.sub_langs", "settings.sub_embed", "settings.sponsor_parts",
                 "settings.update_channel", "settings.licenses", "settings.proxy"):
        assert name in r["rows"], name
    assert r["search_proxy"][0] == texts.t("settings.connection") and texts.t("settings.proxy") in r["search_proxy"]
    assert len(r["search_proxy"]) == 2
    assert r["search_none"] == [i18n.tr("history.no_match")]
    assert r["sponsor"] == "sponsor,selfpromo,interaction,outro,music_offtopic"
    assert r["sub_langs"] == "tr, en"
    assert r["options"] == [["tr", "en"], "sponsor,selfpromo,interaction,outro,music_offtopic"]
    assert r["licenses"]
    assert r["skipped"] == "9.9.9"
    settings_line = next(line for line in r["where"] if "screen=settings" in line)
    home_line = r["where"][-1]
    assert "settings.theme=" in settings_line and "nav.home=" in settings_line
    assert "screen=home" in home_line and "btn_download=" in home_line and "settings.theme=" not in home_line
    x, y = map(int, re.search(r"btn_download=(\d+),(\d+)", home_line).groups())
    assert 0 < x < 412 and 892 - 200 < y < 892 - 80  # the fixed bar above the navigation, in screen coordinates


_OVERFLOW_PROBE = _START.replace('"412"', '"360"').replace('"892"', '"740"') + """
def overflow():
    \"\"\"Widgets of the Download tab's rows (and Settings rows) that run past their row.\"\"\"
    bad = []
    rows = [app.ids[n] for n in ("mode_row", "choice_row", "done_row", "queue_row")]
    rows.append(app.ids.btn_clear.parent)
    for row in rows:
        for child in row.children:
            if child.right > row.right + 1 or child.x < row.x - 1:
                bad.append(f"{type(child).__name__} in {row}")
            for label in child.walk(restrict=True):
                if type(label).__name__ == "MDButtonText" and label.texture_size[0] > child.width + 1:
                    bad.append(f"text {label.text!r}")
    for w in app.ids.home_box.children:
        if w.right > app.ids.home_box.right + 1:
            bad.append(f"{type(w).__name__} wider than the page")
    return bad

languages = list(main.FONT_LANGUAGES)
problems = {}

def probe(*_):
    app.ids.queue_text.text = app.tr("queue.waiting", count=88)
    for name in ("queue_row", "progress_card", "done_row"):
        main._show(app.ids[name], True)
    next_language()

def next_language(*_):
    if not languages:
        result["problems"] = problems
        result["fontscale"] = main.sp(1)
        finish()
        return
    code = languages.pop(0)
    app._change_language(code)
    app._show_options(True)
    Clock.schedule_once(lambda *_: check(code), 0.4)

def check(code, tries=4):
    # A button takes its new text's width a frame or two after the
    # language changes; only an overflow that stays is a problem.
    bad = overflow()
    if bad and tries > 1:
        Clock.schedule_once(lambda *_: check(code, tries - 1), 0.4)
        return
    if bad:
        problems[code] = bad
    next_language()

app.run()
"""


@needs_display
@pytest.mark.parametrize("fontscale", ["1.0", "1.3"])
def test_long_translations_fit_a_small_phone_at_two_text_sizes(tmp_path, fontscale):
    """B3-15, B6-3: every language at normal and large text on a 360 dp wide phone."""
    r, _out = _run_probe(tmp_path, _OVERFLOW_PROBE, {"KIVY_METRICS_FONTSCALE": fontscale}, timeout=400)
    assert r["fontscale"] == pytest.approx(float(fontscale))
    assert r["problems"] == {}
