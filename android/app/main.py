"""Orbida: UniversalDownloader for Android.

A Material You app (KivyMD 2) on top of the shared download code, with
three tabs: Download (link, Video/Audio, quality, trim, progress), History
and Settings (appearance, download defaults, behaviour, About).

Worker threads never touch widgets. They post to an ``events.EventQueue``
that ``Clock`` drains on the main thread, as the Windows app does with Tk's
``after()``.
"""

import dataclasses
import logging
import os
import sys
import threading
import time
from collections import deque

import ytdlp_updates

# A yt-dlp the update check downloaded replaces the bundled one; this has
# to happen before anything imports yt_dlp.
YTDLP_DIR = os.path.join(os.environ["ANDROID_PRIVATE"], "yt-dlp") if "ANDROID_PRIVATE" in os.environ else None
try:
    if ytdlp_updates.activate(YTDLP_DIR):
        import yt_dlp  # noqa: F401  (proves the download works)
except Exception:
    logging.getLogger(__name__).exception("The downloaded yt-dlp does not work; using the bundled one")
    ytdlp_updates.deactivate(YTDLP_DIR)

from kivy.base import ExceptionHandler, ExceptionManager
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.stacklayout import StackLayout
from kivy.uix.widget import Widget
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.dialog import (MDDialog, MDDialogButtonContainer, MDDialogContentContainer,
                               MDDialogHeadlineText, MDDialogSupportingText)
from kivymd.uix.label import MDLabel
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.slider import MDSlider, MDSliderHandle
from kivymd.uix.snackbar import (MDSnackbar, MDSnackbarActionButton, MDSnackbarActionButtonText,
                                 MDSnackbarButtonContainer, MDSnackbarSupportingText, MDSnackbarText)
from kivymd.uix.textfield import (MDTextField, MDTextFieldHelperText, MDTextFieldHintText,
                                  MDTextFieldLeadingIcon)

import android_env
import app_settings
import browser_cookies
import browser_route
import crash_report
import events
import filenames
import formats
import history
import i18n
import layout
import licenses
import logic
import md_patches
import media_tools
import playlist
import self_update
import texts
import urls
import version
import worker
import youtube_login
from app_settings import AppSettings
from lite import LiteHeadline, LiteRow, LiteSection, LiteWrappedText
from playlist import AnalysisResult, QueueItem
from results import ItemStatus

md_patches.disable_gpu_ripple()  # before any KivyMD widget exists; see md_patches
if android_env.on_android():
    md_patches.disable_hover()

APP_NAME = "Orbida"    # the Android app's name; keep in step with title in android/buildozer.spec
APP_VERSION = version.__version__  # buildozer.spec reads it from version.py too
# KivyMD's Roboto fonts cover Latin, Greek and Cyrillic; languages in other
# scripts fall back to English.
FONT_LANGUAGES = [code for code in i18n.LANGUAGES if code not in {"ja", "ko", "zh"}]
LOG_LINES = 1000     # kept, and copied by Copy
LOG_SHOWN = 300      # drawn in the Details panel (the newest)
LOG_CHUNK = 25       # lines per label: one texture each, far below a phone's size limit
HISTORY_STEP = 50    # History rows made at a time; "Show more" adds the next ones
PICKER_PAGE = 100    # playlist picker rows made at a time
CONTENT_WIDTH = 720  # dp; wider screens (tablets, landscape) centre the pages at this width
WHERE_SECONDS = 1    # how often the UI self-test reports where its named widgets are
TAB_SECONDS = 0.2    # tab switch animation
PREBUILD_SECONDS = 0.5  # after start-up, fill in Settings and History in the background
NETWORK_CHECK_SECONDS = 5  # how often Wi-Fi only looks at the network during a download
SELFTEST_TAG = "UDSELFTEST"
MODES = {"video": worker.VIDEO_AUDIO, "audio": worker.AUDIO_ONLY}
MIME = {"mp4": "video/mp4", "mkv": "video/x-matroska", "webm": "video/webm", "mp3": "audio/mpeg",
        "m4a": "audio/mp4", "flac": "audio/flac", "wav": "audio/wav", "opus": "audio/ogg"}

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
_log = logging.getLogger("universaldownloader")


class _KeepRunning(ExceptionHandler):
    """Hands main-loop errors to the app, which records them and carries on."""

    def __init__(self, app):
        super().__init__()
        self.app = app

    def handle_exception(self, inst):
        try:
            keep = self.app.on_error(inst)
        except Exception:
            keep = False
        return ExceptionManager.PASS if keep else ExceptionManager.RAISE


def selftest(message):
    """A line the emulator test in CI looks for in the Android log."""
    print(f"{SELFTEST_TAG} {message}", flush=True)


def _run_tool(args):
    import subprocess
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    return out, None


def _check_quickjs(path):
    """Run the bundled QuickJS once, so a broken binary shows up at start."""
    if not path:
        return "QuickJS missing; YouTube may offer fewer formats"
    out, error = _run_tool([path, "-e", "print(6 * 7)"])
    if error:
        return f"QuickJS failed to start: {error}"
    if out.stdout.strip() != "42":
        return f"QuickJS failed (exit code {out.returncode}): {out.stderr.strip()[:200]}"
    return "QuickJS ready (YouTube)"


def _ffmpeg_https(path):
    """True when the bundled FFmpeg can read HTTPS (needed for trimming)."""
    if not path:
        return False
    out, error = _run_tool([path, "-hide_banner", "-protocols"])
    return error is None and "https" in out.stdout.split()


def _on_screen(widget):
    """The window position of ``widget``'s centre when it can be tapped now, else None."""
    if widget.get_root_window() is None or widget.opacity == 0 or widget.disabled:
        return None
    x, y = widget.to_window(*widget.center)
    if not (0 <= x <= Window.width and 0 <= y <= Window.height):
        return None
    parent = widget.parent
    while parent is not None and parent is not Window:
        if isinstance(parent, ScrollView):  # scrolled out of its view
            left, bottom = parent.to_window(parent.x, parent.y)
            right, top = parent.to_window(parent.right, parent.top)
            if not (left <= x <= right and bottom <= y <= top):
                return None
        parent = parent.parent
    return x, y


def _show(widget, visible):
    """Show or hide a widget, taking it out of its layout while hidden."""
    parent = getattr(widget, "_home", None) or widget.parent
    if parent is None:
        return
    widget._home = parent
    if not hasattr(parent, "_display_order"):
        parent._display_order = list(reversed(parent.children))  # top to bottom
    if visible and widget.parent is None:
        order = parent._display_order
        before = [w for w in order[:order.index(widget)] if w.parent is parent]
        parent.add_widget(widget, index=len(parent.children) - len(before))
    elif not visible and widget.parent is not None:
        parent.remove_widget(widget)


# Pure black theme: surface roles and their grey level (0-1).
PURE_BLACK = {
    "background": 0.0, "surface": 0.0, "surfaceDim": 0.0, "surfaceContainerLowest": 0.0,
    "surfaceContainerLow": 0.03, "surfaceContainer": 0.05, "surfaceContainerHigh": 0.08,
    "surfaceContainerHighest": 0.11,
}


class NavTab(ButtonBehavior, BoxLayout):
    """A tab of the navigation bar; ``main`` draws it as the round button in the middle."""

    name = StringProperty()
    icon = StringProperty()
    text = StringProperty()
    active = BooleanProperty(False)
    main = BooleanProperty(False)


class ProgressRing(Widget):
    """The download's progress as a ring with the percentage inside (0-100)."""

    value = NumericProperty(0)


class Root(MDBoxLayout):
    pass


class LogChunk(Label):
    """LOG_CHUNK lines of the activity log (layout.KV draws it)."""


class SwitchRow(BoxLayout):
    """A settings row with a switch; ``callback(value)`` runs on change."""

    icon = StringProperty()
    headline = StringProperty()
    supporting = StringProperty()
    active = BooleanProperty(False)

    def __init__(self, callback, **kwargs):
        super().__init__(**kwargs)
        self.callback = callback

    def on_switch(self, value):
        if value != self.active:
            self.active = value
            self.callback(value)


Builder.load_string(r"""
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp
<SwitchRow>:
    size_hint_y: None
    height: max(dp(56), texts.height + dp(16))
    padding: dp(16), 0, dp(24), 0
    spacing: dp(16)
    LiteIcon:
        icon: root.icon
        pos_hint: {"center_y": .5}
    BoxLayout:
        id: texts
        orientation: "vertical"
        size_hint_y: None
        height: self.minimum_height
        spacing: dp(2)
        pos_hint: {"center_y": .5}
        LiteHeadline:
            text: root.headline
        LiteWrappedText:
            text: root.supporting
            font_size: sp(12)
    MDSwitch:
        pos_hint: {"center_y": .5}
        active: root.active
        on_active: root.on_switch(self.active)
""")


class UniversalDownloaderApp(MDApp):
    title = APP_NAME
    lang = StringProperty(i18n.FALLBACK)  # kv texts re-read when it changes

    # --- Texts --------------------------------------------------------------------

    def t(self, key, *_lang, **values):
        return texts.t(key, **values)

    def tr(self, key, *_lang, **values):
        return i18n.tr(key, **values)

    def tr_label(self, key, *_lang):
        return i18n.tr_label(key)

    # --- Build --------------------------------------------------------------------

    def build(self):
        self.crash = crash_report.CrashReport(self.user_data_dir)
        self._previous_crash = self.crash.take_previous(self._android_crash_log())
        if self._previous_crash:
            print(f"UDCRASH previous run:\n{self._previous_crash}", flush=True)
        try:
            self.crash.watch_native()
        except OSError as e:
            _log.warning("Cannot watch for crashes: %s", e)
        ExceptionManager.add_handler(_KeepRunning(self))
        self._errors = deque(maxlen=20)
        Window.softinput_mode = "below_target"
        self.settings_path = os.path.join(self.user_data_dir, "settings.json")
        self.settings = app_settings.load(self.settings_path)
        self.history = history.History(os.path.join(self.user_data_dir, "history.json"))
        self.choices_path = os.path.join(self.user_data_dir, "playlist_choices.json")
        self.events = events.EventQueue()
        self.manager = None
        self.session = None
        self.analysis = None
        self.analysis_url = None
        self.chosen = []          # the playlist entries picked for download
        self.link_queue = []      # links added while a download runs
        self._from_queue = False  # the running analysis came from link_queue
        self._analysis_dropped = False  # a cancelled analysis's late result is ignored
        self._mix = None  # the Mix link a song being analyzed was opened in
        self.mix_url = None  # offered on the "Download the Mix" button
        self._cancelled = False
        self._mobile_data_ok = False  # the user chose to download on mobile data
        self._wifi_paused = False     # paused by the Wi-Fi-only setting, not by the user
        self.download_dir = None
        self.job = None  # "analyze" or "download" while one runs
        self.mode = self.settings.default_mode
        self._auto_mode = None  # the mode before a Spotify link switched to audio
        self.quality = {"video": self.settings.video_quality, "audio": self.settings.audio_quality}
        self.fmt = {"video": self.settings.video_container, "audio": self.settings.audio_format}
        self.components = {}
        self.pending_link = None
        self.tools_ready = False
        self._selftest = None
        self._selftest_passes = []
        self._log_lines = deque(maxlen=LOG_LINES)
        self._log_total = 0     # lines ever logged: line n is in chunk n // LOG_CHUNK
        self._log_chunks = {}   # chunk number -> (LogChunk, text it shows)
        self._log_trigger = Clock.create_trigger(self._render_log, 0.25)
        self.last_file = None     # the newest file the last download saved
        self.last_summary = None  # results.JobSummary of the last download
        self.last_url = None      # the link the last download came from (Download again)
        self._preview = None      # worker.preview() of the analysed video
        self._history_shown = HISTORY_STEP
        self._history_filter = ""
        self._history_rows = {}   # path -> LiteRow while History lists every entry (no search)
        self._settings_rows = []  # [(section, [rows])] for the Settings search
        self._named = {}          # name -> widget, for the UI self-test
        self._where = None
        self._options = None      # the options of the last download (Retry failed)
        self._battery_asked = False
        # Settings and History are rebuilt when shown, and only after a change.
        self._stale = {"settings": True, "history": True}
        self._dark = None
        self._login = None           # youtube_login.LoginView while it is open
        self._retry_after_sign_in = False  # analyse again once the Reddit sign-in is done
        self._browser = None         # browser_route.AndroidBridge, made on Android at start
        self._update_checking = False
        self._update_cancelled = False
        self._update_dialog = None   # the download progress dialog while an update downloads
        self._update_label = None
        self._wake_lock = None
        self._notice = None          # android_env.DownloadNotice on Android
        self._paused = False         # the app is in the background
        self._finished = None        # (title, text) of the last download, for the notification
        self._asked_notifications = False
        self._stderr = deque(maxlen=12)  # last lines FFmpeg printed, shown when an item fails
        self._apply_language()
        self._apply_theme()
        Builder.load_string(layout.KV)
        self.root_view = Root()
        self.ids = self.root_view.ids
        self.ids.screens.transition.duration = TAB_SECONDS
        self._wire_handlers()
        Clock.schedule_interval(lambda *_: self.events.dispatch_pending(), 0.1)
        Clock.schedule_interval(self._watch_network, NETWORK_CHECK_SECONDS)
        Clock.schedule_interval(self._poll_notice, 0.5)
        Window.bind(on_keyboard=self._on_key)
        return self.root_view

    def _on_key(self, _window, key, *_args):
        """Back (Escape) steps back before it closes the app: it closes an
        open dialog, then the sign-in page, then returns to the Download tab."""
        if key != 27:
            return False
        dialogs = [w for w in Window.children if isinstance(w, MDDialog) and w._is_open]  # not closing ones
        if dialogs:
            dialogs[0].dismiss()  # the topmost
            return True
        if self._login is not None:
            self._login.close()
            return True
        if self.ids.screens.current != "home":
            self.go_to("home")
            return True
        return False

    def _wire_handlers(self):
        self.events.register(events.LOG, self.log)
        self.events.register(events.TOOLS_CHECKED, self._on_tools_checked)
        self.events.register(events.ANALYSIS_DONE, self._on_analysis_done)
        self.events.register(events.ANALYSIS_FAILED, self._on_analysis_failed)
        self.events.register(events.ANALYSIS_PROGRESS, self._on_analysis_progress)
        self.events.register(events.ITEM_STARTED, self._on_item_started)
        self.events.register(events.PROGRESS, self._on_progress)
        self.events.register(events.STAGE, self._on_stage)
        self.events.register(events.ITEM_DONE, self._on_item_done)
        self.events.register(events.JOB_DONE, self._on_job_done)
        self.events.register("shared_link", self._on_shared_text)
        self.events.register("youtube_login", self._on_youtube_login)
        self.events.register("update_checked", self._on_update_checked)
        self.events.register("update_progress", self._on_update_progress)
        self.events.register("update_downloaded", self._on_update_downloaded)

    def on_start(self):
        self._show_mode()
        _show(self.ids.media_card, False)
        _show(self.ids.btn_pick, False)
        _show(self.ids.btn_mix, False)
        _show(self.ids.queue_row, False)
        _show(self.ids.progress_card, False)
        _show(self.ids.trim_box, False)
        _show(self.ids.log_card, False)
        _show(self.ids.error_card, False)
        _show(self.ids.btn_skipped, False)
        _show(self.ids.done_row, False)
        _show(self.ids.media_thumb, False)
        self._show_options(self.settings.show_options)
        Window.bind(size=lambda *_: self._fit_width())
        self._fit_width()
        self._show_week()
        self.set_busy(False)
        self.ids.btn_download.disabled = True
        self.ids.btn_analyze.disabled = True
        if android_env.on_android():
            os.environ["TMPDIR"] = android_env.cache_dir()
            self._wake_lock = android_env.WakeLock()
            self._notice = android_env.DownloadNotice()
            try:
                android_env.forward_native_stderr(self._on_native_stderr)
            except OSError as e:
                _log.warning("Cannot capture stderr: %s", e)
            android_env.request_storage_permission()
            self._selftest = self._selftest_url()
            Clock.schedule_once(self._fit_system_bars, 0.3)
            Window.bind(size=lambda *_: Clock.schedule_once(self._fit_system_bars, 0.3))
            try:
                android_env.bind_new_intent(lambda text: self.events.post("shared_link", text=text))
                shared = android_env.shared_text()
                if shared:
                    self.pending_link = android_env.find_link(shared)
            except Exception as e:
                _log.warning("Share intent: %s", e)
        else:
            self._selftest = os.environ.get("UD_SELFTEST_URL")  # the same self-test on a desktop
        if not self.pending_link and not self._selftest and self.settings.auto_paste:
            Clock.schedule_once(lambda *_: self.paste(quiet=True), 0.5)
        threading.Thread(target=self._check_tools, daemon=True).start()
        if self._previous_crash:
            Clock.schedule_once(lambda *_: self.show_crash(self._previous_crash), 1)

    def on_error(self, error):
        """A Python error reached Kivy's main loop: record it and keep the app open.

        Returns False when errors come so fast that carrying on is pointless.
        """
        now = time.monotonic()
        self._errors.append(now)
        text = self.crash.record(error, where="main loop")
        print(f"UDCRASH {text}", flush=True)
        if len(self._errors) == self._errors.maxlen and now - self._errors[0] < 2:
            return False
        try:
            self.snack(self.t("crash.error", error=f"{type(error).__name__}: {error}"[:160]))
        except Exception:
            pass
        return True

    def _android_crash_log(self):
        """What Android logged when an earlier run of the app closed, or ""."""
        if not android_env.on_android():
            return ""
        crashes = self.crash.new_system_crashes(android_env.app_log("crash"))
        if not crashes:
            return ""
        before = android_env.app_log("main,system", lines=600)
        return (f"Android crash log:\n{crash_report.tail(crashes, 150)}\n\n"
                f"Android log:\n{crash_report.tail(before, 600)}")

    def copy_diagnostics(self):
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(crash_report.diagnostics(APP_VERSION, self._log_lines, android_env.app_log(lines=3000),
                                                  name=APP_NAME))
        self.snack(self.t("crash.copied"))

    def show_crash(self, text):
        from kivy.core.clipboard import Clipboard

        def copy():
            Clipboard.copy(f"{APP_NAME} {APP_VERSION}\n{text}")
            self.snack(self.t("crash.copied"))

        # A label this long would outgrow a texture; the copy keeps everything.
        label = MDLabel(text=crash_report.tail(text, 60), adaptive_height=True, font_style="Body", role="small")
        scroll = MDScrollView(label, size_hint_y=None, height=min(dp(360), Window.height * 0.5),
                              do_scroll_x=False)
        self._dialog(self.t("crash.title"), self.t("crash.body"), content=scroll,
                     buttons=[(self.t("common.close"), None), (self.t("crash.copy"), copy)])

    def _fit_system_bars(self, *_):
        try:
            left, top, right, bottom = android_env.system_bar_insets(Window.height)
        except Exception as e:
            _log.warning("System bar insets: %s", e)
            return
        self.root_view.padding = [left, top, right, bottom]

    def _fit_width(self, *_):
        """On a tablet or in landscape the pages keep a readable width, centred (B3-13)."""
        side = max(dp(16), (Window.width - dp(CONTENT_WIDTH)) / 2)
        self.ids.home_box.padding = [side, dp(8), side, dp(24)]
        self.ids.action_bar.padding = [side, dp(8), side, dp(8)]
        for name in ("history_search_box", "settings_search_box"):
            self.ids[name].padding = [side, 0, side, dp(4)]
        list_side = max(0, side - dp(16))
        self.ids.history_list.padding = [list_side + dp(8), 0, list_side + dp(8), dp(16)]
        self.ids.settings_list.padding = [list_side, 0, list_side, dp(24)]

    def on_resume(self):
        self._paused = False
        if self._battery_asked:  # coming back from Android's battery question
            self._battery_asked = False
            self._refresh("settings")
        # Recolouring every widget is slow, so only follow a changed dark mode
        # (wallpaper colours are read again on the next start).
        self._stale["history"] = True  # files may have been moved meanwhile
        if self.settings.theme == "system" and self._wants_dark() != self._dark:
            self._apply_theme()

    def on_pause(self):
        # Keep running when the user switches apps; DownloadService and the
        # wake lock keep downloads going in the background.
        self._paused = True
        return True

    def on_stop(self):
        if self.session is not None and self.session.busy:
            self.session.cancel()
            self.session.wait(5)
        self._keep_awake(False)
        if self._notice is not None:
            self._notice.stop()

    # --- Appearance ---------------------------------------------------------------

    def _apply_language(self):
        code = self.settings.language
        if code == i18n.AUTO:
            code = None
            if android_env.on_android():
                try:
                    code = android_env.device_language()
                except Exception:
                    code = None
            code = code if code in FONT_LANGUAGES else i18n.system_language()
        i18n.set_language(code if code in FONT_LANGUAGES else i18n.FALLBACK)
        self.lang = i18n.current()

    def _wants_dark(self):
        s = self.settings
        if s.theme == "system" and android_env.on_android():
            try:
                return bool(android_env.night_mode())
            except Exception:
                return False
        return s.theme == "dark"

    def _apply_theme(self):
        s = self.settings
        dark = self._dark = self._wants_dark()
        self.theme_cls.theme_style_switch_animation = False
        self.theme_cls.primary_palette = s.accent
        self.theme_cls.dynamic_color = s.dynamic_color and android_env.on_android()
        self.theme_cls.theme_style = "Dark" if dark else "Light"
        self.theme_cls.set_colors()
        if dark and s.pure_black:
            self._pure_black()

    def _pure_black(self):
        """AMOLED: black page and bars; cards stay a little lighter so they still show."""
        theme = self.theme_cls
        for name, grey in PURE_BLACK.items():
            setattr(theme, name + "Color", [grey, grey, grey, 1])

    # --- Start-up -----------------------------------------------------------------

    def _check_tools(self):
        """Worker thread: link the bundled programs, verify them, pick the folder."""
        messages = []
        components = {}
        try:
            if android_env.on_android():
                native = android_env.native_library_dir()
                android_env.library_path_env(native, os.environ)
                import certifi
                android_env.certificate_env(certifi.where(), os.environ)
                links = android_env.link_tools(native, os.path.join(android_env.files_dir(), "tools"))
                status = media_tools.find_tools(bundled=os.path.dirname(links.get("ffmpeg", "")) or "/nonexistent")
                messages.append(_check_quickjs(links.get("qjs")))
                components["https"] = _ffmpeg_https(links.get("ffmpeg"))
                js = android_env.js_runtime_options(links)
                candidates = [android_env.public_downloads_dir(), android_env.app_downloads_dir()]
            else:
                status = media_tools.find_tools()
                components["https"] = _ffmpeg_https(status.ffmpeg)
                js = {}
                candidates = [os.path.join(os.path.expanduser("~"), "Downloads", android_env.DOWNLOAD_SUBFOLDER)]
            if android_env.on_android():
                # yt-dlp keeps YouTube's player code and solved challenges
                # here; without a writable cache it fetches them every time.
                js["cachedir"] = os.path.join(android_env.cache_dir(), "yt-dlp")
            self._js_options = js
            self._set_platform_options()
            media_tools.activate(status)

            def check(folder):
                error, _warning = filenames.check_folder(folder)
                return error

            folder, errors = android_env.choose_download_dir(candidates, check)
            messages.extend(errors)
            self.download_dir = folder
        except Exception as e:
            self._js_options = {}
            status = media_tools.ToolStatus(False, error=logic.describe_error(e))
        import yt_dlp.version
        components["yt-dlp"] = yt_dlp.version.__version__
        components["ffmpeg"] = status.version if status.ok else None
        try:
            components["tiktok"] = logic.impersonation_available()
        except Exception:
            components["tiktok"] = False
        messages.insert(0, f"Android {APP_VERSION} (shared code {version.__version__}), yt-dlp {components['yt-dlp']}")
        messages.append(status.summary())
        messages.append(f"FFmpeg HTTPS: {components['https']}, impersonation (TikTok): {components['tiktok']}")
        for message in messages:
            _log.info(message)
            self.events.post(events.LOG, message=message)
        selftest(f"tools ok={status.ok} https={components['https']} {status.summary()}")
        self.events.post(events.TOOLS_CHECKED, status=status, components=components)

    def _on_tools_checked(self, status, components):
        self.components = components
        self.tools_ready = True
        self.manager = logic.DownloadManager(tools=status, bot_check_clients=logic.BOT_CHECK_CLIENTS)
        self.session = worker.Session(self.manager, self.events, tr=i18n.tr)
        if not status.ok:
            self.snack(self.tr("top.ffmpeg_missing"))
        self.ids.btn_analyze.disabled = False
        self.ids.btn_download.disabled = not (self.analysis and self.chosen)
        self._refresh("settings")
        Clock.schedule_once(self._prebuild, PREBUILD_SECONDS)
        if android_env.on_android():
            try:
                self._browser = browser_route.AndroidBridge().prepare()
            except Exception as e:
                _log.warning("Browser route unavailable: %s", e)
        login_test = self._intent_extra("selftest_login")
        browser_test = self._intent_extra("selftest_browser")
        update_test = self._intent_extra("selftest_update")
        if update_test:
            # CI: find, download and install an "update" listed at this releases URL.
            self._selftest = "update"
            self.check_for_updates(quiet=True, url=update_test)
        elif browser_test:
            # CI: analyse (and on success download) a YouTube video through the browser route.
            self._use_browser_route()
            self._selftest = browser_test
            self._selftest_passes = [("video", None)]
            self.ids.url.text = browser_test
            self.analyze()
        elif login_test:
            self.sign_in_youtube(url=login_test)
            Clock.schedule_once(lambda *_: self._login and self._login.close(), 4)
        elif self._selftest:
            self.ids.url.text = self._selftest
            self._selftest_passes = [("video", None), ("audio", None), ("video", ("0:01", "0:03"))]
            self.analyze()
        elif self.pending_link:
            self._use_link(self.pending_link, shared=True)
        if not update_test and self.settings.check_updates and android_env.on_android():
            self.check_for_updates(quiet=True)
        if self._intent_extra("selftest_ui"):
            # CI: say where the named widgets are, so the emulator test taps them by name (B6-1).
            Clock.schedule_interval(self._report_where, WHERE_SECONDS)

    # Widgets the emulator test can tap by name, besides Settings rows and choices (self._named).
    UI_IDS = ("btn_paste", "url", "btn_clear", "btn_analyze", "btn_download", "btn_options", "btn_details",
              "btn_log_copy", "btn_log_clear", "btn_clear_history", "history_search", "settings_search",
              "trim_switch")

    def _report_where(self, *_):
        """Log the screen position of every named widget that can be tapped now (when it changes)."""
        offset = (0, 0)
        if android_env.on_android():
            try:
                offset = android_env.surface_offset()
            except Exception as e:
                _log.debug("Surface offset: %s", e)
        named = {name: self.ids[name] for name in self.UI_IDS}
        named.update({"nav." + tab.name: tab for tab in self.ids.nav.children})
        named.update(self._named)
        spots = []
        for name, widget in sorted(named.items()):
            spot = _on_screen(widget)
            if spot:
                spots.append(f"{name}={int(offset[0] + spot[0])},{int(offset[1] + Window.height - spot[1])}")
        line = f"where screen={self.ids.screens.current} " + " ".join(spots)
        if line != self._where:
            self._where = line
            selftest(line)

    def _selftest_url(self):
        """The ``selftest_url`` extra of the launching intent (CI only)."""
        return self._intent_extra("selftest_url")

    def _intent_extra(self, name):
        if not android_env.on_android():
            return os.environ.get("UD_" + name.upper())
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            return activity.getIntent().getStringExtra(name)
        except Exception:
            return None

    # --- Navigation, messages -----------------------------------------------------

    def switch_tab(self, name):
        screens = self.ids.screens
        order = ["history", "home", "settings"]  # as in the navigation bar
        if name in self._stale and self._stale[name]:
            self._build(name)  # before the slide, so the new screen arrives filled in
        screens.transition.direction = "left" if order.index(name) > order.index(screens.current) else "right"
        screens.current = name
        self.announce(self.t("nav." + name))

    def _build(self, name):
        self._stale[name] = False
        (self.build_settings if name == "settings" else self.build_history)()

    def _prebuild(self, *_):
        """Fill in a tab that is not on screen while the app is idle, one per frame.

        Then the first visit to Settings or History slides in at once instead
        of waiting for its rows to be made.
        """
        for name in ("settings", "history"):
            if self._stale[name] and self.ids.screens.current != name:
                self._build(name)
                Clock.schedule_once(self._prebuild, 0)
                return

    def _refresh(self, *names):
        """Rebuild these tabs now if one is on screen, else when it is next shown."""
        for name in names:
            if self.ids.screens.current == name:
                self._build(name)
            else:
                self._stale[name] = True

    def go_to(self, name):
        """Switch tabs from code, keeping the navigation bar in step."""
        for item in self.ids.nav.children:
            item.active = item.name == name
        if self.ids.screens.current != name:
            self.switch_tab(name)

    def snack(self, text):
        MDSnackbar(MDSnackbarText(text=text), y=dp(96), pos_hint={"center_x": 0.5}, size_hint_x=0.92).open()

    def announce(self, text):
        """Tell a screen reader (TalkBack) what changed; Kivy's widgets are invisible to it."""
        try:
            android_env.announce(text)
        except Exception as e:
            _log.debug("Announce: %s", e)

    def log(self, message):
        self._log_lines.append(message)
        self._log_total += 1
        if self.ids.log_card.parent is not None:  # drawn when the details are opened
            self._log_trigger()

    def _render_log(self, *_):
        """Draw the newest LOG_SHOWN lines, LOG_CHUNK to a label; only changed chunks are redrawn (B5-6)."""
        box = self.ids.log
        first = max(self._log_total - min(LOG_SHOWN, len(self._log_lines)), 0)
        lines = list(self._log_lines)[len(self._log_lines) - (self._log_total - first):]
        wanted = {}
        for number in range(first // LOG_CHUNK, (self._log_total - 1) // LOG_CHUNK + 1 if lines else 0):
            start, end = max(number * LOG_CHUNK, first), min((number + 1) * LOG_CHUNK, self._log_total)
            wanted[number] = "\n".join(lines[start - first:end - first])
        for number in [n for n in self._log_chunks if n not in wanted]:
            box.remove_widget(self._log_chunks.pop(number)[0])
        for number in sorted(wanted):
            text = wanted[number]
            label, shown = self._log_chunks.get(number, (None, None))
            if label is None:
                label = LogChunk()
                box.add_widget(label)  # newest last
            if shown != text:
                label.text = text
            self._log_chunks[number] = (label, text)
        Clock.schedule_once(lambda *_: setattr(self.ids.log_scroll, "scroll_y", 0), 0)  # the newest in view

    def copy_log(self):
        from kivy.core.clipboard import Clipboard
        Clipboard.copy("\n".join(self._log_lines))
        self.snack(self.t("log.copied"))

    def clear_log(self):
        self._log_lines.clear()
        self._log_total = 0
        for label, _text in self._log_chunks.values():
            self.ids.log.remove_widget(label)
        self._log_chunks = {}

    def toggle_details(self):
        visible = self.ids.log_card.parent is None
        _show(self.ids.log_card, visible)
        if visible:
            self._render_log()
        self.ids.details_icon.icon = "chevron-up" if visible else "chevron-down"
        self.ids.details_text.text = self.t("home.hide_details" if visible else "home.details")

    def toggle_options(self):
        shown = self.ids.options_box.parent is None
        self._show_options(shown)
        self._save_settings(show_options=shown)

    def _show_options(self, shown):
        _show(self.ids.options_box, shown)
        self.ids.options_icon.icon = "chevron-up" if shown else "chevron-down"
        self.ids.options_text.text = self.t("home.fewer_options" if shown else "home.more_options")

    def show_error(self, text):
        """The error card (B3-6): stays until closed, or until the next link is analysed."""
        self.ids.error_card.ids.error_text.text = text
        _show(self.ids.error_card, True)
        Clock.schedule_once(lambda *_: self.ids.home_scroll.scroll_to(self.ids.error_card, padding=dp(16)), 0)
        self.announce(text)

    def hide_error(self):
        _show(self.ids.error_card, False)

    def _dialog(self, title, body=None, content=None, buttons=()):
        """A Material 3 dialog; ``buttons`` are (text, callback or None)."""
        dialog = None

        def pressed(callback):
            dialog.dismiss()
            if callback:
                callback()

        parts = [MDDialogHeadlineText(text=title)]
        if body:
            parts.append(MDDialogSupportingText(text=body))
        if content is not None:
            parts.append(MDDialogContentContainer(content))
        row = [Widget()]
        for text, callback in buttons or [(self.t("common.close"), None)]:
            row.append(MDButton(MDButtonText(text=text), style="text",
                                on_release=lambda _b, c=callback: pressed(c)))
        parts.append(MDDialogButtonContainer(*row, spacing=dp(8)))
        dialog = MDDialog(*parts)
        dialog.open()
        return dialog

    def _choose(self, title, options, current, on_pick):
        """A dialog listing ``options`` [(value, label) or (value, label, icon)].

        The list scrolls inside the dialog, so long lists (languages) and
        small or landscape screens always fit.
        """
        dialog = None

        def pick(value):
            dialog.dismiss()
            if value != current or current is None:
                on_pick(value)

        rows = BoxLayout(orientation="vertical", size_hint_y=None)
        rows.bind(minimum_height=rows.setter("height"))
        for value, label, *icon in options:
            chosen = value == current
            lead = icon[0] if icon else ("radiobox-marked" if chosen else "radiobox-blank")
            row = LiteRow(icon=lead, accent=chosen and not icon, headline=label, on_release=lambda _i, v=value: pick(v))
            rows.add_widget(row)
            self._named[f"choice.{value}"] = row  # the emulator test taps choices by value
        visible = min(len(options) * dp(56), Window.height * 0.5)
        scroll = ScrollView(size_hint_y=None, height=visible, do_scroll_x=False,
                            bar_width=dp(4) if len(options) * dp(56) > visible else 0)
        scroll.add_widget(rows)
        dialog = self._dialog(title, content=scroll, buttons=[(self.t("common.cancel"), None)])
        total = len(options) * dp(56)
        values = [value for value, *_rest in options]
        if current in values and total > visible:
            # Open with the current choice in the middle, not scrolled away.
            offset = values.index(current) * dp(56) + dp(28) - visible / 2
            scroll.scroll_y = max(0.0, min(1.0, 1 - offset / (total - visible)))
        return dialog

    # --- Link ---------------------------------------------------------------------

    def paste(self, quiet=False):
        try:
            text = android_env.clipboard_text().strip()
        except Exception:
            text = ""
        links = urls.split_links(text)
        if len(links) > 1:  # several links: Analyze queues them all
            self.ids.url.text = " ".join(links)
            return
        link = android_env.find_link(text)
        if link and link != self.ids.url.text.strip():
            self.ids.url.text = link
        elif not quiet and text and not link:
            self.ids.url.text = text

    def clear_link(self):
        if self.job is None:
            self.ids.url.text = ""

    def _on_shared_text(self, text):
        link = android_env.find_link(text)
        if not link:
            return
        self.go_to("home")
        if self.tools_ready:
            self._use_link(link, shared=True)
        else:
            self.pending_link = link

    def _use_link(self, link, shared=False):
        self.pending_link = None
        if self.job in ("download", "analyze"):
            # Shared while a download runs or a link is read: it waits in the queue, as a typed link does.
            self.queue_link(link)
            return
        if self.job is not None:
            self.snack(self.tr("action.downloading"))
            return
        self.ids.url.text = link
        if shared:
            self.snack(self.t("home.shared"))
            if self.settings.auto_analyze_shared:
                self.analyze()

    def link_changed(self):
        if self.job is None and self.analysis is not None and self.ids.url.text.strip() != self.analysis_url:
            self.analysis = None
            self.ids.btn_download.disabled = True
            _show(self.ids.btn_pick, False)
            self._show_media(self.tr("link.changed"), "", "link-variant-off")

    def analyze(self, keep_mix=False):
        links = urls.split_links(self.ids.url.text)
        if len(links) > 1:
            self.queue_links(links)
            return
        if self.job == "download":
            self.add_to_queue()
            return
        if self.session is None or self.job is not None:
            return
        try:
            started = self.session.analyze(self.ids.url.text, keep_mix=keep_mix)
        except urls.UrlError as e:
            self._show_media(self.tr(e.key, **e.values), "", "alert-circle-outline")
            return
        if started:
            self._analysis_dropped = False
            self.job = "analyze"
            self.analysis = None
            self._preview = None
            self.hide_error()
            _show(self.ids.btn_skipped, False)
            _show(self.ids.media_thumb, False)
            _show(self.ids.done_row, False)
            # A song opened inside a YouTube Mix is analyzed alone; the Mix is offered afterwards.
            self._mix = None if keep_mix else urls.youtube_mix(self.ids.url.text)
            self.mix_url = None
            _show(self.ids.btn_pick, False)
            _show(self.ids.btn_mix, False)
            self.set_busy(True)  # Download turns into Cancel
            self._show_media(self.tr("link.reading"), "", "timer-sand")
            self.log(self.tr("log.fetching"))

    def _show_media(self, title, subtitle, icon):
        _show(self.ids.media_card, True)
        self.ids.media_title.text = title
        self.ids.media_sub.text = subtitle
        self.ids.media_icon.icon = icon
        _show(self.ids.media_icon, True)
        _show(self.ids.media_thumb, False)

    def _show_preview(self, preview):
        """The analysed video's picture and about how big the file will be (B4-12)."""
        self._preview = preview
        if not preview:
            return
        thumbnail = preview.get("thumbnail")
        # With a proxy set, nothing goes around it: no picture then.
        if thumbnail and not self.settings.proxy:
            self.ids.media_thumb.source = thumbnail
            _show(self.ids.media_thumb, True)
            _show(self.ids.media_icon, False)
        self._show_size()

    def _show_size(self):
        """Add "≈ 45 MB" to the media card for the mode and quality chosen now."""
        if not self._preview or self.analysis is None or self.analysis.is_playlist:
            return
        base = self.ids.media_sub.text.split("  ·  ≈")[0]
        size = worker.estimate_size(self._preview["info"], MODES[self.mode], self.quality[self.mode])
        self.ids.media_sub.text = f"{base}  ·  ≈ {history.format_size(size)}" if size else base

    def thumbnail_failed(self):
        _show(self.ids.media_thumb, False)
        _show(self.ids.media_icon, True)

    # --- Choices ------------------------------------------------------------------

    def set_mode(self, mode):
        if self.job is None:
            self.mode = mode
            self._auto_mode = None  # chosen by the user
            self._show_mode()

    def _show_mode(self):
        video = self.mode == "video"
        self.ids.btn_video.style = "filled" if video else "outlined"
        self.ids.btn_audio.style = "outlined" if video else "filled"
        self._show_choices()

    def _quality_label(self, value):
        return self.tr("quality.best") if value == "Best" else value

    def _show_choices(self):
        self.ids.btn_quality.label = f"{self.t('home.quality')}: {self._quality_label(self.quality[self.mode])}"
        self.ids.btn_format.label = f"{self.t('home.format')}: {self.fmt[self.mode].upper()}"
        self._show_size()

    def choose_quality(self, _caller=None):
        values = worker.VIDEO_QUALITIES if self.mode == "video" else worker.AUDIO_QUALITIES
        self._choose(self.t("home.quality"), [(v, self._quality_label(v)) for v in values],
                     self.quality[self.mode],
                     lambda v: (self.quality.__setitem__(self.mode, v), self._show_choices()))

    def choose_format(self, _caller=None):
        values = worker.MODE_FORMATS[MODES[self.mode]]
        self._choose(self.t("home.format"), [(v, v.upper()) for v in values], self.fmt[self.mode],
                     lambda v: (self.fmt.__setitem__(self.mode, v), self._show_choices()))

    def trim_toggled(self, active):
        _show(self.ids.trim_box, active)
        if active and self.components and not self.components.get("https", True):
            self.log("FFmpeg has no HTTPS; trimming may fail")

    # --- Download -----------------------------------------------------------------

    def set_busy(self, busy):
        # While a download runs, more links can be added to the queue.
        queueing = busy and self.job == "download"
        for name in ("btn_video", "btn_audio", "btn_quality", "btn_format", "trim_switch", "trim_start",
                     "trim_end"):
            self.ids[name].disabled = busy
        for name in ("btn_analyze", "btn_clear", "url"):
            self.ids[name].disabled = busy and not queueing
        self.ids.analyze_text.text = self.tr("queue.add" if queueing else "link.analyze")
        self.ids.analyze_icon.icon = "playlist-plus" if queueing else "magnify"
        # Downloads and analyses can be cancelled (a long playlist takes a while to read).
        cancellable = busy and self.job in ("download", "analyze")
        self.ids.download_icon.icon = "close" if busy else "download"
        self.ids.download_text.text = self.tr("action.cancel" if cancellable else "action.download")
        self.ids.btn_download.style = "tonal" if busy else "filled"
        self.ids.btn_download.disabled = busy and not cancellable
        # A running download can be paused (worker.Session.pause).
        downloading = busy and self.job == "download"
        self.ids.btn_pause.opacity = 1 if downloading else 0
        self.ids.btn_pause.disabled = not downloading
        self.ids.btn_pause.icon = "play" if downloading and self.session.paused else "pause"
        self._sync_background()

    def download(self, mobile_data_ok=False):
        if self.job == "analyze":
            self.cancel_analysis()
            return
        if self.job == "download":
            self._cancelled = True
            self.session.cancel()
            self.ids.download_text.text = self.tr("action.cancelling")
            self.ids.btn_download.disabled = True
            return
        if self.job is not None or not self.analysis or not self.chosen:
            return
        if not self.download_dir:
            self.snack(self.tr("folder.error_title"))
            return
        error, _warning = filenames.check_folder(self.download_dir)
        if error:
            self._dialog(self.tr("folder.error_title"), error)
            return
        if self.settings.wifi_only and not mobile_data_ok and android_env.is_metered():
            self._dialog(self.t("wifi.ask_title"), self.t("wifi.ask_body"),
                         buttons=[(self.t("common.cancel"), None),
                                  (self.t("wifi.anyway"), lambda: self.download(mobile_data_ok=True))])
            return
        free = filenames.low_space_mb(self.download_dir)
        if free is not None:  # a warning only: the files may still fit
            self.log(self.tr("folder.low_space", mb=free))
            self.snack(self.tr("folder.low_space", mb=free))
        trim = self.ids.trim_switch.active
        start, end = (self.ids.trim_start.text, self.ids.trim_end.text) if trim else ("", "")
        if trim and self.analysis.is_playlist:
            self.snack(self.t("home.no_trim_playlist"))
            return
        if trim:
            try:
                if logic.parse_trim_range(start, end) is None:
                    self.snack(self.tr("trim.empty"))
                    return
            except logic.TrimError as e:
                self.snack(str(e))
                return
        options = worker.build_options(MODES[self.mode], self.download_dir, fmt=self.fmt[self.mode],
                                       quality=self.quality[self.mode], trim_start=start, trim_end=end)
        if self.settings.subtitles:
            options.update(subtitles=True,
                           subtitle_langs=logic.subtitle_languages(i18n.current(), self.settings.subtitle_langs),
                           subtitle_embed=self.settings.subtitle_embed)
        if self.settings.sponsorblock:
            options.update(sponsorblock=True, sponsorblock_categories=self.settings.sponsorblock_categories)
        self._start_download(dataclasses.replace(self.analysis, items=list(self.chosen)), options, mobile_data_ok)

    def _start_download(self, analysis, options, mobile_data_ok=False):
        self._set_platform_options()
        if self.session.download(analysis, options):
            self._options = options
            self.last_url = self.analysis_url
            self.last_file = None
            _show(self.ids.done_row, False)
            self.hide_error()
            self.job = "download"
            self._cancelled = False
            self._mobile_data_ok = mobile_data_ok
            self._wifi_paused = False
            self.set_busy(True)
            self._keep_awake(True)
            _show(self.ids.progress_card, True)
            self.ids.progress.value = 0
            self.ids.progress_title.text = self.tr("progress.starting")
            self.ids.progress_detail.text = ""
            self.log(self.tr("log.folder", folder=self.download_dir))
            self._ask_notifications()

    def _show_chosen(self):
        if self.analysis is not None and self.analysis.is_playlist:
            self.ids.pick_text.text = self.tr("playlist.selected", count=len(self.chosen)) + \
                f" / {len(self.analysis.items)}"

    def choose_videos(self):
        """Tick the playlist entries to download; ones downloaded before are marked.

        A search narrows the list; rows are made PICKER_PAGE at a time ("Show
        more"), so a list of thousands opens at once (B3-9, B5-5). Entries the
        site does not offer are listed at the end with the reason.
        """
        if self.analysis is None or self.job is not None:
            return
        items = self.analysis.items
        skipped = self.analysis.skipped
        before = {id(item) for item in playlist.downloaded_before(items, [e.url for e in self.history.entries])}
        ticked = {id(item) for item in self.chosen}
        rows = BoxLayout(orientation="vertical", size_hint_y=None)
        rows.bind(minimum_height=rows.setter("height"))
        lines = []        # (row, item) on screen
        shown = [items]   # the entries the search leaves
        more_text = MDButtonText(text="")
        more = MDButton(more_text, style="text")
        count = MDLabel(text="", adaptive_height=True, font_style="Body", role="small",
                        theme_text_color="Secondary")

        def draw(row, item):
            row.icon = "checkbox-marked" if id(item) in ticked else "checkbox-blank-outline"
            row.accent = id(item) in ticked

        def toggle(row, item):
            ticked.symmetric_difference_update({id(item)})
            draw(row, item)
            show_count()

        def show_count():
            count.text = self.tr("playlist.selected", count=len(ticked)) + f" / {len(items)}"

        def tick(which):
            ticked.difference_update(id(item) for item in shown[0])
            ticked.update(id(item) for item in shown[0] if which(item))  # only what the search shows
            for row, item in lines:
                draw(row, item)
            show_count()

        def add_rows(*_):
            start = len(lines)
            for item in shown[0][start:start + PICKER_PAGE]:
                title = f"{item.index}. {item.title}" if item.index else item.title
                row = LiteRow(headline=title, supporting=self.tr("playlist.downloaded") if id(item) in before else "")
                row.bind(on_release=lambda r, i=item: toggle(r, i))
                draw(row, item)
                rows.add_widget(row, index=len(rows.children) - len(lines))  # above the skipped ones
                lines.append((row, item))
            left = len(shown[0]) - len(lines)
            more_text.text = self.tr("history.more", count=left) if left > 0 else ""
            _show(more, left > 0)

        def search(text):
            words = text.casefold().split()
            shown[0] = [item for item in items if all(w in (item.title or "").casefold() for w in words)]
            for row, _item in lines:
                rows.remove_widget(row)
            lines.clear()
            add_rows()
            if not shown[0]:
                more_text.text = self.tr("playlist.no_match")
                _show(more, True)

        for item in skipped:  # at the end, not tickable
            rows.add_widget(LiteRow(icon="cancel", headline=item.title or item.url,
                                    supporting=i18n.tr_message(item.skip_reason or "")))
        field = MDTextField(MDTextFieldLeadingIcon(icon="magnify"),
                            MDTextFieldHintText(text=self.tr("playlist.search")), mode="outlined", multiline=False)
        field.bind(text=lambda _f, text: search(text))
        # The buttons wrap onto a second line when their texts do not fit.
        quick = StackLayout(size_hint_y=None, spacing=dp(8))
        quick.bind(minimum_height=quick.setter("height"))
        for text, which in ((self.tr("playlist.select_all"), lambda i: True),
                            (self.tr("playlist.select_none"), lambda i: False),
                            (self.tr("playlist.select_new"), lambda i: id(i) not in before)):
            quick.add_widget(MDButton(MDButtonText(text=text), style="outlined",
                                      on_release=lambda _b, w=which: tick(w)))
        more.bind(on_release=add_rows)
        scroll = ScrollView(size_hint_y=None, height=Window.height * 0.4, do_scroll_x=False, bar_width=dp(4))
        page = BoxLayout(orientation="vertical", size_hint_y=None)
        page.bind(minimum_height=page.setter("height"))
        page.add_widget(rows)
        page.add_widget(more)
        scroll.add_widget(page)
        add_rows()
        show_count()
        box = MDBoxLayout(field, quick, count, scroll, orientation="vertical", adaptive_height=True, spacing=dp(8))

        def done():
            self.chosen = [item for item in items if id(item) in ticked]
            self._show_chosen()
            self.ids.btn_download.disabled = not self.chosen
            app_settings.save_playlist_choice(self.choices_path, self.analysis_url, [i.url for i in items],
                                              [i.url for i in self.chosen])

        self._dialog(self.tr("playlist.title"), content=box,
                     buttons=[(self.t("common.cancel"), None), (self.t("common.done"), done)])

    # --- Background downloads -----------------------------------------------------

    def _sync_background(self):
        """Run DownloadService while a download or the link queue is going."""
        if self._notice is None:
            return
        wanted = self.job == "download" or bool(self.link_queue) or self._from_queue
        try:
            if wanted and not self._notice.running and self.job == "download":
                self._finished = None
                self._notice.start(self.t("notify.channel"), self.tr("progress.starting"),
                                   labels=self._notice_labels())
            elif not wanted and self._notice.running:
                # Only worth a notification when the user is not looking at the app.
                title, text = self._finished if self._finished and self._paused else (None, "")
                self._notice.stop(title, text)
        except Exception as e:
            _log.warning("Download notification: %s", e)

    def _notify(self, force=False):
        if self._notice is None or not self._notice.running:
            return
        try:
            self._notice.update(self.ids.progress_title.text, self.ids.progress_detail.text,
                                int(self.ids.progress.value), force=force,
                                paused=self.session is not None and self.session.paused)
        except Exception as e:
            _log.warning("Download notification: %s", e)

    def _notice_labels(self):
        return (self.tr("action.pause"), self.tr("action.resume"), self.tr("action.cancel"), self.t("home.open"))

    def _poll_notice(self, *_):
        """Pause, Resume and Cancel pressed in the notification (B4-1)."""
        if self._notice is None or not self._notice.running:
            return
        try:
            action = self._notice.take_action()
        except Exception as e:
            _log.warning("Notification buttons: %s", e)
            return
        if not action or self.job != "download":
            return
        if action == "cancel":
            self.download()  # Download reads Cancel while a download runs
        elif (action == "pause") != self.session.paused:
            self.toggle_pause()

    def _ask_notifications(self):
        if self._notice is None or self._asked_notifications:
            return
        self._asked_notifications = True
        try:
            android_env.ask_notification_permission()
        except Exception as e:
            _log.warning("Notification permission: %s", e)

    def _set_platform_options(self):
        options = {**getattr(self, "_js_options", {}), **app_settings.download_speed_options(self.settings)}
        cookies = youtube_login.cookie_file(self.user_data_dir)
        if cookies:
            options["cookiefile"] = cookies
        logic.set_platform_options(options)
        # The sites' cookies come in the cookie file; this only tells logic where the app is signed in.
        sites = [site.name for site in youtube_login.SITES if youtube_login.saved(self.user_data_dir, site)]
        logic.set_reddit_sign_in(browser_cookies.AppSignIn(sites) if sites else None)
        logic.set_network_options(self.settings.proxy)

    def _keep_awake(self, on):
        if not android_env.on_android():
            return
        try:
            if self.settings.keep_screen_on or not on:
                android_env.set_keep_screen_on(on)
            if self._wake_lock:
                self._wake_lock.acquire() if on else self._wake_lock.release()
        except Exception as e:
            _log.warning("Keep awake: %s", e)

    # --- Events (main thread) -----------------------------------------------------

    def cancel_analysis(self):
        """Stop waiting for the analysis; what it still sends is dropped."""
        self.session.cancel_analysis()
        self._analysis_dropped = True
        self.job = None
        self._mix = None
        self._from_queue = False
        self.clear_link_queue()  # Cancel stops the whole queue
        self.set_busy(False)
        self.ids.btn_download.disabled = True
        self._show_media(self.tr("log.analysis_cancelled"), "", "close-circle-outline")
        self.log(self.tr("log.analysis_cancelled"))

    def _dropped(self):
        """True for the result of a cancelled analysis that was already on its way."""
        return self.job is None and self._analysis_dropped

    def _on_analysis_progress(self, count, total=None):
        """A long playlist is being read: "120 / 850 read" (Cancel stops it)."""
        if self.job != "analyze" or self._dropped():
            return
        text = (self.tr("link.read_count_of", count=count, total=total) if total
                else self.tr("link.read_count", count=count))
        self._show_media(self.tr("link.reading"), text, "timer-sand")

    def _on_analysis_done(self, analysis, url, preview=None):
        if self._dropped():
            return
        self.job = None
        mix, self._mix = self._mix, None
        self.analysis = analysis
        self.analysis_url = self.ids.url.text.strip()
        self.set_busy(False)
        # Playlist entries downloaded before start unticked; a playlist opened
        # before gets the entries the user ticked then (B4-8).
        before = playlist.downloaded_before(analysis.items, [e.url for e in self.history.entries]) \
            if analysis.is_playlist else []
        saved = app_settings.load_playlist_choices(self.choices_path).get(self.analysis_url) \
            if analysis.is_playlist else None
        remembered = app_settings.remembered_choice(saved, analysis.items, before)
        ids_before = {id(item) for item in before}
        self.chosen = remembered if remembered is not None else [
            item for item in analysis.items if id(item) not in ids_before]
        if playlist.found_by_search(analysis) and self.mode != "audio":
            # Spotify links are songs: download them as audio (the user can
            # switch back). Only for this link; the next one gets the mode back.
            self._auto_mode = self.mode
            self.mode = "audio"
            self._show_mode()
            self.log(self.tr("log.spotify"))
        elif not playlist.found_by_search(analysis) and self._auto_mode is not None:
            self.mode, self._auto_mode = self._auto_mode, None
            self._show_mode()
        _show(self.ids.btn_pick, analysis.is_playlist and bool(analysis.items))
        self._show_chosen()
        _show(self.ids.btn_skipped, bool(analysis.skipped) and bool(analysis.items))
        self.ids.skipped_text.text = self.t("home.skipped_why", count=len(analysis.skipped))
        if analysis.is_playlist:
            sub = self.tr("media.videos", count=len(analysis.items))
            if analysis.skipped:
                sub += ", " + self.tr("media.unavailable", count=len(analysis.skipped))
            self._show_media(analysis.title, f"{self.tr('media.playlist')} · {sub}", "playlist-play")
            self.log(self.tr("log.playlist", title=analysis.title, count=len(analysis.items),
                             skipped=len(analysis.skipped)))
        elif analysis.items:
            self._show_media(analysis.title, self.tr("media.video"), "movie-open-outline")
            self._show_preview(preview)
            self.log(self.tr("log.video", title=analysis.title))
            if mix and not self._from_queue:
                self.mix_url = mix
                self.ids.media_sub.text = self.tr("mix.offer")
                _show(self.ids.btn_mix, True)
        else:
            reason = analysis.skipped[0].skip_reason if analysis.skipped else None
            text = (self.tr("link.nothing_reason", reason=i18n.tr_message(reason)) if reason
                    else self.tr("link.nothing"))
            self._show_media(text, "", "alert-circle-outline")
            self.show_error(text)
        self.ids.btn_download.disabled = not self.chosen
        self.announce(self.ids.media_title.text)
        if browser_route.enabled():
            self.log(self.t("youtube.browser_count", count=browser_route.request_count()))
        selftest(f"analysis items={len(analysis.items)} title={analysis.title!r} "
                 f"browser_requests={browser_route.request_count()}")
        if self._from_queue:
            # Queued links download without questions (playlists: only new entries).
            self._from_queue = False
            if not self.chosen:
                self.log(self.tr("log.queue_nothing_new", title=analysis.title))
                Clock.schedule_once(lambda *_: self._next_in_queue(), 0)
            else:
                self.download()
            return
        if self._selftest and analysis.items:
            self._next_selftest_pass()

    def _next_selftest_pass(self):
        if not self._selftest_passes:
            self._selftest = None
            return
        mode, trim = self._selftest_passes.pop(0)
        self.mode = mode
        self._show_mode()
        self.ids.trim_switch.active = bool(trim)
        if trim:
            self.ids.trim_start.text, self.ids.trim_end.text = trim
        selftest(f"pass mode={mode} trim={trim}")
        self.download()

    def download_mix(self):
        """Analyze the whole Mix the last song was opened in."""
        if self.mix_url and self.job is None:
            self.ids.url.text = self.mix_url
            _show(self.ids.btn_mix, False)
            self.analyze(keep_mix=True)

    def _on_analysis_failed(self, message):
        if self._dropped():
            return
        self.job = None
        self._mix = None
        self.set_busy(False)
        self.ids.btn_download.disabled = True
        needs = logic.sign_in_offer(message)
        site = youtube_login.site_named(needs or "")
        if site is not None:
            message = self.t("signin.needed", site=site.name)  # the in-app sign-in, not the browser's
        elif needs:
            message = self.t("signin.not_here", site=needs)
        self._show_media(self.tr("link.nothing_reason", reason=i18n.tr_message(message)), "", "alert-circle-outline")
        self.show_error(i18n.tr_message(message))
        self.log(i18n.tr_message(message))
        if self._from_queue:
            self._from_queue = False
            Clock.schedule_once(lambda *_: self._next_in_queue(), 0)
        selftest(f"analysis failed: {message} browser_requests={browser_route.request_count()}")
        if site is not None and android_env.on_android():
            self._offer_sign_in(site)
            return
        if not logic.is_bot_check(message) or not android_env.on_android():
            return
        if self._browser is not None and not browser_route.enabled():
            # Try again with YouTube's requests going through the phone's browser engine.
            self._use_browser_route()
            self.log(self.t("youtube.via_browser"))
            self.analyze()
        else:
            self._dialog(self.t("youtube.bot_title"), self.t("youtube.bot_body"),
                         buttons=[(self.t("youtube.ok_button"), None)])

    def show_skipped(self):
        """Why each left-out entry of the playlist was left out (B3-4)."""
        if self.analysis is None or not self.analysis.skipped:
            return
        rows = BoxLayout(orientation="vertical", size_hint_y=None)
        rows.bind(minimum_height=rows.setter("height"))
        for item in self.analysis.skipped[:PICKER_PAGE * 5]:
            rows.add_widget(LiteRow(icon="cancel", headline=item.title or item.url,
                                    supporting=i18n.tr_message(item.skip_reason or "")))
        visible = min(len(rows.children) * dp(72), Window.height * 0.5)
        scroll = ScrollView(size_hint_y=None, height=visible, do_scroll_x=False, bar_width=dp(4))
        scroll.add_widget(rows)
        self._dialog(self.t("home.skipped_title", count=len(self.analysis.skipped)), content=scroll)

    def _offer_sign_in(self, site):
        """``site`` refused a post without sign-in: offer the in-app sign-in, then analyse again."""
        def sign_in():
            self._retry_after_sign_in = True
            self._sign_in(site)

        if site is youtube_login.REDDIT:
            title, body = self.t("reddit_login.ask_title"), self.t("reddit_login.ask_body")
        else:
            title, body = self.tr("signin.ask_title", site=site.name), self.t("signin.ask_body", site=site.name)
        self._dialog(title, body, buttons=[(self.t("common.cancel"), None),
                                           (self.t("signin.sign_in", site=site.name), sign_in)])

    def _on_item_started(self, position, total, title):
        self._stderr.clear()
        self.ids.progress.value = 0
        self.ids.progress_title.text = title if total == 1 else self.tr(
            "progress.item", position=position, total=total, title=title)
        self.ids.progress_detail.text = ""
        self._notify(force=True)

    def _on_progress(self, fraction, text, detail):
        self.ids.progress.value = fraction * 100
        if self.session.paused:  # an update sent just before the pause
            detail = self.t("wifi.paused") if self._wifi_paused else self.tr("progress.paused")
        self.ids.progress_detail.text = f"{text}  {detail}".strip()
        self._notify()

    # --- Pause and Wi-Fi only -----------------------------------------------------

    def toggle_pause(self):
        """Pause the running download where it is, or let it go on."""
        if self.job != "download" or self._cancelled:
            return
        self._set_paused(not self.session.paused)

    def _set_paused(self, paused, wifi=False):
        if paused:
            self.session.pause()
            self.log(self.t("wifi.paused") if wifi else self.tr("log.paused"))
            self.ids.progress_detail.text = self.t("wifi.paused") if wifi else self.tr("progress.paused")
        else:
            self.session.resume()
            self.log(self.t("wifi.resumed") if wifi else self.tr("log.resumed"))
        self._wifi_paused = paused and wifi
        self.ids.btn_pause.icon = "play" if paused else "pause"
        self._notify(force=True)

    def _watch_network(self, *_):
        """With Wi-Fi only on, hold a download while the phone is on mobile data."""
        if self.job != "download" or self._cancelled or not self.settings.wifi_only or self._mobile_data_ok:
            return
        metered = android_env.is_metered()
        if metered and not self.session.paused:
            self._set_paused(True, wifi=True)
            self.snack(self.t("wifi.paused"))
        elif not metered and self._wifi_paused:
            self._set_paused(False, wifi=True)
            self.snack(self.t("wifi.resumed"))

    def _on_stage(self, text):
        self.ids.progress_detail.text = i18n.tr_message(text)
        self._notify()

    def _on_item_done(self, result):
        if result.status is ItemStatus.COMPLETED:
            self.log(self.tr("log.saved", path=result.path))
            self.last_file = result.path or self.last_file
            if self.settings.save_history and result.path:
                # Written once at the end of the job (and every few entries meanwhile; B5-3).
                entry = self.history.add(result.title, result.path, url=result.url,
                                         kind="audio" if self.mode == "audio" else "video", save=False)
                self._history_added(entry)
                self._show_week()
            if android_env.on_android():
                try:
                    android_env.scan_media(result.path)
                except Exception as e:
                    _log.warning("Media scan failed: %s", e)
        else:
            line = self.tr("log." + result.status.value, title=result.title)
            self.log(line + (f" ({i18n.tr_message(result.error)})" if result.error else ""))
            if result.status is ItemStatus.FAILED:
                for detail in list(self._stderr)[-6:]:
                    self.log(f"  {detail}")
        background = self._notice is not None and self._notice.service_running()
        selftest(f"item {result.status.value} path={result.path} error={result.error} background={background}")

    def _on_native_stderr(self, line):
        """Worker thread: a line a program (usually FFmpeg) wrote to stderr."""
        self._stderr.append(line)
        print(f"UDSTDERR {line}", flush=True)  # Kivy's logger would mangle FFmpeg's text

    def _on_job_done(self, summary):
        headline = summary.headline(label=lambda status: self.tr("status." + status.value),
                                    nothing=self.tr("summary.nothing"))
        self._finished = (self.tr(summary.title_key()), headline)
        self.job = None
        self.last_summary = summary
        try:
            self.history.flush()
        except OSError as e:
            _log.warning("Cannot save the history: %s", e)
        self.set_busy(False)
        self._keep_awake(False)
        self.log(self.tr("log.result", summary=headline))
        self.ids.progress_title.text = self.tr(summary.title_key())
        self.ids.progress_detail.text = headline
        if summary.all_ok:
            self.ids.progress.value = 100
            self.ids.progress_detail.text = self.t("home.saved", folder=self.download_dir)
        self._show_done_buttons()
        failed = summary.with_status(ItemStatus.FAILED)
        if failed:
            first = i18n.tr_message(failed[0].error or "")
            self.show_error(self.tr("band.failed", count=len(failed)) + (f"\n{first}" if first else ""))
        self.announce(f"{self.ids.progress_title.text}. {headline}")
        selftest(f"job done all_ok={summary.all_ok}")
        if self._cancelled and self.link_queue:
            self.clear_link_queue()  # Cancel stops the whole queue
        if self.link_queue:
            Clock.schedule_once(lambda *_: self._next_in_queue(), 0)
        elif self._selftest:
            self._next_selftest_pass()

    def _show_done_buttons(self):
        """Open / Share the last file, Retry failed, Download again (B3-5, B4-5)."""
        failed = len(self._failed_items())
        has_file = bool(self.last_file) and os.path.exists(self.last_file)
        _show(self.ids.btn_open_file, has_file)
        _show(self.ids.btn_share_file, has_file)
        _show(self.ids.btn_retry, failed > 0)
        self.ids.retry_text.text = self.tr("action.retry_n", count=failed)
        _show(self.ids.btn_again, bool(self.last_url))
        _show(self.ids.done_row, has_file or failed > 0 or bool(self.last_url))

    def _failed_items(self):
        if self.last_summary is None:
            return []
        return [r.source or {"url": r.url, "title": r.title} for r in self.last_summary.with_status(ItemStatus.FAILED)]

    def open_last_file(self, share=False):
        if self.last_file:
            self.open_file(self.last_file, share=share)

    def retry_failed(self):
        """Download only the items that failed last time, with the same choices."""
        items = self._failed_items()
        if not items or self.job is not None or self.session is None:
            return
        self.log(self.tr("log.retrying", count=len(items)))
        fields = {f.name for f in dataclasses.fields(QueueItem)}
        queue = [QueueItem(**{k: v for k, v in item.items() if k in fields}) for item in items]
        title = self.analysis.title if self.analysis else queue[0].title
        self._start_download(AnalysisResult(title=title, items=queue, is_playlist=len(queue) > 1),
                             self._options or {}, self._mobile_data_ok)

    def download_again(self):
        """Read the last download's link again, to download it once more (another mode or quality)."""
        if self.last_url and self.job is None:
            self.ids.url.text = self.last_url
            self.go_to("home")
            self.analyze()

    # --- Link queue ---------------------------------------------------------------

    def add_to_queue(self):
        """Put the link in the field at the end of the queue (while a download runs)."""
        if self.queue_link(self.ids.url.text):
            self.ids.url.text = ""

    def queue_link(self, text):
        """Put one link at the end of the queue; False when it is not a link."""
        try:
            url = urls.normalize_url(text)
        except urls.UrlError as e:
            self.snack(self.tr(e.key, **e.values))
            return False
        self.link_queue.append(url)
        self.log(self.tr("log.queue_added", url=url))
        self.snack(self.tr("log.queue_added", url=url))
        self._show_link_queue()
        return True

    def queue_links(self, links):
        """Download ``links`` one after another, without questions (several pasted at once)."""
        self.link_queue.extend(links)
        self.ids.url.text = ""
        self.log(self.tr("log.batch", count=len(links)))
        self.snack(self.tr("log.batch", count=len(links)))
        self._show_link_queue()
        if self.job is None:
            self._next_in_queue()

    def clear_link_queue(self):
        if self.link_queue:
            self.link_queue = []
            self.log(self.tr("log.queue_cleared"))
        self._show_link_queue()

    def _show_link_queue(self):
        count = len(self.link_queue)
        self.ids.queue_text.text = self.tr("queue.waiting", count=count) if count else ""
        _show(self.ids.queue_row, bool(count))
        self._sync_background()

    def show_link_queue(self):
        """The waiting links (B3-8): tap one to move it up or take it out."""
        if not self.link_queue:
            return
        options = [(i, link, "link-variant") for i, link in enumerate(self.link_queue)]

        def picked(index):
            if index >= len(self.link_queue):
                return
            link = self.link_queue[index]
            moves = [("up", self.tr("queue.up"), "arrow-up"), ("remove", self.tr("queue.remove"), "close")]

            def act(action):
                if link not in self.link_queue:
                    return
                where = self.link_queue.index(link)
                if action == "remove":
                    del self.link_queue[where]
                elif where > 0:
                    self.link_queue.insert(where - 1, self.link_queue.pop(where))
                self._show_link_queue()
                self.show_link_queue()

            self._choose(link, [m for m in moves if m[0] != "up" or index > 0], None, act)

        self._choose(self.tr("queue.waiting", count=len(self.link_queue)), options, None, picked)

    def _next_in_queue(self):
        """Analyze and download the next queued link, if any."""
        if not self.link_queue or self.job is not None:
            self._show_link_queue()
            return
        # Set first: the background service keeps running between two links.
        self._from_queue = True
        url = self.link_queue.pop(0)
        self._show_link_queue()
        self.log(self.tr("log.queue_next", url=url))
        self.ids.url.text = url
        self.analyze()
        if self.job is None:  # the link was rejected
            self._from_queue = False
            self._next_in_queue()

    # --- History ------------------------------------------------------------------

    def build_history(self):
        """The History list: newest first, HISTORY_STEP rows at a time, narrowed by the search (B3-10).

        Whether each file is still there is looked up on a worker thread, so
        a long list opens without waiting for the storage (B5-4).
        """
        box = self.ids.history_list
        box.clear_widgets()
        self._history_rows = {}
        entries = self.history.search(self._history_filter)
        if not entries:
            text = self.tr("history.no_match") if self._history_filter else self.t("history.empty")
            box.add_widget(MDLabel(text=text, halign="center", adaptive_height=True,
                                   padding=(dp(24), dp(48)), theme_text_color="Secondary"))
            return
        shown = entries[:self._history_shown]
        for entry in shown:
            row = self._history_row(entry)
            box.add_widget(row)
            if not self._history_filter:
                self._history_rows[entry.path] = row
        left = len(entries) - len(shown)
        if left > 0:
            more = LiteRow(icon="chevron-down", headline=self.tr("history.more", count=left))
            more.bind(on_release=lambda *_: self._more_history())
            box.add_widget(more)
        rows = [(entry, row) for entry, row in zip(shown, list(reversed(box.children))) if isinstance(row, LiteRow)]
        threading.Thread(target=self._check_history_files, args=(rows,), daemon=True).start()

    def _history_row(self, entry):
        when = android_env.format_date(entry.time) if entry.time else ""
        ext = os.path.splitext(entry.path)[1].lstrip(".").upper()
        row = LiteRow(
            icon="music-note" if entry.kind == "audio" else "movie-outline",
            headline=entry.title or os.path.basename(entry.path),
            supporting=" · ".join(part for part in (ext, when) if part),
            trailing="dots-vertical",
        )
        row.bind(on_release=lambda r, e=entry: self._history_menu(r, e))
        return row

    def _check_history_files(self, rows):
        """Worker thread: mark the rows whose file was moved or deleted."""
        missing = [(entry, row) for entry, row in rows if not os.path.exists(entry.path)]
        if missing:
            Clock.schedule_once(lambda *_: self._mark_missing(missing), 0)

    def _mark_missing(self, missing):
        note = self.t("history.missing")
        for _entry, row in missing:
            if note not in row.supporting:
                row.supporting += f" · {note}"

    def _more_history(self):
        self._history_shown += HISTORY_STEP
        self._build("history")

    def search_history(self, text):
        self._history_filter = text.strip()
        self._history_shown = HISTORY_STEP
        self._refresh("history")

    def _history_added(self, entry):
        """A download finished: put its row on top instead of making the whole list again (B5-2)."""
        box = self.ids.history_list
        if self._stale["history"] or self._history_filter or not self._history_rows:
            self._refresh("history")
            return
        old = self._history_rows.pop(entry.path, None)
        if old is not None:
            box.remove_widget(old)
        row = self._history_row(entry)
        box.add_widget(row, index=len(box.children))  # the top
        self._history_rows[entry.path] = row

    def _history_removed(self, path):
        row = self._history_rows.pop(path, None)
        if row is None or self._history_filter:
            self._refresh("history")
        else:
            self.ids.history_list.remove_widget(row)
            if not self.history.entries:
                self._refresh("history")

    def _history_menu(self, _caller, entry):
        options = [("open", self.t("home.open"), "open-in-new"),
                   ("share", self.t("history.share"), "share-variant-outline"),
                   ("again", self.tr("history.again"), "download-multiple"),
                   ("remove", self.t("history.delete"), "delete-outline")]

        def picked(action):
            if action == "remove":
                removed = self.history.remove(entry.path)
                self._history_removed(entry.path)
                self._show_week()
                if removed:
                    self._undo_snack(self.tr("history.removed", title=entry.title or os.path.basename(entry.path)),
                                     lambda: self._restore_history(*removed))
            elif action == "again":
                if not entry.url:
                    self.snack(self.t("history.no_link"))
                elif self.job is not None:
                    self.queue_link(entry.url)
                else:
                    self.go_to("home")
                    self.ids.url.text = entry.url
                    self.analyze()
            else:
                self.open_file(entry.path, share=action == "share")

        self._choose(entry.title or os.path.basename(entry.path), options, None, picked)

    def _restore_history(self, entry, index):
        self.history.restore(entry, index)
        self._refresh("history")
        self._show_week()

    def _undo_snack(self, text, undo):
        """A message with an Undo button, a little longer than the others."""
        bar = None

        def pressed(*_):
            bar.dismiss()
            undo()

        bar = MDSnackbar(
            MDSnackbarSupportingText(text=text),
            MDSnackbarButtonContainer(
                MDSnackbarActionButton(MDSnackbarActionButtonText(text=self.tr("history.undo")), on_release=pressed),
                pos_hint={"center_y": 0.5}),
            y=dp(96), orientation="horizontal", pos_hint={"center_x": 0.5}, size_hint_x=0.92, duration=6)
        bar.open()
        return bar

    def open_file(self, path, share=False):
        if not os.path.exists(path):
            self.snack(self.t("history.missing"))
            return
        if not android_env.on_android():
            self.snack(path)
            return
        mime = MIME.get(os.path.splitext(path)[1].lstrip(".").lower(), "*/*")

        def failed(error):
            _log.warning("Open %s: %s", path, error)
            Clock.schedule_once(lambda *_: self.snack(self.t("history.open_failed")))

        try:
            android_env.open_or_share(path, mime, share=share, on_error=failed)
        except Exception as e:
            failed(e)

    def confirm_clear_history(self):
        def clear():
            entries = list(self.history.entries)
            self.history.clear()
            self._refresh("history")
            self._show_week()
            if entries:
                self._undo_snack(self.t("history.cleared"), lambda: self._undo_clear(entries))

        self._dialog(self.t("history.clear"), self.t("history.clear_body"),
                     buttons=[(self.t("common.cancel"), None), (self.t("common.remove"), clear)])

    def _undo_clear(self, entries):
        self.history.entries = entries + [e for e in self.history.entries if e.path not in {x.path for x in entries}]
        del self.history.entries[history.LIMIT:]
        self.history.save()
        self._refresh("history")
        self._show_week()

    # --- YouTube sign-in ----------------------------------------------------------

    def _use_browser_route(self):
        """Send yt-dlp's YouTube requests through a hidden WebView for the rest of the session."""
        if self._browser is not None:
            browser_route.enable(self._browser)

    def sign_in_youtube(self, url=None):
        self._sign_in(youtube_login.YOUTUBE, url)

    def sign_in_reddit(self, url=None):
        self._sign_in(youtube_login.REDDIT, url)

    def sign_in_instagram(self, url=None):
        self._sign_in(youtube_login.INSTAGRAM, url)

    def _sign_in(self, site, url=None):
        if not android_env.on_android() or self._login is not None:
            return
        self._login = youtube_login.LoginView(
            lambda header: self.events.post("youtube_login", header=header, site=site.name),
            done_text=self.t("youtube.done"), site=site, dark=bool(self._dark))
        try:
            self._login.open(url)
        except Exception as e:
            self._login = None
            self.snack(self.t("crash.error", error=e))

    def _on_youtube_login(self, header, site="YouTube"):
        self._login = None
        site = youtube_login.site_named(site) or youtube_login.YOUTUBE
        ok = youtube_login.save(self.user_data_dir, header, site)
        selftest(f"login closed site={site.name} signed_in={ok}")
        self._set_platform_options()
        self._refresh("settings")
        self.snack(self.t("signin.ok", site=site.name) if ok else self.t("youtube.failed"))
        if ok and self._retry_after_sign_in:
            self.analyze()  # the post that needed the sign-in
        self._retry_after_sign_in = False

    def sign_out_youtube(self):
        self._sign_out(youtube_login.YOUTUBE)

    def sign_out_reddit(self):
        self._sign_out(youtube_login.REDDIT)

    def sign_out_instagram(self):
        self._sign_out(youtube_login.INSTAGRAM)

    def _sign_out(self, site):
        def sign_out():
            youtube_login.forget(self.user_data_dir, site)
            try:
                youtube_login.clear_webview_cookies()
            except Exception as e:
                _log.warning("Clear WebView cookies: %s", e)
            self._set_platform_options()
            self._refresh("settings")
            self.snack(self.t("signin.signed_out", site=site.name))

        self._dialog(self.t("signin.signed_in", site=site.name),
                     buttons=[(self.t("common.cancel"), None), (self.t("youtube.sign_out"), sign_out)])

    # --- Settings -----------------------------------------------------------------

    def _save_settings(self, **changes):
        for key, value in changes.items():
            setattr(self.settings, key, value)
        self.settings = self.settings.normalized()
        try:
            app_settings.save(self.settings_path, self.settings)
        except OSError as e:
            _log.warning("Cannot save settings: %s", e)

    def build_settings(self):
        s = self.settings
        t = self.t
        groups = self._settings_rows = []  # [(section, [rows])], for the search

        def add(row, name):
            groups[-1][1].append(row)  # search_settings puts them on the page
            self._named["settings." + name] = row

        def section(title):
            groups.append((LiteSection(text=title), []))

        def choice(icon, title, options, current, apply, name):
            """A row showing the current value; picking another updates it in place."""
            labels = {value: label for value, label, *_ in options}
            row = LiteRow(icon=icon, headline=title, supporting=labels.get(current, str(current)))
            chosen = [current]

            def picked(value):
                chosen[0] = value
                row.supporting = labels.get(value, str(value))
                apply(value)

            row.bind(on_release=lambda _r: self._choose(title, options, chosen[0], picked))
            add(row, name)

        def switch(icon, title, active, apply, supporting="", name=""):
            add(SwitchRow(apply, icon=icon, headline=title, supporting=supporting, active=active), name or icon)

        def info(icon, title, *lines, on_release=None, name=""):
            row = LiteRow(icon=icon, headline=title, supporting=lines[0] if lines else "",
                          tertiary=lines[1] if len(lines) > 1 else "")
            if on_release:
                row.bind(on_release=lambda _r: on_release())
            add(row, name or icon)
            return row

        # Appearance
        section(t("settings.appearance"))
        themes = [(v, t("theme." + v)) for v in app_settings.THEMES]
        choice("theme-light-dark", t("settings.theme"), themes, s.theme, lambda v: self._change_look(theme=v), "theme")
        switch("palette-outline", t("settings.dynamic"), s.dynamic_color,
               lambda v: self._change_look(dynamic_color=v), t("settings.dynamic_hint"))
        switch("circle-half-full", t("settings.pure_black"), s.pure_black,
               lambda v: self._change_look(pure_black=v), t("settings.pure_black_hint"))
        accents = [(v, t("accent." + v)) for v in app_settings.ACCENTS]
        choice("format-color-fill", t("settings.accent"), accents, s.accent,
               lambda v: self._change_look(accent=v), "accent")
        languages = [(i18n.AUTO, i18n.tr("settings.language_auto"))] + [
            (code, i18n.LANGUAGES[code]) for code in FONT_LANGUAGES]
        choice("translate", t("settings.language"), languages, s.language, self._change_language, "language")

        # Downloads
        section(t("settings.downloads"))
        modes = [("video", t("home.video")), ("audio", t("home.audio"))]
        choice("tune-variant", t("settings.default_mode"), modes, s.default_mode,
               lambda v: self._change_default(default_mode=v), "default_mode")
        qualities = [(v, self._quality_label(v)) for v in worker.VIDEO_QUALITIES]
        choice("high-definition", t("settings.video_quality"), qualities, s.video_quality,
               lambda v: self._change_default(video_quality=v), "video_quality")
        containers = [(v, v.upper()) for v in app_settings.VIDEO_CONTAINERS]
        choice("filmstrip", t("settings.video_container"), containers, s.video_container,
               lambda v: self._change_default(video_container=v), "video_container")
        audio_formats = [(v, v.upper()) for v in app_settings.AUDIO_FORMATS]
        choice("music-box-outline", t("settings.audio_format"), audio_formats, s.audio_format,
               lambda v: self._change_default(audio_format=v), "audio_format")
        audio_q = [(v, self._quality_label(v)) for v in app_settings.AUDIO_QUALITIES]
        choice("equalizer-outline", t("settings.audio_quality"), audio_q, s.audio_quality,
               lambda v: self._change_default(audio_quality=v), "audio_quality")
        add(self._add_fragments_row(), "fragments")
        switch("subtitles-outline", t("settings.subtitles"), s.subtitles,
               lambda v: self._save_settings(subtitles=v), name="subtitles")
        info("translate-variant", self.tr("settings.sub_langs"),
             s.subtitle_langs or t("settings.sub_langs_auto"), on_release=self.edit_subtitle_langs, name="sub_langs")
        switch("subtitles", self.tr("settings.sub_embed"), s.subtitle_embed,
               lambda v: self._save_settings(subtitle_embed=v), name="sub_embed")
        switch("content-cut", t("settings.sponsorblock"), s.sponsorblock,
               lambda v: self._save_settings(sponsorblock=v), name="sponsorblock")
        info("format-list-checks", t("settings.sponsor_parts"), self._sponsor_text(),
             on_release=self.choose_sponsor_categories, name="sponsor_parts")
        info("folder-download-outline", t("settings.folder"), self.download_dir or "…", name="folder")

        # Connection
        section(t("settings.connection"))
        limits = [(n, f"{n} MB/s" if n else t("speed.unlimited")) for n in app_settings.SPEED_LIMITS]
        choice("speedometer", t("settings.speed_limit"), limits, s.speed_limit,
               lambda v: self._change_network(speed_limit=v), "speed_limit")
        info("server-network", t("settings.proxy"), s.proxy or t("settings.proxy_none"),
             on_release=self.edit_proxy, name="proxy")

        # Behaviour
        section(t("settings.behaviour"))
        switch("clipboard-arrow-down-outline", t("settings.auto_paste"), s.auto_paste,
               lambda v: self._save_settings(auto_paste=v), t("settings.auto_paste_hint"))
        switch("share-variant-outline", t("settings.auto_analyze"), s.auto_analyze_shared,
               lambda v: self._save_settings(auto_analyze_shared=v), t("settings.auto_analyze_hint"))
        switch("cellphone-screenshot", t("settings.keep_screen"), s.keep_screen_on,
               lambda v: self._save_settings(keep_screen_on=v), t("settings.keep_screen_hint"))
        switch("wifi", t("settings.wifi_only"), s.wifi_only,
               lambda v: self._save_settings(wifi_only=v), t("settings.wifi_only_hint"))
        switch("history", t("settings.history"), s.save_history, self._change_save_history)
        if android_env.on_android():
            info("battery-heart-variant", t("battery.title"), self._battery_text(),
                 on_release=self.ask_battery, name="battery")

        # YouTube
        section(t("youtube.section"))
        if youtube_login.saved(self.user_data_dir):
            info("account-check-outline", t("youtube.signed_in"), t("youtube.sign_out_hint"),
                 on_release=self.sign_out_youtube)
        else:
            info("account-outline", t("youtube.sign_in"), t("youtube.sign_in_hint"),
                 on_release=self.sign_in_youtube)

        # Reddit (NSFW posts need a signed-in account)
        section(t("reddit_login.section"))
        if youtube_login.saved(self.user_data_dir, youtube_login.REDDIT):
            info("account-check-outline", t("reddit_login.signed_in"), t("youtube.sign_out_hint"),
                 on_release=self.sign_out_reddit)
        else:
            info("account-outline", t("reddit_login.sign_in"), t("reddit_login.sign_in_hint"),
                 on_release=lambda *_: self.sign_in_reddit())

        # Instagram (most posts need a signed-in account)
        section("Instagram")
        if youtube_login.saved(self.user_data_dir, youtube_login.INSTAGRAM):
            info("account-check-outline", t("signin.signed_in", site="Instagram"), t("youtube.sign_out_hint"),
                 on_release=self.sign_out_instagram)
        else:
            info("account-outline", t("signin.sign_in", site="Instagram"), t("instagram.sign_in_hint"),
                 on_release=lambda *_: self.sign_in_instagram())

        # About
        section(t("settings.about"))
        info("information-outline", t("settings.version"), f"{APP_VERSION} · {t('settings.whats_new')}",
             on_release=self.show_release_notes, name="version")
        info("update", t("update.check"), on_release=self.check_for_updates, name="check_updates")
        switch("cellphone-arrow-down", t("update.auto"), s.check_updates,
               lambda v: self._save_settings(check_updates=v), t("update.auto_hint"), name="auto_update")
        channels = [("stable", self.tr("settings.channel_stable")), ("beta", self.tr("settings.channel_beta"))]
        choice("source-branch", self.tr("settings.update_channel"), channels, s.update_channel,
               lambda v: self._save_settings(update_channel=v, skipped_version=""), "update_channel")
        info("puzzle-outline", t("settings.components"), *self._components_text(), name="components")
        info("license", self.tr("about.licenses"), on_release=self.show_licenses, name="licenses")
        if android_env.on_android():
            info("bug-outline", t("settings.diagnostics"), t("settings.diagnostics_hint"),
                 on_release=self.copy_diagnostics, name="diagnostics")
        info("restore", t("settings.reset"), on_release=self.confirm_reset, name="reset")
        self.search_settings(self.ids.settings_search.text)

    def search_settings(self, text):
        """Show only the settings whose texts contain every word of ``text`` (B3-11)."""
        words = text.casefold().split()
        box = self.ids.settings_list
        box.clear_widgets()
        found = 0
        for heading, rows in self._settings_rows:
            texts = [(row, " ".join(str(getattr(row, k, "")) for k in ("headline", "supporting", "tertiary"))
                      + " " + heading.text) for row in rows]
            matching = [row for row, words_of in texts if all(w in words_of.casefold() for w in words)]
            if matching:
                box.add_widget(heading)
                for row in matching:
                    box.add_widget(row)
                found += len(matching)
        if not found:
            box.add_widget(MDLabel(text=self.tr("history.no_match"), halign="center", adaptive_height=True,
                                   padding=(dp(24), dp(48)), theme_text_color="Secondary"))

    # --- Updates ------------------------------------------------------------------

    def check_for_updates(self, quiet=False, url=self_update.RELEASES_URL):
        """Look for a newer release on GitHub in the background, then offer it.

        ``quiet`` (the check at start-up) says nothing unless one is found.
        """
        if self._update_checking:
            return
        self._update_checking = True
        if not quiet:
            self.snack(self.t("update.checking"))

        def work():
            try:
                found, error = self_update.check(APP_VERSION, url, channel=self.settings.update_channel,
                                                 skipped=self.settings.skipped_version if quiet else ""), None
            except self_update.UpdateError as e:
                found, error = None, str(e)
            ytdlp = None
            if YTDLP_DIR and url == self_update.RELEASES_URL:
                try:
                    ytdlp = ytdlp_updates.update(YTDLP_DIR, lambda page: self_update._open(page, 30))
                except Exception as e:  # the bundled yt-dlp still works
                    _log.info("yt-dlp update failed: %s", e)
            self.events.post("update_checked", update=found, quiet=quiet, error=error, ytdlp=ytdlp)

        threading.Thread(target=work, daemon=True).start()

    def _on_update_checked(self, update, quiet, error, ytdlp=None):
        self._update_checking = False
        if ytdlp:
            self.log(self.tr("update.ytdlp_ready", version=ytdlp))
            if update is None:
                self.snack(self.tr("update.ytdlp_ready", version=ytdlp))
                quiet = True  # that note is enough
        if self._selftest == "update":
            selftest(f"update found version={update.version if update else None} error={error}")
            if update:
                self.install_update(update)
            return
        if error:
            _log.warning(error)
            if not quiet:
                self.snack(self.t("update.failed"))
        elif update is None:
            if not quiet:
                self.snack(self.t("update.none"))
        else:
            self._offer_update(update)

    def _offer_update(self, update):
        text = self.t("update.body", current=APP_VERSION)
        notes = self_update.short_notes(update.notes)
        label = MDLabel(text=f"{text}\n\n{notes}" if notes else text, adaptive_height=True)
        scroll = MDScrollView(label, size_hint_y=None, height=min(dp(320), Window.height * 0.45),
                              do_scroll_x=False)
        self._dialog(self.t("update.title", version=update.version), content=scroll,
                     buttons=[(self.tr("update.skip"), lambda: self._save_settings(skipped_version=update.version)),
                              (self.t("update.later"), None),
                              (self.t("update.install"), lambda: self.install_update(update))])

    def install_update(self, update):
        """Download the update's APK, then hand it to Android to install."""
        if not android_env.on_android():
            self.snack(self.t("update.not_android"))
            return
        if self.job is not None:
            self.snack(self.t("update.busy"))
            return
        folder = os.path.join(android_env.cache_dir(), "updates")
        self._update_cancelled = False
        self._update_label = MDLabel(text=self.t("update.downloading", percent=0), adaptive_height=True)
        self._update_dialog = self._dialog(
            self.t("update.title", version=update.version), content=self._update_label,
            buttons=[(self.t("common.cancel"), lambda: setattr(self, "_update_cancelled", True))])

        def work():
            shown = [-1]

            def progress(done, total):
                percent = int(done * 100 / total) if total else 0
                if percent != shown[0]:
                    shown[0] = percent
                    self.events.post("update_progress", percent=percent)

            try:
                self_update.remove_old(folder)
                path, error = self_update.download(update, folder, progress, lambda: self._update_cancelled), None
            except self_update.Cancelled:
                path, error = None, None
            except self_update.UpdateError as e:
                path, error = None, str(e)
            self.events.post("update_downloaded", path=path, error=error)

        threading.Thread(target=work, daemon=True).start()

    def _on_update_progress(self, percent):
        if self._update_label is not None:
            self._update_label.text = self.t("update.downloading", percent=percent)

    def _on_update_downloaded(self, path, error):
        if self._update_dialog is not None and not self._update_cancelled:
            self._update_dialog.dismiss()
        self._update_dialog = self._update_label = None
        if self._selftest == "update":
            size = os.path.getsize(path) if path else 0
            selftest(f"update downloaded bytes={size} error={error}")
        if error:
            _log.warning(error)
            self._dialog(self.t("update.download_failed"), error)
            return
        if path is None:  # cancelled
            return
        try:
            from jnius import autoclass
            installer = autoclass("io.github.dordeorz.universaldownloader.UpdateInstaller")
            installer.install(android_env._activity(), path)
        except Exception as e:
            _log.warning("Cannot start the install: %s", e)
            self._dialog(self.t("update.install_failed"), str(e))
            return
        self.snack(self.t("update.confirm"))
        watch = {"seconds": 0.0, "last": ""}

        def poll(dt):
            status = installer.status() or ""
            watch["seconds"] += dt
            if status != watch["last"]:
                watch["last"] = status
                if self._selftest == "update":
                    selftest(f"update status={status}")
            if status.startswith("failed"):
                _log.warning("Update: %s", status)
                if not status.startswith("failed: 3"):  # 3: the user cancelled Android's screen
                    self._dialog(self.t("update.install_failed"), status[len("failed: "):])
                return False
            return status != "success" and watch["seconds"] < 600

        Clock.schedule_interval(poll, 0.5)

    def _add_fragments_row(self):
        row = BoxLayout(orientation="vertical", size_hint_y=None, padding=(dp(16), dp(10), dp(24), dp(4)))
        row.bind(minimum_height=row.setter("height"))
        title = LiteHeadline()
        hint = LiteWrappedText(font_size=sp(12))

        def show(count):
            title.text = f"{self.t('settings.fragments')}: {count}"
            hint.text = self.t("settings.fragments_hint", count=count)

        slider = MDSlider(MDSliderHandle(), min=app_settings.FRAGMENTS_MIN, max=app_settings.FRAGMENTS_MAX,
                          step=1, value=self.settings.fragments, size_hint_y=None, height=dp(40))
        slider.bind(value=lambda _s, v: show(int(v)))
        slider.bind(on_touch_up=lambda s, touch: self._save_settings(fragments=int(s.value))
                    if s.collide_point(*touch.pos) or touch.grab_current is s else None)
        show(self.settings.fragments)
        row.add_widget(title)
        row.add_widget(slider)
        row.add_widget(hint)
        row.headline = self.t("settings.fragments")  # for the search
        return row

    def _components_text(self):
        c = self.components
        if not c:
            return ("…",)
        yes, no = self.t("common.available"), self.t("common.missing")
        return (f"yt-dlp {c.get('yt-dlp')} · FFmpeg {c.get('ffmpeg') or no}",
                f"{self.t('home.tiktok')}: {yes if c.get('tiktok') else no} · "
                f"{self.t('home.trim')}: {yes if c.get('https') else no}")

    def _change_network(self, **changes):
        self._save_settings(**changes)
        self._set_platform_options()

    def edit_proxy(self):
        field = MDTextField(MDTextFieldHintText(text="host:port"),
                            MDTextFieldHelperText(text=self.t("settings.proxy_hint"), mode="persistent"),
                            text=self.settings.proxy, multiline=False)

        def save():
            try:
                proxy = urls.proxy_url(field.text)
            except ValueError:
                self.snack(self.t("settings.proxy_invalid"))
                return
            self._change_network(proxy=proxy)
            self._refresh("settings")

        box = MDBoxLayout(field, orientation="vertical", adaptive_height=True, padding=(0, dp(8)))
        self._dialog(self.t("settings.proxy"), content=box,
                     buttons=[(self.t("common.cancel"), None), (self.t("common.ok"), save)])

    def edit_subtitle_langs(self):
        """Subtitle languages (B4-6): codes such as "en, tr"; empty for the app's language, then English."""
        field = MDTextField(MDTextFieldHintText(text="en, tr"),
                            MDTextFieldHelperText(text=self.tr("settings.sub_langs_hint"), mode="persistent"),
                            text=self.settings.subtitle_langs, multiline=False)

        def save():
            langs = logic.subtitle_languages("", field.text) if field.text.strip() else []
            self._save_settings(subtitle_langs=", ".join(langs))
            self._refresh("settings")

        box = MDBoxLayout(field, orientation="vertical", adaptive_height=True, padding=(0, dp(8)))
        self._dialog(self.tr("settings.sub_langs"), content=box,
                     buttons=[(self.t("common.cancel"), None), (self.t("common.ok"), save)])

    def _sponsor_text(self):
        chosen = formats.sponsorblock_categories(self.settings.sponsorblock_categories)
        if len(chosen) == len(formats.SPONSORBLOCK_CATEGORIES):
            return self.t("settings.sponsor_all")
        return ", ".join(self.tr("sponsor." + c) for c in chosen) or self.t("settings.sponsor_none")

    def choose_sponsor_categories(self):
        """Which SponsorBlock parts are cut (B4-7)."""
        ticked = set(formats.sponsorblock_categories(self.settings.sponsorblock_categories))
        rows = BoxLayout(orientation="vertical", size_hint_y=None)
        rows.bind(minimum_height=rows.setter("height"))

        def draw(row, category):
            row.icon = "checkbox-marked" if category in ticked else "checkbox-blank-outline"
            row.accent = category in ticked

        def toggle(row, category):
            ticked.symmetric_difference_update({category})
            draw(row, category)

        for category in formats.SPONSORBLOCK_CATEGORIES:
            row = LiteRow(headline=self.tr("sponsor." + category))
            row.bind(on_release=lambda r, c=category: toggle(r, c))
            draw(row, category)
            rows.add_widget(row)
            self._named["choice." + category] = row

        def save():
            self._save_settings(sponsorblock_categories=",".join(c for c in formats.SPONSORBLOCK_CATEGORIES
                                                                   if c in ticked))
            self._refresh("settings")

        hint = self.tr("settings.sponsorblock_hint", option=self.t("settings.sponsorblock"))
        self._dialog(self.t("settings.sponsor_parts"), hint, content=rows,
                     buttons=[(self.t("common.cancel"), None), (self.t("common.done"), save)])

    def _battery_text(self):
        try:
            free = android_env.ignoring_battery_optimizations()
        except Exception as e:
            _log.warning("Battery optimisation: %s", e)
            return self.t("battery.hint")
        return self.t("battery.free") if free else self.t("battery.hint")

    def ask_battery(self):
        """Ask Android to let downloads run in the background without battery limits (B4-11)."""
        try:
            android_env.ask_ignore_battery_optimizations()
        except Exception as e:
            _log.warning("Battery optimisation: %s", e)
            self.snack(self.t("crash.error", error=e))
            return
        self._battery_asked = True  # the answer shows when the app is back (on_resume)

    def show_licenses(self):
        label = MDLabel(text=licenses.text(), adaptive_height=True, font_style="Body", role="small")
        scroll = MDScrollView(label, size_hint_y=None, height=min(dp(420), Window.height * 0.55),
                              do_scroll_x=False)
        self._dialog(self.tr("about.licenses"), content=scroll)

    def _change_save_history(self, value):
        self._save_settings(save_history=value)
        self._show_week()

    def _show_week(self):
        """FitWren-style tiles: files and size downloaded in the last 7 days."""
        shown = self.settings.save_history
        _show(self.ids.week_row, shown)
        if shown:
            files, size = self.history.recent(7)
            self.ids.week_files.text = str(files)
            self.ids.week_size.text = history.format_size(size)

    def _change_look(self, **changes):
        # The rows' colours follow the theme by themselves; nothing is rebuilt.
        self._save_settings(**changes)
        self._apply_theme()

    def _change_language(self, code):
        self._save_settings(language=code)
        self._apply_language()
        self._show_choices()
        Clock.schedule_once(self._redraw_field_texts, 0.2)
        self._refresh("settings", "history")
        if self.job is None:
            self.set_busy(False)
            self.ids.btn_download.disabled = not (self.analysis and self.chosen)

    def _redraw_field_texts(self, *_):
        """Text fields draw their hint and helper texts once; redraw after a language change."""
        for name in ("url", "trim_start", "trim_end"):
            field = self.ids[name]
            try:
                for label, canvas, group in ((field._hint_text_label, field.canvas.after, "hint-text-rectangle"),
                                             (field._helper_text_label, field.canvas.before,
                                              "helper-text-rectangle")):
                    if label:
                        label.texture_update()
                        for rect in canvas.get_group(group):
                            rect.texture = label.texture
                            rect.size = label.texture_size
            except Exception as e:  # private KivyMD details; a stale hint is only cosmetic
                _log.debug("Redraw %s: %s", name, e)

    def _change_default(self, **changes):
        self._save_settings(**changes)
        s = self.settings
        if self.job is None:
            self.mode = s.default_mode
            self.quality = {"video": s.video_quality, "audio": s.audio_quality}
            self.fmt = {"video": s.video_container, "audio": s.audio_format}
            self._show_mode()

    def confirm_reset(self):
        def reset():
            self.settings = AppSettings()
            self._save_settings()
            self._apply_language()
            self._apply_theme()
            self._change_default()
            self._refresh("settings", "history")
            self.snack(self.t("settings.reset_done"))

        self._dialog(self.t("settings.reset"), self.t("settings.reset_body"),
                     buttons=[(self.t("common.cancel"), None), (self.t("common.reset"), reset)])

    def show_release_notes(self):
        notes = release_notes(self.lang)
        label = MDLabel(text=notes, adaptive_height=True, markup=True)
        scroll = MDScrollView(label, size_hint_y=None, height=min(dp(420), Window.height * 0.55),
                              do_scroll_x=False)
        self._dialog(f"{APP_NAME} {APP_VERSION}", content=scroll)


def release_notes(lang):
    """The bundled release notes (whats_new.json), in ``lang`` or English."""
    import json
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whats_new.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    lines = []
    for release in data:
        items = release.get(lang) or release.get("en") or []
        lines.append(f"[b]{release.get('version', '')}[/b]  {release.get('date', '')}")
        lines.extend(f"•  {item}" for item in items)
        lines.append("")
    return "\n".join(lines).strip()


if __name__ == "__main__":
    UniversalDownloaderApp().run()
