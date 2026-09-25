"""UniversalDownloader for Android (preview).

A single Kivy screen on top of the shared download code: paste a link,
analyze it, pick Video + Audio or Audio Only, download into
``Download/UniversalDownloader`` with progress and cancel.

Worker threads never touch widgets. They post to an ``events.EventQueue``
that ``Clock`` drains on the main thread, as the Windows app does with Tk's
``after()``.
"""

import logging
import os
import sys
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton

import android_env
import events
import filenames
import i18n
import logic
import media_tools
import urls
import version
import worker
from i18n import tr
from results import ItemStatus

APP_VERSION = "android-preview"
# Kivy's bundled Roboto font covers Latin, Greek and Cyrillic; languages in
# other scripts fall back to English.
FONT_LANGUAGES = {code for code in i18n.LANGUAGES if code not in {"ja", "ko", "zh"}}
LOG_LINES = 200
SELFTEST_TAG = "UDSELFTEST"

ACCENT = (0.15, 0.45, 0.95, 1)
DANGER = (0.85, 0.25, 0.25, 1)
MUTED = (0.7, 0.7, 0.75, 1)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
_log = logging.getLogger("universaldownloader")


def selftest(message):
    """A line the emulator test in CI looks for in the Android log."""
    print(f"{SELFTEST_TAG} {message}", flush=True)


def _check_quickjs(path):
    """Run the bundled QuickJS once, so a broken binary shows up at start."""
    if not path:
        return "QuickJS missing; YouTube may offer fewer formats"
    import subprocess
    try:
        out = subprocess.run([path, "-e", "print(6 * 7)"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return f"QuickJS failed to start: {e}"
    if out.stdout.strip() != "42":
        return f"QuickJS failed (exit code {out.returncode}): {out.stderr.strip()[:200]}"
    return "QuickJS ready (YouTube)"


def _label(text="", size=15, color=(1, 1, 1, 1), bold=False, **kwargs):
    label = Label(text=text, font_size=sp(size), color=color, bold=bold, halign="left", valign="middle",
                  size_hint_y=None, **kwargs)
    label.bind(width=lambda w, width: setattr(w, "text_size", (width, None)),
               texture_size=lambda w, size: setattr(w, "height", max(size[1], dp(22))))
    return label


def _button(text, on_press, color=ACCENT, **kwargs):
    button = Button(text=text, font_size=sp(16), size_hint_y=None, height=dp(50), background_normal="",
                    background_color=color, **kwargs)
    button.bind(on_press=lambda *_: on_press())
    return button


class DownloaderScreen(BoxLayout):
    def __init__(self, app, **kwargs):
        super().__init__(orientation="vertical", padding=dp(16), spacing=dp(10), **kwargs)
        self.app = app

        self.add_widget(_label("UniversalDownloader", size=22, bold=True))
        self.lbl_tools = _label(tr("top.ffmpeg_checking"), size=13, color=MUTED)
        self.add_widget(self.lbl_tools)

        self.txt_url = TextInput(hint_text="https://", multiline=False, font_size=sp(16), size_hint_y=None,
                                 height=dp(50), write_tab=False)
        self.txt_url.bind(on_text_validate=lambda *_: app.analyze(), text=lambda *_: app.link_changed())
        self.add_widget(self.txt_url)

        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        self.btn_paste = _button(tr("link.paste"), app.paste, color=(0.3, 0.3, 0.35, 1))
        self.btn_analyze = _button(tr("link.analyze"), app.analyze)
        row.add_widget(self.btn_paste)
        row.add_widget(self.btn_analyze)
        self.add_widget(row)

        self.lbl_media = _label(tr("activity.welcome"), size=15)
        self.add_widget(self.lbl_media)

        modes = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.btn_video = ToggleButton(text=tr("mode.video_audio"), group="mode", state="down",
                                      allow_no_selection=False, font_size=sp(15))
        self.btn_audio = ToggleButton(text=tr("mode.audio_only"), group="mode", allow_no_selection=False,
                                      font_size=sp(15))
        for button in (self.btn_video, self.btn_audio):
            button.bind(state=lambda *_: self.update_choices())
            modes.add_widget(button)
        self.add_widget(modes)

        choice = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        self.lbl_choice = _label(tr("options.quality"), size=13, color=MUTED, size_hint_x=0.4)
        self.spn_choice = Spinner(font_size=sp(15))
        choice.add_widget(self.lbl_choice)
        choice.add_widget(self.spn_choice)
        self.add_widget(choice)
        self.update_choices()

        self.lbl_folder = _label("", size=12, color=MUTED)
        self.add_widget(self.lbl_folder)

        self.btn_download = _button(tr("action.download"), app.download)
        self.add_widget(self.btn_download)

        self.progress = ProgressBar(max=1.0, value=0, size_hint_y=None, height=dp(18))
        self.add_widget(self.progress)
        self.lbl_progress = _label(tr("progress.ready"), size=14)
        self.add_widget(self.lbl_progress)

        self.add_widget(_label(tr("activity.title"), size=12, color=MUTED, bold=True))
        self.log_view = ScrollView(do_scroll_x=False)
        self.lbl_log = Label(text="", font_size=sp(12), color=(0.85, 0.85, 0.9, 1), halign="left",
                             valign="top", size_hint_y=None, markup=False)
        self.lbl_log.bind(width=lambda w, width: setattr(w, "text_size", (width, None)),
                          texture_size=lambda w, size: setattr(w, "height", size[1]))
        self.log_view.add_widget(self.lbl_log)
        self.add_widget(self.log_view)
        self._log_lines = []

    @property
    def mode(self):
        return worker.AUDIO_ONLY if self.btn_audio.state == "down" else worker.VIDEO_AUDIO

    def update_choices(self):
        if self.mode == worker.AUDIO_ONLY:
            self.lbl_choice.text = tr("options.format")
            self.spn_choice.values = ["mp3", "m4a"]
            if self.spn_choice.text not in self.spn_choice.values:
                self.spn_choice.text = "mp3"
        else:
            self.lbl_choice.text = tr("options.quality")
            labels = [tr("quality.best") if q == "Best" else q for q in worker.VIDEO_QUALITIES]
            self.spn_choice.values = labels
            if self.spn_choice.text not in labels:
                self.spn_choice.text = labels[0]

    def selected_quality(self):
        text = self.spn_choice.text
        return "Best" if text == tr("quality.best") else text

    def log(self, line):
        self._log_lines.append(line)
        del self._log_lines[:-LOG_LINES]
        self.lbl_log.text = "\n".join(self._log_lines)
        Clock.schedule_once(lambda *_: setattr(self.log_view, "scroll_y", 0), 0)

    def set_busy(self, busy):
        self.btn_analyze.disabled = busy
        self.btn_paste.disabled = busy
        self.btn_video.disabled = busy
        self.btn_audio.disabled = busy
        self.spn_choice.disabled = busy
        if busy:
            self.btn_download.text = tr("action.cancel")
            self.btn_download.background_color = DANGER
        else:
            self.btn_download.text = tr("action.download")
            self.btn_download.background_color = ACCENT
            self.btn_download.disabled = False


class UniversalDownloaderApp(App):
    title = "UniversalDownloader"

    def build(self):
        Window.softinput_mode = "below_target"
        Window.clearcolor = (0.07, 0.07, 0.09, 1)
        self.events = events.EventQueue()
        self.manager = None
        self.session = None
        self.analysis = None
        self.analysis_url = None
        self.download_dir = None
        self.job = None  # "analyze" or "download" while one runs
        self._selftest = None
        self._set_language()
        self.screen = DownloaderScreen(self)
        self._wire_handlers()
        Clock.schedule_interval(lambda *_: self.events.dispatch_pending(), 0.1)
        return self.screen

    def _wire_handlers(self):
        self.events.register(events.LOG, lambda message: self.screen.log(message))
        self.events.register(events.TOOLS_CHECKED, self._on_tools_checked)
        self.events.register(events.ANALYSIS_DONE, self._on_analysis_done)
        self.events.register(events.ANALYSIS_FAILED, self._on_analysis_failed)
        self.events.register(events.ITEM_STARTED, self._on_item_started)
        self.events.register(events.PROGRESS, self._on_progress)
        self.events.register(events.STAGE, self._on_stage)
        self.events.register(events.ITEM_DONE, self._on_item_done)
        self.events.register(events.JOB_DONE, self._on_job_done)

    def _set_language(self):
        code = None
        if android_env.on_android():
            try:
                code = android_env.device_language()
            except Exception:
                code = None
        code = code if code in FONT_LANGUAGES else i18n.system_language()
        i18n.set_language(code if code in FONT_LANGUAGES else i18n.FALLBACK)

    def on_start(self):
        self.screen.set_busy(False)
        self.screen.btn_download.disabled = True
        self.screen.btn_analyze.disabled = True
        if android_env.on_android():
            os.environ["TMPDIR"] = android_env.cache_dir()
            android_env.request_storage_permission()
            self._selftest = self._selftest_url()
        threading.Thread(target=self._check_tools, daemon=True).start()

    # --- Start-up -----------------------------------------------------------------

    def _check_tools(self):
        """Worker thread: link the bundled programs, verify them, pick the folder."""
        messages = []
        try:
            if android_env.on_android():
                links = android_env.link_tools(android_env.native_library_dir(),
                                               os.path.join(android_env.files_dir(), "tools"))
                status = media_tools.find_tools(bundled=os.path.dirname(links.get("ffmpeg", "")) or "/nonexistent")
                logic.set_platform_options(android_env.js_runtime_options(links))
                messages.append(_check_quickjs(links.get("qjs")))
                candidates = [android_env.public_downloads_dir(), android_env.app_downloads_dir()]
            else:
                status = media_tools.find_tools()
                candidates = [os.path.join(os.path.expanduser("~"), "Downloads", "UniversalDownloader")]
            media_tools.activate(status)

            def check(folder):
                error, _warning = filenames.check_folder(folder)
                return error

            folder, errors = android_env.choose_download_dir(candidates, check)
            messages.extend(errors)
            self.download_dir = folder
        except Exception as e:
            status = media_tools.ToolStatus(False, error=logic.describe_error(e))
        import yt_dlp.version
        messages.insert(0, f"yt-dlp {yt_dlp.version.__version__}, app {version.__version__} ({APP_VERSION})")
        messages.append(status.summary())
        for message in messages:
            _log.info(message)
            self.events.post(events.LOG, message=message)
        selftest(f"tools ok={status.ok} {status.summary()}")
        self.events.post(events.TOOLS_CHECKED, status=status)

    def _on_tools_checked(self, status):
        self.manager = logic.DownloadManager(tools=status)
        self.session = worker.Session(self.manager, self.events, tr=tr)
        if status.ok:
            self.screen.lbl_tools.text = tr("top.ffmpeg_ready", version=status.version)
        else:
            self.screen.lbl_tools.text = tr("top.ffmpeg_missing")
            self.screen.lbl_tools.color = DANGER
        folder = self.download_dir or "?"
        self.screen.lbl_folder.text = f"{tr('options.save_to')}: {folder}"
        self.screen.btn_analyze.disabled = False
        self.screen.btn_download.disabled = not (self.analysis and self.analysis.items)
        if self._selftest:
            self.screen.txt_url.text = self._selftest
            self.analyze()

    # --- Actions ------------------------------------------------------------------

    def paste(self):
        text = android_env.clipboard_text().strip()
        if text:
            self.screen.txt_url.text = text

    def link_changed(self):
        if self.job is None and self.analysis is not None and self.screen.txt_url.text.strip() != self.analysis_url:
            self.analysis = None
            self.screen.btn_download.disabled = True
            self.screen.lbl_media.text = tr("link.changed")

    def analyze(self):
        if self.session is None or self.job is not None:
            return
        try:
            started = self.session.analyze(self.screen.txt_url.text)
        except urls.UrlError as e:
            self.screen.lbl_media.text = tr(e.key, **e.values)
            return
        if started:
            self.job = "analyze"
            self.analysis = None
            self.screen.set_busy(True)
            self.screen.btn_download.disabled = True
            self.screen.lbl_media.text = tr("link.reading")
            self.screen.log(tr("log.fetching"))

    def download(self):
        if self.job == "download":
            self.session.cancel()
            self.screen.btn_download.text = tr("action.cancelling")
            self.screen.btn_download.disabled = True
            return
        if self.job is not None or not self.analysis or not self.analysis.items:
            return
        if not self.download_dir:
            self.screen.log(tr("folder.error_title"))
            return
        mode = self.screen.mode
        if mode == worker.AUDIO_ONLY:
            options = worker.build_options(mode, "Best", self.download_dir, audio_format=self.screen.spn_choice.text)
        else:
            options = worker.build_options(mode, self.screen.selected_quality(), self.download_dir)
        if self.session.download(self.analysis, options):
            self.job = "download"
            self.screen.set_busy(True)
            self.screen.progress.value = 0
            self.screen.lbl_progress.text = tr("progress.starting")
            self.screen.log(tr("log.folder", folder=self.download_dir))

    # --- Events (main thread) -----------------------------------------------------

    def _on_analysis_done(self, analysis, url):
        self.job = None
        self.analysis = analysis
        self.analysis_url = self.screen.txt_url.text.strip()
        self.screen.set_busy(False)
        if analysis.is_playlist:
            text = f"{tr('media.playlist')}: {analysis.title}\n{tr('media.videos', count=len(analysis.items))}"
            if analysis.skipped:
                text += f", {tr('media.unavailable', count=len(analysis.skipped))}"
            self.screen.log(tr("log.playlist", title=analysis.title, count=len(analysis.items),
                               skipped=len(analysis.skipped)))
        elif analysis.items:
            text = f"{tr('media.video')}: {analysis.title}"
            self.screen.log(tr("log.video", title=analysis.title))
        else:
            reason = analysis.skipped[0].skip_reason if analysis.skipped else None
            text = tr("link.nothing_reason", reason=i18n.tr_message(reason)) if reason else tr("link.nothing")
        self.screen.lbl_media.text = text
        self.screen.btn_download.disabled = not analysis.items
        selftest(f"analysis items={len(analysis.items)} title={analysis.title!r}")
        if self._selftest and analysis.items:
            self.download()

    def _on_analysis_failed(self, message):
        self.job = None
        self.screen.set_busy(False)
        self.screen.btn_download.disabled = True
        self.screen.lbl_media.text = tr("link.nothing_reason", reason=message)
        self.screen.log(message)
        selftest(f"analysis failed: {message}")

    def _on_item_started(self, position, total, title):
        self.screen.progress.value = 0
        self.screen.lbl_progress.text = tr("progress.item", position=position, total=total, title=title)

    def _on_progress(self, fraction, text, detail):
        self.screen.progress.value = fraction
        self.screen.lbl_progress.text = f"{text}  {detail}".strip()

    def _on_stage(self, text):
        self.screen.lbl_progress.text = i18n.tr_message(text)

    def _on_item_done(self, result):
        if result.status is ItemStatus.COMPLETED:
            self.screen.log(tr("log.saved", path=result.path))
            if android_env.on_android():
                try:
                    android_env.scan_media(result.path)
                except Exception as e:
                    _log.warning("Media scan failed: %s", e)
        else:
            line = tr("log." + result.status.value, title=result.title)
            self.screen.log(line + (f" ({i18n.tr_message(result.error)})" if result.error else ""))
        selftest(f"item {result.status.value} path={result.path} error={result.error}")

    def _on_job_done(self, summary):
        self.job = None
        self.screen.set_busy(False)
        headline = summary.headline(label=lambda status: tr("status." + status.value), nothing=tr("summary.nothing"))
        self.screen.log(tr("log.result", summary=headline))
        self.screen.lbl_progress.text = f"{tr(summary.title_key())}: {headline}"
        if summary.all_ok:
            self.screen.progress.value = 1
        selftest(f"job done all_ok={summary.all_ok}")
        if self._selftest:
            self._selftest = None
            if self.screen.mode == worker.VIDEO_AUDIO:
                # Second pass of the self-test: the same link as audio.
                self._selftest = self.screen.txt_url.text
                self.screen.btn_audio.state = "down"
                self.screen.btn_video.state = "normal"
                self.download()

    def _selftest_url(self):
        """The ``selftest_url`` extra of the launching intent (CI only)."""
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            return activity.getIntent().getStringExtra("selftest_url")
        except Exception:
            return None

    def on_pause(self):
        # Keep running when the user switches apps; downloads continue while
        # Android lets the process live.
        return True

    def on_stop(self):
        if self.session is not None and self.session.busy:
            self.session.cancel()
            self.session.wait(5)


if __name__ == "__main__":
    UniversalDownloaderApp().run()
