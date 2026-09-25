"""UniversalDownloader for Android.

A Material You app (KivyMD 2) on top of the shared download code, with
three tabs: Download (link, Video/Audio, quality, trim, progress), History
and Settings (appearance, download defaults, behaviour, About).

Worker threads never touch widgets. They post to an ``events.EventQueue``
that ``Clock`` drains on the main thread, as the Windows app does with Tk's
``after()``.
"""

import logging
import os
import sys
import threading
import time
from collections import deque

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.widget import Widget
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.dialog import (MDDialog, MDDialogButtonContainer, MDDialogContentContainer,
                               MDDialogHeadlineText, MDDialogSupportingText)
from kivymd.uix.label import MDLabel
from kivymd.uix.list import (MDListItem, MDListItemHeadlineText, MDListItemLeadingIcon,
                             MDListItemSupportingText, MDListItemTertiaryText, MDListItemTrailingIcon)
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.navigationbar import MDNavigationItem
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.slider import MDSlider, MDSliderHandle
from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText

import android_env
import app_settings
import events
import filenames
import history
import i18n
import layout
import logic
import media_tools
import texts
import urls
import version
import worker
from app_settings import AppSettings
from results import ItemStatus

APP_VERSION = "0.2.0"  # keep in step with android/buildozer.spec
# KivyMD's Roboto fonts cover Latin, Greek and Cyrillic; languages in other
# scripts fall back to English.
FONT_LANGUAGES = [code for code in i18n.LANGUAGES if code not in {"ja", "ko", "zh"}]
LOG_LINES = 150
SELFTEST_TAG = "UDSELFTEST"
MODES = {"video": worker.VIDEO_AUDIO, "audio": worker.AUDIO_ONLY}
MIME = {"mp4": "video/mp4", "mkv": "video/x-matroska", "webm": "video/webm", "mp3": "audio/mpeg",
        "m4a": "audio/mp4", "flac": "audio/flac", "wav": "audio/wav", "opus": "audio/ogg"}

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
_log = logging.getLogger("universaldownloader")


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


class NavItem(MDNavigationItem):
    name = StringProperty()
    icon = StringProperty()
    text = StringProperty()


class Root(MDBoxLayout):
    pass


class SwitchRow(MDBoxLayout):
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
<SwitchRow>:
    adaptive_height: True
    padding: dp(16), dp(10), dp(24), dp(10)
    spacing: dp(16)
    MDIcon:
        icon: root.icon
        pos_hint: {"center_y": .5}
        theme_text_color: "Custom"
        text_color: app.theme_cls.onSurfaceVariantColor
    MDBoxLayout:
        orientation: "vertical"
        adaptive_height: True
        pos_hint: {"center_y": .5}
        MDLabel:
            text: root.headline
            adaptive_height: True
        MDLabel:
            text: root.supporting
            font_style: "Body"
            role: "small"
            adaptive_height: True
            theme_text_color: "Custom"
            text_color: app.theme_cls.onSurfaceVariantColor
            opacity: 1 if root.supporting else 0
            height: self.texture_size[1] if root.supporting else 0
    MDSwitch:
        pos_hint: {"center_y": .5}
        active: root.active
        on_active: root.on_switch(self.active)
""")


class UniversalDownloaderApp(MDApp):
    title = "UniversalDownloader"
    lang = StringProperty(i18n.FALLBACK)  # kv texts re-read when it changes

    # --- Texts --------------------------------------------------------------------

    def t(self, key, *_lang, **values):
        return texts.t(key, **values)

    def tr(self, key, *_lang, **values):
        return i18n.tr(key, **values)

    # --- Build --------------------------------------------------------------------

    def build(self):
        Window.softinput_mode = "below_target"
        self.settings_path = os.path.join(self.user_data_dir, "settings.json")
        self.settings = app_settings.load(self.settings_path)
        self.history = history.History(os.path.join(self.user_data_dir, "history.json"))
        self.events = events.EventQueue()
        self.manager = None
        self.session = None
        self.analysis = None
        self.analysis_url = None
        self.download_dir = None
        self.job = None  # "analyze" or "download" while one runs
        self.mode = self.settings.default_mode
        self.quality = {"video": self.settings.video_quality, "audio": self.settings.audio_quality}
        self.fmt = {"video": self.settings.video_container, "audio": self.settings.audio_format}
        self.components = {}
        self.pending_link = None
        self.tools_ready = False
        self._selftest = None
        self._selftest_passes = []
        self._log_lines = []
        self._menu = None
        self._wake_lock = None
        self._stderr = deque(maxlen=12)  # last lines FFmpeg printed, shown when an item fails
        self._apply_language()
        self._apply_theme()
        Builder.load_string(layout.KV)
        self.root_view = Root()
        self.ids = self.root_view.ids
        self._wire_handlers()
        Clock.schedule_interval(lambda *_: self.events.dispatch_pending(), 0.1)
        return self.root_view

    def _wire_handlers(self):
        self.events.register(events.LOG, self.log)
        self.events.register(events.TOOLS_CHECKED, self._on_tools_checked)
        self.events.register(events.ANALYSIS_DONE, self._on_analysis_done)
        self.events.register(events.ANALYSIS_FAILED, self._on_analysis_failed)
        self.events.register(events.ITEM_STARTED, self._on_item_started)
        self.events.register(events.PROGRESS, self._on_progress)
        self.events.register(events.STAGE, self._on_stage)
        self.events.register(events.ITEM_DONE, self._on_item_done)
        self.events.register(events.JOB_DONE, self._on_job_done)
        self.events.register("shared_link", self._on_shared_text)

    def on_start(self):
        self._show_mode()
        _show(self.ids.media_card, False)
        _show(self.ids.progress_card, False)
        _show(self.ids.trim_box, False)
        _show(self.ids.log, False)
        self.set_busy(False)
        self.ids.btn_download.disabled = True
        self.ids.btn_analyze.disabled = True
        self.build_settings()
        self.build_history()
        if android_env.on_android():
            os.environ["TMPDIR"] = android_env.cache_dir()
            self._wake_lock = android_env.WakeLock()
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

    def _fit_system_bars(self, *_):
        try:
            top, bottom = android_env.system_bar_insets(Window.height)
        except Exception as e:
            _log.warning("System bar insets: %s", e)
            return
        self.root_view.padding = [0, top, 0, bottom]

    def on_resume(self):
        if self.settings.theme == "system" or self.settings.dynamic_color:
            self._apply_theme()

    def on_pause(self):
        # Keep running when the user switches apps; the wake lock keeps
        # downloads going while Android lets the process live.
        return True

    def on_stop(self):
        if self.session is not None and self.session.busy:
            self.session.cancel()
            self.session.wait(5)
        self._keep_awake(False)

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

    def _apply_theme(self):
        s = self.settings
        dark = s.theme == "dark"
        if s.theme == "system" and android_env.on_android():
            try:
                dark = android_env.night_mode()
            except Exception:
                dark = False
        self.theme_cls.theme_style_switch_animation = False
        self.theme_cls.primary_palette = s.accent
        self.theme_cls.dynamic_color = s.dynamic_color and android_env.on_android()
        self.theme_cls.theme_style = "Dark" if dark else "Light"
        self.theme_cls.set_colors()

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
                candidates = [os.path.join(os.path.expanduser("~"), "Downloads", "UniversalDownloader")]
            logic.set_platform_options({**js, **app_settings.download_speed_options(self.settings)})
            self._js_options = js
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
        self.manager = logic.DownloadManager(tools=status)
        self.session = worker.Session(self.manager, self.events, tr=i18n.tr)
        if not status.ok:
            self.snack(self.tr("top.ffmpeg_missing"))
        self.ids.btn_analyze.disabled = False
        self.ids.btn_download.disabled = not (self.analysis and self.analysis.items)
        self.build_settings()
        if self._selftest:
            self.ids.url.text = self._selftest
            self._selftest_passes = [("video", None), ("audio", None), ("video", ("0:01", "0:03"))]
            self.analyze()
        elif self.pending_link:
            self._use_link(self.pending_link, shared=True)

    def _selftest_url(self):
        """The ``selftest_url`` extra of the launching intent (CI only)."""
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            return activity.getIntent().getStringExtra("selftest_url")
        except Exception:
            return None

    # --- Navigation, messages -----------------------------------------------------

    def switch_tab(self, name):
        screens = self.ids.screens
        order = ["home", "history", "settings"]
        screens.transition.direction = "left" if order.index(name) > order.index(screens.current) else "right"
        screens.current = name
        if name == "history":
            self.build_history()

    def go_to(self, name):
        """Switch tabs from code, keeping the navigation bar in step."""
        for item in self.ids.nav.children:
            if isinstance(item, NavItem) and item.name == name and not item.active:
                self.ids.nav.set_active_item(item)
        if self.ids.screens.current != name:
            self.switch_tab(name)

    def snack(self, text):
        MDSnackbar(MDSnackbarText(text=text), y=dp(96), pos_hint={"center_x": 0.5}, size_hint_x=0.92).open()

    def log(self, message):
        self._log_lines.append(message)
        del self._log_lines[:-LOG_LINES]
        self.ids.log.text = "\n".join(self._log_lines)

    def toggle_details(self):
        visible = self.ids.log.parent is None
        _show(self.ids.log, visible)
        self.ids.details_icon.icon = "chevron-up" if visible else "chevron-down"
        self.ids.details_text.text = self.t("home.hide_details" if visible else "home.details")

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

    def _choose(self, caller, options, current, on_pick):
        """Drop-down menu of ``options`` [(value, label)] next to ``caller``."""
        if self._menu:
            self._menu.dismiss()

        def pick(value):
            self._menu.dismiss()
            on_pick(value)

        items = [{"text": label, "trailing_icon": "check" if value == current else "",
                  "on_release": lambda v=value: pick(v)} for value, label in options]
        self._menu = MDDropdownMenu(caller=caller, items=items, position="bottom")
        self._menu.open()

    # --- Link ---------------------------------------------------------------------

    def paste(self, quiet=False):
        try:
            text = android_env.clipboard_text().strip()
        except Exception:
            text = ""
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
            self._show_media(self.tr("link.changed"), "", "link-variant-off")

    def analyze(self):
        if self.session is None or self.job is not None:
            return
        try:
            started = self.session.analyze(self.ids.url.text)
        except urls.UrlError as e:
            self._show_media(self.tr(e.key, **e.values), "", "alert-circle-outline")
            return
        if started:
            self.job = "analyze"
            self.analysis = None
            self.set_busy(True)
            self.ids.btn_download.disabled = True
            self._show_media(self.tr("link.reading"), "", "timer-sand")
            self.log(self.tr("log.fetching"))

    def _show_media(self, title, subtitle, icon):
        _show(self.ids.media_card, True)
        self.ids.media_title.text = title
        self.ids.media_sub.text = subtitle
        self.ids.media_icon.icon = icon

    # --- Choices ------------------------------------------------------------------

    def set_mode(self, mode):
        if self.job is None:
            self.mode = mode
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

    def choose_quality(self, caller):
        values = worker.VIDEO_QUALITIES if self.mode == "video" else worker.AUDIO_QUALITIES
        self._choose(caller, [(v, self._quality_label(v)) for v in values], self.quality[self.mode],
                     lambda v: (self.quality.__setitem__(self.mode, v), self._show_choices()))

    def choose_format(self, caller):
        values = worker.MODE_FORMATS[MODES[self.mode]]
        self._choose(caller, [(v, v.upper()) for v in values], self.fmt[self.mode],
                     lambda v: (self.fmt.__setitem__(self.mode, v), self._show_choices()))

    def trim_toggled(self, active):
        _show(self.ids.trim_box, active)
        if active and self.components and not self.components.get("https", True):
            self.log("FFmpeg has no HTTPS; trimming may fail")

    # --- Download -----------------------------------------------------------------

    def set_busy(self, busy):
        for name in ("btn_analyze", "btn_clear", "btn_video", "btn_audio", "btn_quality", "btn_format",
                     "trim_switch", "trim_start", "trim_end"):
            self.ids[name].disabled = busy
        self.ids.url.disabled = busy
        self.ids.download_icon.icon = "close" if busy else "download"
        self.ids.download_text.text = self.tr("action.cancel" if busy and self.job == "download"
                                              else "action.download")
        self.ids.btn_download.style = "tonal" if busy else "filled"
        self.ids.btn_download.disabled = busy and self.job != "download"

    def download(self):
        if self.job == "download":
            self.session.cancel()
            self.ids.download_text.text = self.tr("action.cancelling")
            self.ids.btn_download.disabled = True
            return
        if self.job is not None or not self.analysis or not self.analysis.items:
            return
        if not self.download_dir:
            self.snack(self.tr("folder.error_title"))
            return
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
        logic.set_platform_options({**getattr(self, "_js_options", {}),
                                    **app_settings.download_speed_options(self.settings)})
        if self.session.download(self.analysis, options):
            self.job = "download"
            self.set_busy(True)
            self._keep_awake(True)
            _show(self.ids.progress_card, True)
            self.ids.progress.value = 0
            self.ids.progress_title.text = self.tr("progress.starting")
            self.ids.progress_detail.text = ""
            self.log(self.tr("log.folder", folder=self.download_dir))

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

    def _on_analysis_done(self, analysis, url):
        self.job = None
        self.analysis = analysis
        self.analysis_url = self.ids.url.text.strip()
        self.set_busy(False)
        if analysis.is_playlist:
            sub = self.tr("media.videos", count=len(analysis.items))
            if analysis.skipped:
                sub += ", " + self.tr("media.unavailable", count=len(analysis.skipped))
            self._show_media(analysis.title, f"{self.tr('media.playlist')} · {sub}", "playlist-play")
            self.log(self.tr("log.playlist", title=analysis.title, count=len(analysis.items),
                             skipped=len(analysis.skipped)))
        elif analysis.items:
            self._show_media(analysis.title, self.tr("media.video"), "movie-open-outline")
            self.log(self.tr("log.video", title=analysis.title))
        else:
            reason = analysis.skipped[0].skip_reason if analysis.skipped else None
            text = (self.tr("link.nothing_reason", reason=i18n.tr_message(reason)) if reason
                    else self.tr("link.nothing"))
            self._show_media(text, "", "alert-circle-outline")
        self.ids.btn_download.disabled = not analysis.items
        selftest(f"analysis items={len(analysis.items)} title={analysis.title!r}")
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

    def _on_analysis_failed(self, message):
        self.job = None
        self.set_busy(False)
        self.ids.btn_download.disabled = True
        self._show_media(self.tr("link.nothing_reason", reason=message), "", "alert-circle-outline")
        self.log(message)
        selftest(f"analysis failed: {message}")

    def _on_item_started(self, position, total, title):
        self._stderr.clear()
        self.ids.progress.value = 0
        self.ids.progress_title.text = title if total == 1 else self.tr(
            "progress.item", position=position, total=total, title=title)
        self.ids.progress_detail.text = ""

    def _on_progress(self, fraction, text, detail):
        self.ids.progress.value = fraction * 100
        self.ids.progress_detail.text = f"{text}  {detail}".strip()

    def _on_stage(self, text):
        self.ids.progress_detail.text = i18n.tr_message(text)

    def _on_item_done(self, result):
        if result.status is ItemStatus.COMPLETED:
            self.log(self.tr("log.saved", path=result.path))
            if self.settings.save_history and result.path:
                self.history.add(result.title, result.path, url=result.url,
                                 kind="audio" if self.mode == "audio" else "video")
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
        selftest(f"item {result.status.value} path={result.path} error={result.error}")

    def _on_native_stderr(self, line):
        """Worker thread: a line a program (usually FFmpeg) wrote to stderr."""
        self._stderr.append(line)
        _log.info("stderr: %s", line)

    def _on_job_done(self, summary):
        self.job = None
        self.set_busy(False)
        self._keep_awake(False)
        headline = summary.headline(label=lambda status: self.tr("status." + status.value),
                                    nothing=self.tr("summary.nothing"))
        self.log(self.tr("log.result", summary=headline))
        self.ids.progress_title.text = self.tr(summary.title_key())
        self.ids.progress_detail.text = headline
        if summary.all_ok:
            self.ids.progress.value = 100
            self.ids.progress_detail.text = self.t("home.saved", folder=self.download_dir)
        selftest(f"job done all_ok={summary.all_ok}")
        if self._selftest:
            self._next_selftest_pass()

    # --- History ------------------------------------------------------------------

    def build_history(self):
        box = self.ids.history_list
        box.clear_widgets()
        entries = self.history.entries
        if not entries:
            box.add_widget(MDLabel(text=self.t("history.empty"), halign="center", adaptive_height=True,
                                   padding=(dp(24), dp(48)), theme_text_color="Secondary"))
            return
        for entry in entries:
            exists = os.path.exists(entry.path)
            when = time.strftime("%d.%m.%Y %H:%M", time.localtime(entry.time)) if entry.time else ""
            ext = os.path.splitext(entry.path)[1].lstrip(".").upper()
            sub = " · ".join(part for part in (ext, when) if part)
            if not exists:
                sub += f" · {self.t('history.missing')}"
            item = MDListItem(
                MDListItemLeadingIcon(icon="music-note" if entry.kind == "audio" else "movie-outline"),
                MDListItemHeadlineText(text=entry.title or os.path.basename(entry.path)),
                MDListItemSupportingText(text=sub),
                MDListItemTrailingIcon(icon="dots-vertical"),
                on_release=lambda _i, e=entry: self._history_menu(_i, e),
            )
            box.add_widget(item)

    def _history_menu(self, caller, entry):
        options = [("open", self.t("home.open")), ("share", self.t("history.share")),
                   ("remove", self.t("history.delete"))]

        def picked(action):
            if action == "remove":
                self.history.remove(entry.path)
                self.build_history()
            else:
                self.open_file(entry.path, share=action == "share")

        self._choose(caller, options, None, picked)

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
            self.history.clear()
            self.build_history()

        self._dialog(self.t("history.clear"), self.t("history.clear_body"),
                     buttons=[(self.t("common.cancel"), None), (self.t("common.remove"), clear)])

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
        box = self.ids.settings_list
        box.clear_widgets()
        s = self.settings
        t = self.t

        def section(title):
            box.add_widget(MDLabel(text=title, font_style="Title", role="small", adaptive_height=True,
                                   theme_text_color="Custom", text_color=self.theme_cls.primaryColor,
                                   padding=(dp(16), dp(20), dp(16), dp(4))))

        def choice(icon, title, value_label, options, current, apply, supporting=None):
            item = MDListItem(MDListItemLeadingIcon(icon=icon), MDListItemHeadlineText(text=title),
                              MDListItemSupportingText(text=supporting or value_label))
            if supporting:
                item.add_widget(MDListItemSupportingText(text=value_label))
            item.bind(on_release=lambda i: self._choose(i, options, current, apply))
            box.add_widget(item)

        def switch(icon, title, active, apply, supporting=""):
            box.add_widget(SwitchRow(apply, icon=icon, headline=title, supporting=supporting, active=active))

        def info(icon, title, *lines, on_release=None):
            item = MDListItem(MDListItemLeadingIcon(icon=icon), MDListItemHeadlineText(text=title))
            for line, cls in zip(lines, (MDListItemSupportingText, MDListItemTertiaryText)):
                item.add_widget(cls(text=line))
            if on_release:
                item.bind(on_release=lambda _i: on_release())
            box.add_widget(item)

        # Appearance
        section(t("settings.appearance"))
        themes = [(v, t("theme." + v)) for v in app_settings.THEMES]
        choice("theme-light-dark", t("settings.theme"), t("theme." + s.theme), themes, s.theme,
               lambda v: self._change_look(theme=v))
        switch("palette-outline", t("settings.dynamic"), s.dynamic_color,
               lambda v: self._change_look(dynamic_color=v), t("settings.dynamic_hint"))
        accents = [(v, t("accent." + v)) for v in app_settings.ACCENTS]
        choice("format-color-fill", t("settings.accent"), t("accent." + s.accent), accents, s.accent,
               lambda v: self._change_look(accent=v))
        languages = [(i18n.AUTO, i18n.tr("settings.language_auto"))] + [
            (code, i18n.LANGUAGES[code]) for code in FONT_LANGUAGES]
        current = dict(languages).get(s.language, s.language)
        choice("translate", t("settings.language"), current, languages, s.language, self._change_language)

        # Downloads
        section(t("settings.downloads"))
        modes = [("video", t("home.video")), ("audio", t("home.audio"))]
        choice("tune-variant", t("settings.default_mode"), dict(modes)[s.default_mode], modes, s.default_mode,
               lambda v: self._change_default(default_mode=v))
        qualities = [(v, self._quality_label(v)) for v in worker.VIDEO_QUALITIES]
        choice("high-definition", t("settings.video_quality"), self._quality_label(s.video_quality), qualities,
               s.video_quality, lambda v: self._change_default(video_quality=v))
        containers = [(v, v.upper()) for v in app_settings.VIDEO_CONTAINERS]
        choice("filmstrip", t("settings.video_container"), s.video_container.upper(), containers,
               s.video_container, lambda v: self._change_default(video_container=v))
        audio_formats = [(v, v.upper()) for v in app_settings.AUDIO_FORMATS]
        choice("music-box-outline", t("settings.audio_format"), s.audio_format.upper(), audio_formats,
               s.audio_format, lambda v: self._change_default(audio_format=v))
        audio_q = [(v, self._quality_label(v)) for v in app_settings.AUDIO_QUALITIES]
        choice("equalizer-outline", t("settings.audio_quality"), self._quality_label(s.audio_quality), audio_q,
               s.audio_quality, lambda v: self._change_default(audio_quality=v))
        self._add_fragments_row(box)
        info("folder-download-outline", t("settings.folder"), self.download_dir or "…")

        # Behaviour
        section(t("settings.behaviour"))
        switch("clipboard-arrow-down-outline", t("settings.auto_paste"), s.auto_paste,
               lambda v: self._save_settings(auto_paste=v), t("settings.auto_paste_hint"))
        switch("share-variant-outline", t("settings.auto_analyze"), s.auto_analyze_shared,
               lambda v: self._save_settings(auto_analyze_shared=v), t("settings.auto_analyze_hint"))
        switch("cellphone-screenshot", t("settings.keep_screen"), s.keep_screen_on,
               lambda v: self._save_settings(keep_screen_on=v), t("settings.keep_screen_hint"))
        switch("history", t("settings.history"), s.save_history, lambda v: self._save_settings(save_history=v))

        # About
        section(t("settings.about"))
        info("information-outline", t("settings.version"), f"{APP_VERSION} · {t('settings.whats_new')}",
             on_release=self.show_release_notes)
        info("puzzle-outline", t("settings.components"), *self._components_text())
        info("restore", t("settings.reset"), on_release=self.confirm_reset)

    def _add_fragments_row(self, box):
        row = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(dp(16), dp(10), dp(24), dp(4)))
        title = MDLabel(adaptive_height=True)
        hint = MDLabel(font_style="Body", role="small", adaptive_height=True,
                       theme_text_color="Custom", text_color=self.theme_cls.onSurfaceVariantColor)

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
        box.add_widget(row)

    def _components_text(self):
        c = self.components
        if not c:
            return ("…",)
        yes, no = self.t("common.available"), self.t("common.missing")
        return (f"yt-dlp {c.get('yt-dlp')} · FFmpeg {c.get('ffmpeg') or no}",
                f"{self.t('home.tiktok')}: {yes if c.get('tiktok') else no} · "
                f"{self.t('home.trim')}: {yes if c.get('https') else no}")

    def _change_look(self, **changes):
        self._save_settings(**changes)
        self._apply_theme()
        Clock.schedule_once(lambda *_: self.build_settings(), 0.1)

    def _change_language(self, code):
        self._save_settings(language=code)
        self._apply_language()
        self._show_choices()
        Clock.schedule_once(self._redraw_field_texts, 0.2)
        self.build_settings()
        self.build_history()
        if self.job is None:
            self.set_busy(False)
            self.ids.btn_download.disabled = not (self.analysis and self.analysis.items)

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
        self.build_settings()

    def confirm_reset(self):
        def reset():
            self.settings = AppSettings()
            self._save_settings()
            self._apply_language()
            self._apply_theme()
            self._change_default()
            self.snack(self.t("settings.reset_done"))

        self._dialog(self.t("settings.reset"), self.t("settings.reset_body"),
                     buttons=[(self.t("common.cancel"), None), (self.t("common.reset"), reset)])

    def show_release_notes(self):
        notes = release_notes(self.lang)
        label = MDLabel(text=notes, adaptive_height=True, markup=True)
        scroll = MDScrollView(label, size_hint_y=None, height=min(dp(420), Window.height * 0.55),
                              do_scroll_x=False)
        self._dialog(f"UniversalDownloader {APP_VERSION}", content=scroll)


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
