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

# Design tokens: (light, dark) pairs, the CustomTkinter convention. Text
# colours keep at least 4.5:1 contrast on the backgrounds they are used on.
ACCENT = ("#5b5bd6", "#5f5ae6")
ACCENT_HOVER = ("#4848c2", "#4d48d4")
ACCENT_DISABLED = ("#b4b4ea", "#3a3970")
ON_ACCENT = "#ffffff"
ON_ACCENT_DISABLED = ("#f1f1fc", "#8e8cc0")
BG = ("#f3f4f8", "#12131c")
TOPBAR = ("#ffffff", "#181926")
CARD = ("#ffffff", "#1e2030")
CARD_BORDER = ("#e1e3ec", "#2a2d42")
FIELD = ("#f5f6fa", "#262939")
MUTED = ("#6b6f80", "#9aa0b4")
TEXT = ("#1b1d29", "#eceef6")
SECONDARY = ("#e4e5ef", "#2c2f44")
SECONDARY_HOVER = ("#d6d8e6", "#363a52")
DANGER = ("#c53b3b", "#ef5b5b")
SUCCESS = ("#1d7a50", "#3dd68c")
WARNING = ("#946214", "#f0b429")


def font(size=13, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=CARD_BORDER, **kw)


# Room for the title bar and frame, which geometry() sizes do not include.
WINDOW_FRAME_PX = 48


def work_area(window):
    """(left, top, right, bottom) of the usable screen in pixels.

    On Windows this is the monitor minus the taskbar; elsewhere the screen
    minus room for a panel.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            pass
    return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight() - 48


def place_on_screen(window, width_px, height_px, min_px=None):
    """Size ``window`` to ``width_px`` x ``height_px`` pixels, capped to the work
    area, and move it so the whole window, title bar included, is visible.

    ``min_px`` (width, height) becomes the window's minimum size, also capped.
    Returns the size used, in pixels.
    """
    left, top, right, bottom = work_area(window)
    avail_w, avail_h = right - left, bottom - top - WINDOW_FRAME_PX
    width, height = min(width_px, avail_w), min(height_px, avail_h)
    scale = window._get_window_scaling()
    if min_px is not None:
        window.minsize(int(min(min_px[0], avail_w) / scale), int(min(min_px[1], avail_h) / scale))
    size = f"{round(width / scale)}x{round(height / scale)}"
    # winfo_x/y is the window's outer corner, title bar included.
    x, y = window.winfo_x(), window.winfo_y()
    new_x = min(max(x, left), max(left, right - width))
    new_y = min(max(y, top), max(top, bottom - WINDOW_FRAME_PX - height))
    window.geometry(size if (new_x, new_y) == (x, y) else f"{size}+{new_x}+{new_y}")
    return width, height


def fit_dialog(dialog, size, min_size):
    """Size a dialog for the current text size (``size`` is at Normal),
    over its parent and within the screen."""
    try:
        ws = ctk.ScalingTracker.get_widget_scaling(dialog)
        scale = dialog._get_window_scaling()
        parent = dialog.master
        dialog.geometry(f"+{parent.winfo_rootx() + 60}+{parent.winfo_rooty() + 40}")
        dialog.update_idletasks()
        width, height = (round(v * ws * scale) for v in size)
        place_on_screen(dialog, width, height, min_px=tuple(round(v * ws * scale) for v in min_size))
    except tkinter.TclError:
        pass  # closed already


def set_window_icon(window):
    """The app icon: the .ico on Windows, the PNG elsewhere (Tk reads PNG natively)."""
    try:
        if sys.platform == "win32":
            window.iconbitmap(resource_path("app.ico"))
        else:
            window._icon_image = tkinter.PhotoImage(file=resource_path("app.png"))
            window.iconphoto(False, window._icon_image)
    except Exception as e:
        _log.warning("Could not set window icon: %s", e)


def shorten_path(path, limit=64):
    """``path`` cut in the middle to at most ``limit`` characters."""
    if len(path) <= limit:
        return path
    keep = limit - 3
    head = keep // 3
    return path[:head] + "..." + path[-(keep - head):]


def section_label(parent, text):
    return ctk.CTkLabel(parent, text=text, font=font(12, "bold"), text_color=MUTED, anchor="w")


MEDIA_HINT = "Works with YouTube, TikTok, Instagram, X and hundreds of other sites. Press Enter to analyze."
# Selected segment: a white chip in light mode (dark text stays readable),
# the accent in dark mode (light text on it).
SEGMENT_SELECTED = ("#ffffff", ACCENT[1])
SEGMENT_SELECTED_HOVER = ("#f4f4fb", ACCENT_HOVER[1])


def segmented(parent, values, command, **kw):
    kw.setdefault("height", 34)
    return ctk.CTkSegmentedButton(parent, values=values, command=command, font=font(13), fg_color=SECONDARY,
                                  unselected_color=SECONDARY, unselected_hover_color=SECONDARY_HOVER,
                                  selected_color=SEGMENT_SELECTED, selected_hover_color=SEGMENT_SELECTED_HOVER,
                                  text_color=TEXT, **kw)


def switch(parent, text, command, **kw):
    return ctk.CTkSwitch(parent, text=text, command=command, font=font(13), text_color=TEXT, progress_color=ACCENT,
                         fg_color=("#c3c6d4", "#3a3e55"), button_color=("#5b5f73", "#e8e9f2"),
                         button_hover_color=("#44475a", "#ffffff"), **kw)


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
        # CustomTkinter puts its own icon on new windows shortly after
        # they open, so the app icon is set now and again after that.
        set_window_icon(self)
        self.after(250, set_window_icon, self)
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
        fit_dialog(self, (640, 540), (420, 360))
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

class SettingsDialog(ctk.CTkToplevel):
    """Modal settings: appearance, what happens after a download, about.

    Every change applies at once and is saved; ``on_change(name, value)``
    tells the app which setting changed.
    """

    SHORTCUTS = (
        ("Enter", "Analyze the link"),
        ("Ctrl+Enter", "Start the download"),
        ("Esc", "Cancel the download"),
        ("Ctrl+O", "Choose the download folder"),
        ("Ctrl+,", "Open settings"),
    )

    def __init__(self, parent, settings, tools, on_change):
        super().__init__(parent, fg_color=BG)
        self.title("Settings")
        self.transient(parent)
        # CustomTkinter puts its own icon on new windows shortly after
        # they open, so the app icon is set now and again after that.
        set_window_icon(self)
        self.after(250, set_window_icon, self)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())
        self.on_change = on_change
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Settings", font=font(22, "bold"), text_color=TEXT, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=24, pady=(20, 8))
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=12)
        body.grid_columnconfigure(0, weight=1)

        # Appearance
        look = self._section(body, 0, "Appearance")
        self._row_label(look, 1, "Theme", "Follow Windows, or always dark or light.")
        self.seg_theme = segmented(look, list(settings_store.THEMES), lambda v: self.on_change("theme", v))
        self.seg_theme.set(settings.theme)
        self.seg_theme.grid(row=2, column=0, sticky="w", padx=16, pady=(0, 14))
        self._row_label(look, 3, "Text size", "Makes all text and controls bigger.")
        self.seg_text = segmented(look, list(settings_store.TEXT_SIZES), lambda v: self.on_change("text_size", v))
        self.seg_text.set(settings.text_size)
        self.seg_text.grid(row=4, column=0, sticky="w", padx=16, pady=(0, 16))

        # After downloading
        after = self._section(body, 1, "When downloads finish")
        self.sw_summary = self._switch(after, 1, "Show a summary window", settings.show_summary, "show_summary")
        self.sw_open = self._switch(after, 2, "Open the download folder", settings.open_folder_when_done,
                                    "open_folder_when_done")

        # Keyboard
        keys = self._section(body, 2, "Keyboard shortcuts")
        for i, (key, action) in enumerate(self.SHORTCUTS, start=1):
            row = ctk.CTkFrame(keys, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", padx=16, pady=(0, 8 if i < len(self.SHORTCUTS) else 16))
            ctk.CTkLabel(row, text=key, font=font(12, "bold"), text_color=TEXT, fg_color=FIELD, corner_radius=6,
                         width=96, height=26).pack(side="left")
            ctk.CTkLabel(row, text=action, font=font(13), text_color=TEXT, anchor="w").pack(side="left", padx=12)

        # About
        about = self._section(body, 3, "About")
        ctk.CTkLabel(about, text=f"{DISPLAY_NAME} {__version__}", font=font(13, "bold"), text_color=TEXT,
                     anchor="w").grid(row=1, column=0, sticky="ew", padx=16)
        tools_text = tools.summary() if tools is not None else "Checking FFmpeg..."
        ctk.CTkLabel(about, text=tools_text, font=font(12), text_color=MUTED, anchor="w", justify="left",
                     wraplength=440).grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 10))
        self.btn_logs = secondary_button(about, "Open log folder", self.open_logs, width=150, height=34)
        self.btn_logs.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 16))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=16)
        self.btn_done = primary_button(footer, "Done", self.close, width=120, height=40)
        self.btn_done.pack(side="right")
        self.fit()
        self.after(100, self._grab)

    def fit(self):
        fit_dialog(self, (560, 660), (480, 420))

    def _section(self, parent, row, title):
        frame = card(parent)
        frame.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 12))
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=title, font=font(15, "bold"), text_color=TEXT, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        return frame

    def _row_label(self, parent, row, title, hint):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 6))
        ctk.CTkLabel(box, text=title, font=font(13, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(box, text=hint, font=font(12), text_color=MUTED, anchor="w").pack(anchor="w")

    def _switch(self, parent, row, text, value, name):
        widget = switch(parent, text, lambda: self.on_change(name, bool(widget.get())))
        if value:
            widget.select()
        widget.grid(row=row, column=0, sticky="w", padx=16, pady=(0, 14))
        return widget

    def open_logs(self):
        open_path(app_setup.data_dir())

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass

    def close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


def open_path(folder):
    """Show ``folder`` in Explorer (or the platform's file manager)."""
    os.makedirs(folder, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(folder)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])


class App(ctk.CTk):
    MIN_SIZE = (900, 700)

    def __init__(self):
        super().__init__()
        self.title(f"{DISPLAY_NAME} {__version__}")
        self.geometry("1040x800")
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
        ctk.set_widget_scaling(settings_store.TEXT_SIZES[self.settings.text_size])

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

        self.settings_dialog = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.create_top_bar()
        self.create_main_view()
        self._bind_shortcuts()
        self.after(50, self._fit_to_content)
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
        set_window_icon(self)

    # --- layout -----------------------------------------------------------

    def create_top_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=0, fg_color=TOPBAR, height=64, border_width=0)
        bar.grid(row=0, column=0, sticky="new")
        bar.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(bar, height=1, corner_radius=0, fg_color=CARD_BORDER).grid(row=1, column=0, columnspan=3,
                                                                              sticky="ew")
        self.top_bar = bar

        brand = ctk.CTkFrame(bar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=(24, 0), pady=12)
        self._logo_image = None
        try:
            self._logo_image = tkinter.PhotoImage(file=resource_path("app.png")).subsample(6)
            self.logo = tkinter.Label(brand, image=self._logo_image, borderwidth=0, highlightthickness=0)
            self.logo.pack(side="left", padx=(0, 12))
        except tkinter.TclError:
            self.logo = None
        ctk.CTkLabel(brand, text="Universal Downloader", font=font(17, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(brand, text=f"v{__version__}", font=font(12), text_color=MUTED).pack(side="left", padx=(8, 0))

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=(0, 24), pady=12)
        status = ctk.CTkFrame(right, fg_color=FIELD, corner_radius=16)
        status.pack(side="left", padx=(0, 12))
        self.lbl_status_dot = ctk.CTkLabel(status, text="\u25cf", font=font(13), text_color=MUTED, width=14)
        self.lbl_status_dot.pack(side="left", padx=(12, 4), pady=4)
        self.lbl_status = ctk.CTkLabel(status, text="Checking FFmpeg...", font=font(12), text_color=MUTED)
        self.lbl_status.pack(side="left", padx=(0, 14), pady=4)
        self.btn_settings = secondary_button(right, "\u2699  Settings", self.open_settings, width=120, height=36)
        self.btn_settings.pack(side="left")
        self._refresh_logo_bg()

    def _section_label(self, parent, text):
        return section_label(parent, text)

    def create_main_view(self):
        # Scrolls only when the window cannot be tall enough for its content
        # (large text on a small screen); otherwise the activity box takes
        # the spare height (see _fill_height).
        self.main_frame = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent",
                                                 scrollbar_button_color=BG, scrollbar_button_hover_color=BG)
        self.main_frame.grid(row=1, column=0, sticky="nsew", padx=(32, 12), pady=(20, 16))
        self.main_frame.grid_columnconfigure(0, weight=1)
        self._scroll_canvas = self.main_frame._parent_canvas

        # The top bar names the app, so the link card comes first.

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
        self.lbl_media = ctk.CTkLabel(url_card, text=MEDIA_HINT, font=font(13), text_color=MUTED,
                                      anchor="w", justify="left")
        self.lbl_media.grid(row=1, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 14))

        # Options
        opt_card = card(self.main_frame)
        opt_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        opt_card.grid_columnconfigure((1, 3), weight=1)
        self._section_label(opt_card, "MODE").grid(row=0, column=0, sticky="w", padx=(16, 12), pady=(16, 8))
        self.cmb_mode = segmented(opt_card, list(formats.MODES), self._on_mode_changed)
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

        self._section_label(opt_card, "TRIM").grid(row=2, column=0, sticky="w", padx=(16, 12), pady=(8, 12))
        trim_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        trim_row.grid(row=2, column=1, columnspan=3, sticky="w", pady=(8, 12))
        self.chk_trim = switch(trim_row, "Only part of the video", self.toggle_trim)
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

        ctk.CTkFrame(opt_card, height=1, corner_radius=0, fg_color=CARD_BORDER).grid(row=3, column=0, columnspan=4, sticky="ew",
                                                                    padx=16)
        self._section_label(opt_card, "SAVE TO").grid(row=4, column=0, sticky="w", padx=(16, 12), pady=12)
        folder_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        folder_row.grid(row=4, column=1, columnspan=3, sticky="ew", padx=(0, 16), pady=12)
        folder_row.grid_columnconfigure(0, weight=1)
        self.lbl_folder = ctk.CTkLabel(folder_row, text="", font=font(13), text_color=TEXT, fg_color=FIELD,
                                       corner_radius=8, height=36, anchor="w")
        self.lbl_folder.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.lbl_folder.bind("<Double-Button-1>", lambda _e: self.open_folder())
        self.btn_dest = secondary_button(folder_row, "Change...", self.select_folder, width=100)
        self.btn_dest.grid(row=0, column=1, padx=(0, 8))
        self.btn_open = secondary_button(folder_row, "Open", self.open_folder, width=80)
        self.btn_open.grid(row=0, column=2)
        self._show_folder()

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
        self.progress_bar = ctk.CTkProgressBar(prog_card, height=10, corner_radius=5, progress_color=ACCENT,
                                               fg_color=SECONDARY)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16)
        self.lbl_progress = ctk.CTkLabel(prog_card, text="0%", font=font(12), text_color=MUTED, anchor="w")
        self.lbl_progress.grid(row=2, column=0, sticky="w", padx=16, pady=(4, 12))
        self.lbl_detail = ctk.CTkLabel(prog_card, text="", font=font(12), text_color=MUTED, anchor="e")
        self.lbl_detail.grid(row=2, column=1, sticky="e", padx=16, pady=(4, 12))

        # Activity log
        log_card = self.log_card = card(self.main_frame)
        log_card.grid(row=5, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        self._section_label(log_card, "ACTIVITY").grid(row=0, column=0, sticky="w", padx=16, pady=(12, 4))
        self.console = ctk.CTkTextbox(log_card, height=100, font=ctk.CTkFont(family="Consolas", size=12),
                                      fg_color="transparent", text_color=TEXT, wrap="word")
        self.console.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        # Keep a gap between the cards and the (usually hidden) scrollbar.
        for card_widget in self.main_frame.grid_slaves():
            card_widget.grid_configure(padx=(0, 16))
        self._scroll_canvas.bind("<Configure>", lambda _e: self.after_idle(self._fill_height), add="+")
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
        self.lbl_folder.configure(text="   " + shorten_path(self.download_folder))
    def _refresh_logo_bg(self):
        if self.logo is not None:
            dark = ctk.get_appearance_mode() == "Dark"
            self.logo.configure(bg=TOPBAR[1] if dark else TOPBAR[0])
    def _on_theme_changed(self, theme):
        ctk.set_appearance_mode(theme)
        self.settings.theme = theme
        self._refresh_logo_bg()
        self._save_settings()
    def _on_setting_changed(self, name, value):
        """Called by the settings dialog; applies and saves one setting."""
        if name == "theme":
            self._on_theme_changed(value)
            return
        setattr(self.settings, name, value)
        if name == "text_size":
            ctk.set_widget_scaling(settings_store.TEXT_SIZES[value])
            self.after(50, self._fit_to_content)
            if self.settings_dialog is not None and self.settings_dialog.winfo_exists():
                self.settings_dialog.after(60, self.settings_dialog.fit)
        self._save_settings()
    LOG_HEIGHT = 100  # activity box height the window is sized for
    LOG_MIN_HEIGHT = 60

    def _fit_to_content(self):
        """Fit the window to its content within the screen's work area.

        Larger text sizes need more room: the window grows up to the work
        area, so the taskbar stays visible. If that is still not enough the
        content scrolls instead of being cut off.
        """
        try:
            self.console.configure(height=self.LOG_HEIGHT)
            self.update_idletasks()
            content = self.main_frame.winfo_reqheight()
            chrome = self.winfo_reqheight() - self._scroll_canvas.winfo_reqheight()
            need = (self.winfo_reqwidth(), chrome + content)
            scale = self._get_window_scaling()
            base_min = (self.MIN_SIZE[0] * scale, self.MIN_SIZE[1] * scale)
            width = max(self.winfo_width(), need[0])
            height = max(self.winfo_height(), need[1])
            # The content scrolls when the window is made smaller than it.
            place_on_screen(self, width, height, min_px=base_min)
            self.after_idle(self._fill_height)
        except tkinter.TclError:
            pass  # window already closed

    def _fill_height(self):
        """Give the activity box the spare height, or show the scrollbar."""
        try:
            ws = ctk.ScalingTracker.get_widget_scaling(self)
            available = self._scroll_canvas.winfo_height()
            others = self.main_frame.winfo_reqheight() - self.console.winfo_reqheight()
            log_px = max(self.LOG_MIN_HEIGHT * ws, available - others)
            height = round(log_px / ws)
            if abs(height - self.console.cget("height")) > 1:
                self.console.configure(height=height)
            scrolls = others + log_px > available + 1
            colour, hover = (SECONDARY, SECONDARY_HOVER) if scrolls else (BG, BG)
            self.main_frame.configure(scrollbar_button_color=colour, scrollbar_button_hover_color=hover)
            self.content_scrolls = scrolls
        except tkinter.TclError:
            pass

    def open_settings(self):
        if self.settings_dialog is not None and self.settings_dialog.winfo_exists():
            self.settings_dialog.focus_force()
            return
        self.settings_dialog = SettingsDialog(self, self.settings, self.tools, self._on_setting_changed)
    def _bind_shortcuts(self):
        self.bind("<Control-Return>", lambda _e: self._shortcut(self.start_download_queue, self.btn_download))
        self.bind("<Escape>", lambda _e: self.cancel_job())
        self.bind("<Control-o>", lambda _e: self._shortcut(self.select_folder, self.btn_dest))
        self.bind("<Control-comma>", lambda _e: self.open_settings())
        # The link field's own Enter binding would otherwise also run.
        self.url_entry.bind("<Control-Return>",
                            lambda _e: self._shortcut(self.start_download_queue, self.btn_download))
        self.after(300, self.url_entry.focus_set)
    def _shortcut(self, action, button):
        # A shortcut does what its button does, and only when it is enabled.
        if button.cget("state") == "normal":
            action()
        return "break"
    def _save_settings(self):
        self.settings.download_folder = self.download_folder
        self.settings.mode = self.cmb_mode.get()
        self.settings.format = self.cmb_format.get()
        self.settings.quality = self.cmb_quality.get()
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
            open_path(folder)
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
        else:
            self._show_progress(done / len(summary.results) if summary.results else 0, summary.headline())
        if done and self.settings.open_folder_when_done:
            self.open_folder()
        if self.settings.show_summary:
            show = messagebox.showinfo if summary.all_ok else messagebox.showwarning
            show(summary.title(), summary.report(), parent=self)
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
