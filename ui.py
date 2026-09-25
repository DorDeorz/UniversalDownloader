import logging
import os
import subprocess
import sys
import threading
import tkinter
from tkinter import filedialog, messagebox

import customtkinter as ctk

import app_setup
import events
import filenames
import formats
import media_tools
import playlist
import settings as settings_store
import urls
from logic import DownloadManager, TrimError, parse_trim_range
from results import ItemResult, ItemStatus, JobSummary
from utils import default_download_dir, resource_path
from version import DISPLAY_NAME, __version__

_log = logging.getLogger(__name__)

ctk.set_default_color_theme("blue")

# Design tokens: (light, dark) pairs, the CustomTkinter convention.
ACCENT = ("#5b5bd6", "#6e6af0")
ACCENT_HOVER = ("#4848c2", "#5a55e0")
ACCENT_DISABLED = ("#b4b4ea", "#3a3970")
ON_ACCENT = "#ffffff"
ON_ACCENT_DISABLED = ("#f1f1fc", "#8e8cc0")
BG = ("#f3f4f8", "#12131c")
SIDEBAR = ("#e8e9f2", "#191a26")
CARD = ("#ffffff", "#1e2030")
CARD_BORDER = ("#e1e3ec", "#2a2d42")
FIELD = ("#f5f6fa", "#262939")
MUTED = ("#6b6f80", "#9aa0b4")
TEXT = ("#1b1d29", "#eceef6")
SECONDARY = ("#e4e5ef", "#2c2f44")
SECONDARY_HOVER = ("#d6d8e6", "#363a52")
DANGER = ("#d64545", "#ef5b5b")
SUCCESS = ("#23875a", "#3dd68c")
WARNING = ("#b7791f", "#f0b429")


def font(size=13, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=CARD_BORDER, **kw)


def primary_button(parent, text, command, **kw):
    kw.setdefault("height", 36)
    kw.setdefault("font", font(13, "bold"))
    kw.setdefault("corner_radius", 8)
    return ctk.CTkButton(parent, text=text, command=command, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                         text_color=ON_ACCENT, text_color_disabled=ON_ACCENT_DISABLED, **kw)


def set_primary_state(button, state, **kw):
    """Enable or disable a primary button; a disabled one gets a muted fill."""
    button.configure(state=state, fg_color=ACCENT if state == "normal" else ACCENT_DISABLED, **kw)


def secondary_button(parent, text, command, **kw):
    kw.setdefault("height", 36)
    return ctk.CTkButton(parent, text=text, command=command, fg_color=SECONDARY, hover_color=SECONDARY_HOVER,
                         text_color=TEXT, corner_radius=8, font=font(13), **kw)


class PlaylistSelector(ctk.CTkToplevel):
    """Modal list of playlist entries to pick from.

    Calls ``callback(items)`` with the chosen queue items on confirm, or
    ``callback(None)`` when the dialog is cancelled or closed.
    """

    BATCH = 50  # checkboxes created per idle step, so big playlists stay responsive

    def __init__(self, parent, analysis, callback):
        super().__init__(parent, fg_color=BG)
        self.title("Select Videos")
        self.geometry("640x540")
        self.minsize(420, 360)
        # Modal: stays above the main window and blocks it until closed.
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.callback = callback
        self.items = list(analysis.items)
        self.vars = []
        self._done = False

        heading = f"{analysis.title}: {len(self.items)} downloadable"
        if analysis.skipped:
            heading += f", {len(analysis.skipped)} skipped"
        self.lbl_title = ctk.CTkLabel(self, text=heading, font=font(16, "bold"), text_color=TEXT,
                                      wraplength=600, anchor="w", justify="left")
        self.lbl_title.pack(fill="x", pady=(18, 2), padx=20)
        if analysis.skipped:
            reasons = {}
            for item in analysis.skipped:
                reasons[item.skip_reason] = reasons.get(item.skip_reason, 0) + 1
            detail = "Skipped: " + ", ".join(f"{n} {reason}" for reason, n in reasons.items())
            ctk.CTkLabel(self, text=detail, font=font(12), text_color=MUTED, wraplength=600, anchor="w",
                         justify="left").pack(fill="x", padx=20)

        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(fill="x", padx=20, pady=(12, 0))
        self.btn_all = secondary_button(self.btn_frame, "Select all", self.select_all, width=100, height=32)
        self.btn_all.pack(side="left")
        self.btn_none = secondary_button(self.btn_frame, "Select none", self.select_none, width=100, height=32)
        self.btn_none.pack(side="left", padx=(8, 0))
        self.lbl_count = ctk.CTkLabel(self.btn_frame, text="", font=font(12, "bold"), text_color=MUTED)
        self.lbl_count.pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=12, border_width=1,
                                             border_color=CARD_BORDER)
        self.scroll.pack(pady=12, padx=20, fill="both", expand=True)

        self.bottom = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom.pack(fill="x", padx=20, pady=(0, 18))
        self.btn_cancel = secondary_button(self.bottom, "Cancel", self.cancel, width=110, height=40)
        self.btn_cancel.pack(side="right", padx=(8, 0))
        self.btn_confirm = primary_button(self.bottom, "Add to queue", self.confirm_selection, height=40)
        self.btn_confirm.pack(side="right", fill="x", expand=True)

        self._add_rows(0)
        self.after(100, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass  # window not viewable yet or already closed

    def _add_rows(self, start):
        for item in self.items[start:start + self.BATCH]:
            var = ctk.IntVar(value=1)
            label = f"{item.index:>3}. {item.title}" if item.index else item.title
            ctk.CTkCheckBox(self.scroll, text=label, variable=var, command=self._update_count, font=font(13),
                            text_color=TEXT, fg_color=ACCENT, hover_color=ACCENT_HOVER, checkbox_width=20,
                            checkbox_height=20, corner_radius=5).pack(anchor="w", pady=4, padx=8)
            self.vars.append(var)
        self._update_count()
        if start + self.BATCH < len(self.items):
            self.after(1, self._add_rows, start + self.BATCH)

    def selected_items(self):
        return [item for item, var in zip(self.items, self.vars) if var.get() == 1]

    def _update_count(self):
        count = len(self.selected_items())
        self.lbl_count.configure(text=f"{count} selected")
        # An empty selection cannot be confirmed (ISSUES.md #24).
        set_primary_state(self.btn_confirm, "normal" if count else "disabled",
                          text=f"Add {count} to queue" if count else "Nothing selected")

    def select_all(self):
        for var in self.vars: var.set(1)
        self._update_count()
    def select_none(self):
        for var in self.vars: var.set(0)
        self._update_count()

    def confirm_selection(self):
        selected = self.selected_items()
        if not selected:
            return
        self._finish(selected)

    def cancel(self):
        self._finish(None)

    def _finish(self, result):
        if self._done:
            return
        self._done = True
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        self.callback(result)

class App(ctk.CTk):
    MIN_SIZE = (900, 680)

    def __init__(self):
        super().__init__()
        self.title(f"{DISPLAY_NAME} {__version__}")
        self.geometry("1040x760")
        # Resizable with a sensible minimum (ISSUES.md #44).
        self.minsize(*self.MIN_SIZE)
        self.configure(fg_color=BG)

        self.icon_path = resource_path("app.ico")
        self.set_icon()
        # CustomTkinter sets its own icon shortly after start; set ours again.
        self.after(200, self.set_icon)

        self.settings_path = os.path.join(app_setup.data_dir(), "settings.json")
        self.settings = settings_store.load(self.settings_path, default_download_dir())
        ctk.set_appearance_mode(self.settings.theme)

        self.manager = DownloadManager()
        self.download_folder = self.settings.download_folder
        self.download_queue = []
        self.analyzed_url = None
        # Only one job (analysis or download) runs at a time; see _start_job.
        self._job_thread = None
        self._job_kind = None
        self._cancel_event = threading.Event()
        self._closing = False
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Worker threads never touch widgets; they post events that are
        # dispatched here on the main thread (see events.py).
        self.events = events.EventQueue()
        self.events.register(events.LOG, self._append_log)
        self.events.register(events.PROGRESS, self._show_progress)
        self.events.register(events.STAGE, self._show_stage)
        self.events.register(events.ITEM_STARTED, self._on_item_started)
        self.events.register(events.ANALYSIS_DONE, self._on_analysis_done)
        self.events.register(events.ANALYSIS_FAILED, self._on_analysis_failed)
        self.events.register(events.ITEM_DONE, self._on_item_done)
        self.events.register(events.JOB_DONE, self._on_job_done)
        self.events.register(events.TOOLS_CHECKED, self._on_tools_checked)
        self.last_summary = None
        self.playlist_dialog = None
        self._pending_skipped = []
        self.skipped_items = []
        self._poll_id = None
        self.tools = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.create_sidebar()
        self.create_main_view()
        self._apply_mode(self.settings.mode, self.settings.format, self.settings.quality)
        self._poll_events()
        # Check FFmpeg off the main thread; downloads stay disabled until then.
        self._start_job("setup", self.run_tool_check)

    POLL_INTERVAL_MS = 50

    def _poll_events(self):
        """Drain the event queue on the main thread, then reschedule."""
        try:
            self.events.dispatch_pending()
        finally:
            self._poll_id = self.after(self.POLL_INTERVAL_MS, self._poll_events)

    def destroy(self):
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        super().destroy()

    def set_icon(self):
        """Window icon: the .ico on Windows, the PNG elsewhere (Tk reads PNG natively)."""
        try:
            if sys.platform == "win32":
                self.iconbitmap(self.icon_path)
            else:
                self._icon_image = tkinter.PhotoImage(file=resource_path("app.png"))
                self.iconphoto(True, self._icon_image)
        except Exception as e:
            _log.warning("Could not set window icon: %s", e)

    # --- layout -----------------------------------------------------------

    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=240, corner_radius=0, fg_color=SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(24, 28))
        self._logo_image = None
        try:
            self._logo_image = tkinter.PhotoImage(file=resource_path("app.png")).subsample(5)
            self.logo = tkinter.Label(brand, image=self._logo_image, borderwidth=0, highlightthickness=0)
            self.logo.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        except tkinter.TclError:
            self.logo = None
        ctk.CTkLabel(brand, text="Universal\nDownloader", font=font(16, "bold"), text_color=TEXT, anchor="w",
                     justify="left").grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(brand, text=f"Version {__version__}", font=font(11), text_color=MUTED, anchor="w").grid(
            row=1, column=1, sticky="w")

        self._section_label(self.sidebar, "SAVE TO").grid(row=1, column=0, sticky="w", padx=20)
        self.lbl_folder = ctk.CTkLabel(self.sidebar, text="", font=font(12), text_color=TEXT, anchor="w",
                                       justify="left", wraplength=200)
        self.lbl_folder.grid(row=2, column=0, sticky="ew", padx=20, pady=(4, 8))
        folder_buttons = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        folder_buttons.grid(row=3, column=0, sticky="ew", padx=20)
        folder_buttons.grid_columnconfigure((0, 1), weight=1)
        self.btn_dest = secondary_button(folder_buttons, "Change...", self.select_folder, height=32)
        self.btn_dest.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_open = secondary_button(folder_buttons, "Open", self.open_folder, height=32)
        self.btn_open.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self._show_folder()

        self._section_label(self.sidebar, "APPEARANCE").grid(row=4, column=0, sticky="w", padx=20, pady=(28, 6))
        self.seg_theme = ctk.CTkSegmentedButton(self.sidebar, values=list(settings_store.THEMES),
                                                command=self._on_theme_changed, font=font(12),
                                                selected_color=ACCENT, selected_hover_color=ACCENT_HOVER)
        self.seg_theme.set(self.settings.theme)
        self.seg_theme.grid(row=5, column=0, sticky="ew", padx=20)

        self.sidebar.grid_rowconfigure(6, weight=1)
        status = ctk.CTkFrame(self.sidebar, fg_color=CARD, corner_radius=10)
        status.grid(row=7, column=0, sticky="ew", padx=16, pady=16)
        self.lbl_status_dot = ctk.CTkLabel(status, text="\u25cf", font=font(14), text_color=MUTED, width=16)
        self.lbl_status_dot.grid(row=0, column=0, padx=(12, 6), pady=10)
        self.lbl_status = ctk.CTkLabel(status, text="Checking FFmpeg...", font=font(12), text_color=MUTED,
                                       anchor="w")
        self.lbl_status.grid(row=0, column=1, sticky="w", pady=10, padx=(0, 12))
        self._refresh_logo_bg()

    def _section_label(self, parent, text):
        return ctk.CTkLabel(parent, text=text, font=font(11, "bold"), text_color=MUTED, anchor="w")

    def create_main_view(self):
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=28, pady=24)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(5, weight=1)

        header = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(header, text="Download videos and music", font=font(24, "bold"), text_color=TEXT,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(header, text="Paste a link from YouTube, TikTok, Instagram, X or hundreds of other sites.",
                     font=font(13), text_color=MUTED, anchor="w").pack(anchor="w", pady=(2, 0))

        # Link
        url_card = card(self.main_frame)
        url_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        url_card.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(url_card, placeholder_text="https://www.youtube.com/watch?v=...", height=44,
                                      font=font(14), fg_color=FIELD, border_width=0, corner_radius=8)
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=16)
        self.url_entry.bind("<KeyRelease>", self._on_url_changed)
        self.url_entry.bind("<Return>", lambda _e: self.start_analysis_thread())
        self.btn_paste = secondary_button(url_card, "Paste", self.paste_url, width=80, height=44)
        self.btn_paste.grid(row=0, column=1, padx=(0, 8), pady=16)
        self.btn_analyze = primary_button(url_card, "Analyze", self.start_analysis_thread, width=120, height=44,
                                          font=font(14, "bold"))
        self.btn_analyze.grid(row=0, column=2, padx=(0, 16), pady=16)
        self.lbl_media = ctk.CTkLabel(url_card, text="Nothing analysed yet.", font=font(13), text_color=MUTED,
                                      anchor="w", justify="left")
        self.lbl_media.grid(row=1, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 14))

        # Options
        opt_card = card(self.main_frame)
        opt_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        opt_card.grid_columnconfigure((1, 3), weight=1)
        self._section_label(opt_card, "MODE").grid(row=0, column=0, sticky="w", padx=(16, 12), pady=(16, 8))
        self.cmb_mode = ctk.CTkSegmentedButton(opt_card, values=list(formats.MODES), command=self._on_mode_changed,
                                               font=font(13), height=34, selected_color=ACCENT,
                                               selected_hover_color=ACCENT_HOVER)
        self.cmb_mode.grid(row=0, column=1, columnspan=3, sticky="w", pady=(16, 8))
        self._section_label(opt_card, "FORMAT").grid(row=1, column=0, sticky="w", padx=(16, 12), pady=8)
        self.cmb_format = ctk.CTkOptionMenu(opt_card, values=["mp4"], command=lambda _v: self._save_settings(),
                                            width=150, height=34, font=font(13), fg_color=SECONDARY,
                                            button_color=SECONDARY, button_hover_color=SECONDARY_HOVER,
                                            text_color=TEXT, dropdown_font=font(13))
        self.cmb_format.grid(row=1, column=1, sticky="w", pady=8)
        self._section_label(opt_card, "QUALITY").grid(row=1, column=2, sticky="w", padx=(16, 12), pady=8)
        self.cmb_quality = ctk.CTkOptionMenu(opt_card, values=["Best"], command=lambda _v: self._save_settings(),
                                             width=150, height=34, font=font(13), fg_color=SECONDARY,
                                             button_color=SECONDARY, button_hover_color=SECONDARY_HOVER,
                                             text_color=TEXT, dropdown_font=font(13))
        self.cmb_quality.grid(row=1, column=3, sticky="w", pady=8)

        self._section_label(opt_card, "TRIM").grid(row=2, column=0, sticky="w", padx=(16, 12), pady=(8, 16))
        trim_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        trim_row.grid(row=2, column=1, columnspan=3, sticky="w", pady=(8, 16))
        self.chk_trim = ctk.CTkSwitch(trim_row, text="Only part of the video", command=self.toggle_trim,
                                      font=font(13), progress_color=ACCENT)
        self.chk_trim.grid(row=0, column=0, padx=(0, 16))
        self.ent_start = ctk.CTkEntry(trim_row, placeholder_text="Start  0:10", width=110, height=32,
                                      fg_color=FIELD, border_width=0)
        self.ent_start.grid(row=0, column=1, padx=(0, 6))
        ctk.CTkLabel(trim_row, text="to", text_color=MUTED, font=font(13)).grid(row=0, column=2, padx=4)
        self.ent_end = ctk.CTkEntry(trim_row, placeholder_text="End  1:30", width=110, height=32,
                                    fg_color=FIELD, border_width=0)
        self.ent_end.grid(row=0, column=3, padx=(6, 12))
        self.lbl_trim_hint = ctk.CTkLabel(trim_row, text="SS, MM:SS or HH:MM:SS", text_color=MUTED, font=font(12))
        self.lbl_trim_hint.grid(row=0, column=4)
        self.toggle_trim()

        # Actions
        actions = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        actions.grid_columnconfigure(0, weight=1)
        self.btn_download = primary_button(actions, "Download", self.start_download_queue, height=48,
                                           corner_radius=10, font=font(16, "bold"))
        set_primary_state(self.btn_download, "disabled")
        self.btn_download.grid(row=0, column=0, sticky="ew")
        self.btn_cancel = secondary_button(actions, "Cancel", self.cancel_job, width=110, height=48,
                                           state="disabled")
        self.btn_cancel.grid(row=0, column=1, padx=(10, 0))
        self.btn_retry = secondary_button(actions, "Retry failed", self.retry_failed, width=140, height=48,
                                          state="disabled")
        self.btn_retry.grid(row=0, column=2, padx=(10, 0))

        # Progress
        prog_card = card(self.main_frame)
        prog_card.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        prog_card.grid_columnconfigure(0, weight=1)
        self.lbl_item = ctk.CTkLabel(prog_card, text="Ready", font=font(13, "bold"), text_color=TEXT, anchor="w")
        self.lbl_item.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 6))
        self.progress_bar = ctk.CTkProgressBar(prog_card, height=10, corner_radius=5, progress_color=ACCENT)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16)
        self.lbl_progress = ctk.CTkLabel(prog_card, text="0%", font=font(12), text_color=MUTED, anchor="w")
        self.lbl_progress.grid(row=2, column=0, sticky="w", padx=16, pady=(4, 12))
        self.lbl_detail = ctk.CTkLabel(prog_card, text="", font=font(12), text_color=MUTED, anchor="e")
        self.lbl_detail.grid(row=2, column=1, sticky="e", padx=16, pady=(4, 12))

        # Activity log
        log_card = card(self.main_frame)
        log_card.grid(row=5, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        self._section_label(log_card, "ACTIVITY").grid(row=0, column=0, sticky="w", padx=16, pady=(12, 4))
        self.console = ctk.CTkTextbox(log_card, height=120, font=ctk.CTkFont(family="Consolas", size=12),
                                      fg_color="transparent", text_color=TEXT, wrap="word")
        self.console.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.log("Welcome! Paste a link and press Analyze.")

    # --- small UI helpers ---------------------------------------------------

    def log(self, message):
        """Queue a console line; safe to call from any thread."""
        self.events.post(events.LOG, message=message)
    def _append_log(self, message):
        self.console.insert("end", f"> {message}\n")
        self.console.see("end")
    def _show_progress(self, fraction, text, detail=""):
        self.progress_bar.set(fraction)
        self.lbl_progress.configure(text=text)
        self.lbl_detail.configure(text=detail)
    def _show_stage(self, text):
        self.lbl_detail.configure(text=text)
    def _on_item_started(self, position, total, title):
        prefix = f"{position} of {total}:  " if total > 1 else ""
        self.lbl_item.configure(text=f"{prefix}{title}")
        self.progress_bar.configure(progress_color=ACCENT)
        self._show_progress(0, "Starting...")
    def _show_folder(self):
        self.lbl_folder.configure(text=self.download_folder)
    def _refresh_logo_bg(self):
        if self.logo is not None:
            dark = ctk.get_appearance_mode() == "Dark"
            self.logo.configure(bg=SIDEBAR[1] if dark else SIDEBAR[0])
    def _on_theme_changed(self, theme):
        ctk.set_appearance_mode(theme)
        self._refresh_logo_bg()
        self._save_settings()
    def _save_settings(self):
        self.settings = settings_store.Settings(
            download_folder=self.download_folder, mode=self.cmb_mode.get(), format=self.cmb_format.get(),
            quality=self.cmb_quality.get(), theme=self.seg_theme.get())
        settings_store.save(self.settings_path, self.settings)
    def _apply_mode(self, mode, fmt=None, quality=None):
        self.cmb_mode.set(mode)
        self._on_mode_changed(mode, save=False)
        if fmt in formats.formats_for_mode(mode):
            self.cmb_format.set(fmt)
        if quality in formats.qualities_for_mode(mode):
            self.cmb_quality.set(quality)
    def _on_mode_changed(self, mode, save=True):
        """Offer only the formats and qualities that are valid for ``mode``."""
        choices = formats.formats_for_mode(mode)
        self.cmb_format.configure(values=choices)
        if self.cmb_format.get() not in choices:
            self.cmb_format.set(choices[0])
        qualities = formats.qualities_for_mode(mode)
        self.cmb_quality.configure(values=qualities)
        if self.cmb_quality.get() not in qualities:
            self.cmb_quality.set(qualities[0])
        if save:
            self._save_settings()
    def toggle_trim(self):
        state = "normal" if self.chk_trim.get() else "disabled"
        self.ent_start.configure(state=state)
        self.ent_end.configure(state=state)
    def select_folder(self):
        folder = filedialog.askdirectory(initialdir=self.download_folder, parent=self)
        if folder:
            self.download_folder = os.path.normpath(folder)
            self._show_folder()
            self._save_settings()
            self._append_log(f"Saving to {self.download_folder}")
    def open_folder(self):
        folder = self.download_folder
        try:
            os.makedirs(folder, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])
        except OSError as e:
            self._append_log(f"Could not open {folder}: {e}")
    def paste_url(self):
        try:
            text = self.clipboard_get().strip()
        except tkinter.TclError:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)
        self._on_url_changed()
    def _set_status(self, text, color):
        self.lbl_status.configure(text=text, text_color=color)
        self.lbl_status_dot.configure(text_color=color)
    def is_busy(self):
        return self._job_kind is not None

    def _start_job(self, kind, target, *args):
        """Start a worker thread unless another job is running.

        Returns False (and starts nothing) when a job is already active, so a
        second click cannot run two workers against the same state.
        """
        if self.is_busy():
            self._append_log(f"Busy: wait for the current {self._job_kind} to finish.")
            return False
        self._job_kind = kind
        self._cancel_event = threading.Event()
        self._set_controls_busy(True)
        self._job_thread = threading.Thread(target=target, args=args, name=f"uvd-{kind}", daemon=True)
        self._job_thread.start()
        return True

    def _end_job(self):
        self._job_kind = None
        self._job_thread = None
        self._set_controls_busy(False)

    def _set_controls_busy(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (self.url_entry, self.btn_paste, self.btn_dest, self.chk_trim,
                       self.cmb_mode, self.cmb_format, self.cmb_quality):
            widget.configure(state=state)
        trim_state = "normal" if (not busy and self.chk_trim.get()) else "disabled"
        self.ent_start.configure(state=trim_state)
        self.ent_end.configure(state=trim_state)
        # Only downloads can be cancelled; analysis is a single request
        # bounded by the network timeout.
        self.btn_cancel.configure(state="normal" if busy and self._job_kind == "download" else "disabled",
                                  text="Cancel")
        set_primary_state(self.btn_analyze, state)
        if busy:
            set_primary_state(self.btn_download, "disabled")
            self.btn_retry.configure(state="disabled")
        else:
            self._refresh_download_button()
            self._refresh_retry_button()

    def _refresh_download_button(self):
        count = len(self.download_queue)
        if self.tools is not None and not self.tools.ok:
            set_primary_state(self.btn_download, "disabled", text="FFmpeg missing")
        elif count:
            set_primary_state(self.btn_download, "normal",
                              text=f"Download {count} items" if count > 1 else "Download")
        else:
            set_primary_state(self.btn_download, "disabled", text="Download")

    def _failed_items(self):
        if self.last_summary is None:
            return []
        return [r.source or {'url': r.url, 'title': r.title}
                for r in self.last_summary.with_status(ItemStatus.FAILED)]

    def _refresh_retry_button(self):
        count = len(self._failed_items())
        if count:
            self.btn_retry.configure(state="normal", text=f"Retry {count} failed")
        else:
            self.btn_retry.configure(state="disabled", text="Retry failed")

    def cancel_job(self):
        """Ask the running download to stop; results arrive via job_done."""
        if self._job_kind != "download" or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.btn_cancel.configure(state="disabled", text="Cancelling...")
        self._append_log("Cancelling...")

    def retry_failed(self):
        items = self._failed_items()
        if not items or self.is_busy():
            return
        self._append_log(f"Retrying {len(items)} failed item(s).")
        self.download_queue = items
        self.skipped_items = []
        self.start_download_queue()

    CLOSE_TIMEOUT_MS = 15000

    def on_close(self):
        """Window close: confirm, cancel a running download, wait, then exit."""
        if self._closing:
            return
        if self._job_kind == "download":
            if not messagebox.askyesno("Download in progress",
                                       "A download is still running. Cancel it and quit?", parent=self):
                return
            self._closing = True
            self.cancel_job()
            self._wait_then_destroy(self.CLOSE_TIMEOUT_MS)
            return
        # An analysis is one bounded request on a daemon thread; nothing to
        # clean up, so the window can close right away.
        self._closing = True
        self.destroy()

    def _wait_then_destroy(self, remaining_ms):
        thread = self._job_thread
        if thread is None or not thread.is_alive() or remaining_ms <= 0:
            if thread is not None and thread.is_alive():
                _log.warning("Worker did not stop within %d ms; closing anyway", self.CLOSE_TIMEOUT_MS)
            self.destroy()
            return
        self.after(100, self._wait_then_destroy, remaining_ms - 100)

    def _on_url_changed(self, _event=None):
        """Drop the analysed queue as soon as the URL no longer matches it."""
        if self.is_busy() or self.analyzed_url is None:
            return
        if self.url_entry.get().strip() != self.analyzed_url:
            self.analyzed_url = None
            self.set_queue([])

    def start_analysis_thread(self):
        if self.is_busy():
            return
        try:
            url = urls.normalize_url(self.url_entry.get())
        except ValueError as e:
            # Rejected before any network request (ISSUES.md #32).
            self.lbl_media.configure(text=str(e), text_color=DANGER)
            return
        if url != self.url_entry.get().strip():
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
        # A new analysis invalidates the previous queue and progress.
        self.analyzed_url = None
        self.set_queue([])
        self._show_progress(0, "0%")
        self.lbl_item.configure(text="Ready")
        if self._start_job("analysis", self.run_analysis, url):
            self.btn_analyze.configure(text="Checking...")
            self.lbl_media.configure(text="Reading the link...", text_color=MUTED)
    def run_tool_check(self):
        """Worker thread: find and verify FFmpeg/ffprobe."""
        try:
            status = self.manager.ensure_tools()
        except Exception as e:
            status = media_tools.ToolStatus(False, error=f"FFmpeg check failed: {e}")
        self.events.post(events.TOOLS_CHECKED, status=status)
    def _on_tools_checked(self, status):
        self.tools = status
        self._end_job()
        self._append_log(status.summary())
        if status.ok:
            self._set_status(f"FFmpeg {status.version.split('-')[0]} ready", SUCCESS)
        else:
            self._set_status("FFmpeg missing", DANGER)
            messagebox.showerror("FFmpeg missing", f"{status.error}\n\nDownloads are disabled.", parent=self)
    def run_analysis(self, url):
        """Worker thread: fetch info and post the result; no widget access."""
        try:
            self.log("Fetching info...")
            info = self.manager.fetch_info(url)
            if info is None:
                self.events.post(events.ANALYSIS_FAILED, message="ERROR: Info is None.")
            elif 'error' in info:
                self.events.post(events.ANALYSIS_FAILED, message=f"FAILED: {info['error']}")
            else:
                self.events.post(events.ANALYSIS_DONE, analysis=playlist.analyze(info, url), url=url)
        except Exception as e:
            self.events.post(events.ANALYSIS_FAILED, message=f"Error: {e}")
    def _on_analysis_failed(self, message):
        self._append_log(message)
        self.btn_analyze.configure(text="Analyze")
        self.lbl_media.configure(text=message, text_color=DANGER)
        self._end_job()
    def _on_analysis_done(self, analysis, url):
        self.btn_analyze.configure(text="Analyze")
        self._end_job()
        self._describe_analysis(analysis)
        for item in analysis.skipped:
            self._append_log(f"Skipped: {item.title} ({item.skip_reason})")
        if not analysis.items:
            message = "Nothing downloadable was found at this link."
            if analysis.skipped:
                message = f"Nothing downloadable: {analysis.skipped[0].skip_reason}."
            self._append_log(message)
            messagebox.showwarning("Nothing to download", message, parent=self)
            return
        if analysis.is_playlist:
            self._append_log(f"Playlist: {analysis.title} ({len(analysis.items)} downloadable, "
                             f"{len(analysis.skipped)} skipped)")
            self._pending_skipped = [item.as_dict() for item in analysis.skipped]
            self.playlist_dialog = PlaylistSelector(
                self, analysis, lambda items: self._on_playlist_selected(url, items))
        else:
            self._append_log(f"Single Video: {analysis.title}")
            self.analyzed_url = url
            self.set_queue([item.as_dict() for item in analysis.items])
    def _describe_analysis(self, analysis):
        if not analysis.items:
            self.lbl_media.configure(text=f"{analysis.title}: nothing downloadable", text_color=WARNING)
            return
        if analysis.is_playlist:
            detail = f"Playlist  \u00b7  {len(analysis.items)} videos"
            if analysis.skipped:
                detail += f"  \u00b7  {len(analysis.skipped)} unavailable"
        else:
            duration = analysis.items[0].duration
            detail = "Video" + (f"  \u00b7  {format_duration(duration)}" if duration else "")
        self.lbl_media.configure(text=f"{analysis.title}\n{detail}", text_color=TEXT)
    def _on_playlist_selected(self, url, items):
        self.playlist_dialog = None
        if items is None:
            self._append_log("Playlist selection cancelled.")
            return
        if self.url_entry.get().strip() != url:
            self._append_log("The link changed; analyse it again.")
            return
        self.analyzed_url = url
        self.set_queue([item.as_dict() for item in items], skipped=self._pending_skipped)
    def set_queue(self, items, skipped=()):
        self.download_queue = list(items)
        # Entries that cannot be downloaded; reported as skipped in the result.
        self.skipped_items = list(skipped) if self.download_queue else []
        if self.download_queue:
            self.log(f"Queue ready: {len(self.download_queue)} item(s).")
        if not self.is_busy():
            self._refresh_download_button()
    def start_download_queue(self):
        if not self.download_queue or self.is_busy(): return
        if self.chk_trim.get():
            # Kötü trim değerleriyle kuyruğu hiç başlatma
            try:
                if parse_trim_range(self.ent_start.get(), self.ent_end.get()) is None:
                    raise TrimError("Enter a trim start and/or end time")
            except TrimError as e:
                self.log(f"Trim error: {e}")
                messagebox.showerror("Invalid trim range", str(e), parent=self)
                return
        error, warning = filenames.check_folder(self.download_folder)
        if error:
            self._append_log(error)
            messagebox.showerror("Download folder", error, parent=self)
            return
        if warning:
            self._append_log(f"Warning: {warning}")
        self._show_progress(0, "0%")
        items = list(self.download_queue) + list(self.skipped_items)
        opts = {
            'save_path': self.download_folder, 'mode': self.cmb_mode.get(),
            'format': self.cmb_format.get(), 'quality': self.cmb_quality.get(),
            'trim_start': self.ent_start.get() if self.chk_trim.get() else None,
            'trim_end': self.ent_end.get() if self.chk_trim.get() else None
        }
        if self._start_job("download", self._run_queue_with_cancel, items, opts):
            self.btn_download.configure(text="Downloading...")
    def run_queue(self, items, opts, cancel_event=None):
        """Worker thread: download each item and post events; no widget access."""
        summary = JobSummary()
        total = len(items)
        try:
            for i, item in enumerate(items):
                if item.get('skip_reason'):
                    # Unavailable playlist entries count in the summary as skipped.
                    result = ItemResult(item['url'], item['title'], ItemStatus.SKIPPED, error=item['skip_reason'])
                    summary.add(result)
                    self.events.post(events.ITEM_DONE, result=result)
                    continue
                if cancel_event is not None and cancel_event.is_set():
                    result = ItemResult(item['url'], item['title'], ItemStatus.CANCELLED, error='Cancelled by user')
                    summary.add(result)
                    self.events.post(events.ITEM_DONE, result=result)
                    continue
                self.log(f"[{i+1}/{total}] {item['title']}")
                self.events.post(events.ITEM_STARTED, position=i + 1, total=total, title=item['title'])
                item_opts = dict(opts, playlist_index=item.get('index'), playlist_title=item.get('playlist'))
                try:
                    result = self.manager.download_video(
                        item['url'], item_opts, self.progress_hook, log_callback=self.log, title=item['title'],
                        cancel_event=cancel_event)
                except Exception as e:
                    result = ItemResult(item['url'], item['title'], ItemStatus.FAILED, error=str(e) or type(e).__name__)
                result.source = item
                summary.add(result)
                self.events.post(events.ITEM_DONE, result=result)
        finally:
            self.events.post(events.JOB_DONE, summary=summary)
    def _run_queue_with_cancel(self, items, opts):
        # Bound at start so a later job's event cannot leak into this one.
        self.run_queue(items, opts, self._cancel_event)
    def _on_item_done(self, result):
        self._append_log(result.describe())
    def _on_job_done(self, summary):
        self._append_log(f"Result: {summary.headline()}")
        self.last_summary = summary
        self._end_job()
        if self._closing:
            return
        self.lbl_item.configure(text=f"{summary.title()}: {summary.headline()}")
        done = len(summary.with_status(ItemStatus.COMPLETED))
        self.progress_bar.configure(progress_color=SUCCESS if summary.all_ok else WARNING if done else DANGER)
        if summary.all_ok:
            self._show_progress(1, "Complete")
            messagebox.showinfo(summary.title(), summary.report(), parent=self)
        else:
            self._show_progress(done / len(summary.results) if summary.results else 0, summary.headline())
            messagebox.showwarning(summary.title(), summary.report(), parent=self)
    def progress_hook(self, d):
        """yt-dlp progress and postprocessor hook; runs on the worker thread."""
        stage = events.stage_from_hook(d)
        if stage is not None:
            self.events.post(events.STAGE, text=stage)
            return
        progress = events.progress_from_hook(d)
        if progress is not None:
            fraction, text = progress
            self.events.post(events.PROGRESS, fraction=fraction, text=text, detail=events.detail_from_hook(d))


def format_duration(seconds):
    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
