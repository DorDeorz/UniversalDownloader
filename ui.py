import logging
import os
import subprocess
import sys
import threading
import time
import tkinter
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk

import app_setup
import download_history
import events
import filenames
import formats
import i18n
import media_tools
import playlist
import settings as settings_store
import updates
import urls
from logic import DownloadManager, TrimError, parse_trim_range
from results import ItemResult, ItemStatus, JobSummary
from utils import default_download_dir, resource_path
from i18n import tr
from version import DISPLAY_NAME, GITHUB_REPO, __version__

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

# Accent colours offered in Settings (the names match the Android app's).
# Every accent keeps white text readable (4.5:1) in both themes.
ACCENTS = {
    "Indigo": {"accent": ACCENT, "hover": ACCENT_HOVER, "disabled": ACCENT_DISABLED,
               "on_disabled": ON_ACCENT_DISABLED},
    "Blue": {"accent": ("#256fe7", "#256fe7"), "hover": ("#175ed1", "#175ed1"),
             "disabled": ("#b7cbeb", "#293a57"), "on_disabled": ("#f3f6fc", "#9cadc9")},
    "Teal": {"accent": ("#128176", "#128176"), "hover": ("#0e625a", "#0e625a"),
             "disabled": ("#b9e9e4", "#2a5551"), "on_disabled": ("#f3fcfb", "#9cc9c5")},
    "Green": {"accent": ("#1c8542", "#1c8542"), "hover": ("#166734", "#166734"),
              "disabled": ("#bce6cc", "#2d523b"), "on_disabled": ("#f3fcf6", "#9cc9ac")},
    "Purple": {"accent": ("#9a50da", "#9a50da"), "hover": ("#8933d4", "#8933d4"),
               "disabled": ("#d2bce6", "#412d52"), "on_disabled": ("#f8f3fc", "#b49cc9")},
    "Pink": {"accent": ("#d9267f", "#d9267f"), "hover": ("#ba216e", "#ba216e"),
             "disabled": ("#e8bbd1", "#542c40"), "on_disabled": ("#fcf3f7", "#c99cb2")},
    "Red": {"accent": ("#d93636", "#d93636"), "hover": ("#c52626", "#c52626"),
            "disabled": ("#e7bbbb", "#532c2c"), "on_disabled": ("#fcf3f3", "#c99c9c")},
    "Orange": {"accent": ("#c45210", "#c45210"), "hover": ("#a3440d", "#a3440d"),
               "disabled": ("#eccab6", "#583927"), "on_disabled": ("#fcf6f3", "#c9ac9c")},
}
assert tuple(ACCENTS) == settings_store.ACCENTS


def _keep_size_on_state_change(set_cursor):
    """Wrap CTkButton._set_cursor so a button keeps the width its text needs.

    On Windows, enabling or disabling a button sets its cursor through the
    button's frame. Tk then requests the frame's own width again (0 for the
    mode buttons), which replaces the width the text needs, and nothing
    lays the button out again. The app disables its controls at every start
    while it checks FFmpeg, so the mode buttons came up squeezed to squares
    until a language or text size change rebuilt them. Turning propagation
    off and on makes Tk lay the button out again.
    """
    def _set_cursor(self):
        set_cursor(self)
        self.grid_propagate(False)
        self.grid_propagate(True)
    return _set_cursor


ctk.CTkButton._set_cursor = _keep_size_on_state_change(ctk.CTkButton._set_cursor)


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


MODE_KEYS = {formats.VIDEO_AUDIO: "mode.video_audio", formats.VIDEO_ONLY: "mode.video_only",
             formats.AUDIO_ONLY: "mode.audio_only"}


def shorten_path(path, limit=64):
    """``path`` cut in the middle to at most ``limit`` characters."""
    if len(path) <= limit:
        return path
    keep = limit - 3
    head = keep // 3
    return path[:head] + "..." + path[-(keep - head):]


def section_label(parent, text):
    return ctk.CTkLabel(parent, text=text, font=font(12, "bold"), text_color=MUTED, anchor="w")


# Selected segment: a white chip in light mode (dark text stays readable),
# the accent in dark mode (light text on it).
SEGMENT_SELECTED = ("#ffffff", ACCENT[1])
SEGMENT_SELECTED_HOVER = ("#f4f4fb", ACCENT_HOVER[1])

# Widget options that can carry an accent colour (see recolor).
_COLOUR_OPTIONS = ("fg_color", "hover_color", "progress_color", "selected_color", "selected_hover_color",
                   "button_color", "button_hover_color", "border_color", "text_color_disabled")


def apply_accent(name):
    """Make ``name`` the accent for widgets built from now on.

    Returns {old colour: new colour} for :func:`recolor`, which repaints
    the widgets that already exist.
    """
    global ACCENT, ACCENT_HOVER, ACCENT_DISABLED, ON_ACCENT_DISABLED, SEGMENT_SELECTED, SEGMENT_SELECTED_HOVER
    tokens = ACCENTS.get(name, ACCENTS["Indigo"])
    old = (ACCENT, ACCENT_HOVER, ACCENT_DISABLED, ON_ACCENT_DISABLED, SEGMENT_SELECTED, SEGMENT_SELECTED_HOVER)
    ACCENT, ACCENT_HOVER = tokens["accent"], tokens["hover"]
    ACCENT_DISABLED, ON_ACCENT_DISABLED = tokens["disabled"], tokens["on_disabled"]
    SEGMENT_SELECTED = ("#ffffff", ACCENT[1])
    SEGMENT_SELECTED_HOVER = ("#f4f4fb", ACCENT_HOVER[1])
    new = (ACCENT, ACCENT_HOVER, ACCENT_DISABLED, ON_ACCENT_DISABLED, SEGMENT_SELECTED, SEGMENT_SELECTED_HOVER)
    return {o: n for o, n in zip(old, new) if o != n}


def recolor(root, mapping):
    """Repaint every widget under ``root`` that uses a colour in ``mapping``."""
    if not mapping:
        return 0
    changed = 0
    stack = [root]
    while stack:
        widget = stack.pop()
        try:
            stack.extend(widget.winfo_children())
        except tkinter.TclError:
            continue
        if not isinstance(widget, ctk.CTkBaseClass):
            continue
        for option in _COLOUR_OPTIONS:
            try:
                value = widget.cget(option)
            except (ValueError, AttributeError, tkinter.TclError):
                continue
            key = tuple(value) if isinstance(value, list) else value
            if key in mapping:
                widget.configure(**{option: mapping[key]})
                changed += 1
    return changed


class ChoiceSegment(ctk.CTkSegmentedButton):
    """A segmented button that shows translated labels for fixed values.

    ``get``, ``set`` and ``command`` use the values (e.g. "Audio Only"), so
    the rest of the app and the saved settings never see a translation.
    ``relabel`` redraws the labels after a language change.
    """

    def __init__(self, parent, choices, label=str, command=None, **kw):
        self._choices, self._label, self._on_pick = list(choices), label, command
        kw.setdefault("height", 34)
        super().__init__(parent, values=self._labels(), command=self._picked, font=font(13), fg_color=SECONDARY,
                         unselected_color=SECONDARY, unselected_hover_color=SECONDARY_HOVER,
                         selected_color=SEGMENT_SELECTED, selected_hover_color=SEGMENT_SELECTED_HOVER,
                         text_color=TEXT, **kw)

    def _labels(self):
        return [self._label(c) for c in self._choices]

    def _value_of(self, text):
        labels = self._labels()
        return self._choices[labels.index(text)] if text in labels else text

    def _picked(self, text):
        if self._on_pick:
            self._on_pick(self._value_of(text))

    def get(self):
        return self._value_of(super().get())

    def set(self, value, *args, **kwargs):
        super().set(self._label(value) if value in self._choices else value, *args, **kwargs)

    def configure(self, **kwargs):
        if "values" in kwargs:
            # New values rebuild the buttons, and CustomTkinter makes them as
            # tall as the last size it measured, not the height asked for.
            # Measured sizes round down at 125-175% display scaling and can be
            # tiny while the page is hidden, so every language change made the
            # mode buttons smaller. Build them at the requested height instead.
            self._current_height = self._desired_height
        super().configure(**kwargs)

    def relabel(self):
        value = self.get()
        self.configure(values=self._labels())
        if value in self._choices:
            self.set(value)


class ChoiceMenu(ctk.CTkOptionMenu):
    """An option menu with translated labels for its values (see ChoiceSegment)."""

    def __init__(self, parent, choices, label=str, command=None, **kw):
        self._choices, self._label, self._on_pick = list(choices), label, command
        super().__init__(parent, values=self._labels(), command=self._picked, **kw)

    def _labels(self):
        return [self._label(c) for c in self._choices]

    def _value_of(self, text):
        labels = self._labels()
        return self._choices[labels.index(text)] if text in labels else text

    def _picked(self, text):
        if self._on_pick:
            self._on_pick(self._value_of(text))

    def get(self):
        return self._value_of(super().get())

    def set(self, value):
        super().set(self._label(value) if value in self._choices else value)

    def set_choices(self, choices):
        value = self.get()
        self._choices = list(choices)
        self.configure(values=self._labels())
        if value in self._choices:
            self.set(value)

    def relabel(self):
        self.set_choices(self._choices)


def segmented(parent, values, command, label=str, **kw):
    return ChoiceSegment(parent, values, label, command, **kw)


def option_menu(parent, choices, command, label=str, **kw):
    return ChoiceMenu(parent, choices, label, command, height=34, font=font(13), fg_color=SECONDARY,
                      button_color=SECONDARY, button_hover_color=SECONDARY_HOVER, text_color=TEXT,
                      dropdown_font=font(13), **kw)


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
        self.title(tr("playlist.title"))
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

        if analysis.skipped:
            heading = tr("playlist.heading_skipped", title=analysis.title, count=len(self.items),
                         skipped=len(analysis.skipped))
        else:
            heading = tr("playlist.heading", title=analysis.title, count=len(self.items))
        self.lbl_title = ctk.CTkLabel(self, text=heading, font=font(16, "bold"), text_color=TEXT,
                                      wraplength=600, anchor="w", justify="left")
        self.lbl_title.pack(fill="x", pady=(18, 2), padx=20)
        if analysis.skipped:
            reasons = {}
            for item in analysis.skipped:
                reasons[item.skip_reason] = reasons.get(item.skip_reason, 0) + 1
            detail = tr("playlist.skipped", reasons=", ".join(
                f"{n} {i18n.tr_message(reason)}" for reason, n in reasons.items()))
            ctk.CTkLabel(self, text=detail, font=font(12), text_color=MUTED, wraplength=600, anchor="w",
                         justify="left").pack(fill="x", padx=20)

        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(fill="x", padx=20, pady=(12, 0))
        self.btn_all = secondary_button(self.btn_frame, tr("playlist.select_all"), self.select_all, width=100,
                                        height=32)
        self.btn_all.pack(side="left")
        self.btn_none = secondary_button(self.btn_frame, tr("playlist.select_none"), self.select_none, width=100,
                                         height=32)
        self.btn_none.pack(side="left", padx=(8, 0))
        self.lbl_count = ctk.CTkLabel(self.btn_frame, text="", font=font(12, "bold"), text_color=MUTED)
        self.lbl_count.pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=12, border_width=1,
                                             border_color=CARD_BORDER)
        self.scroll.pack(pady=12, padx=20, fill="both", expand=True)

        self.bottom = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom.pack(fill="x", padx=20, pady=(0, 18))
        self.btn_cancel = secondary_button(self.bottom, tr("action.cancel"), self.cancel, width=110, height=40)
        self.btn_cancel.pack(side="right", padx=(8, 0))
        self.btn_confirm = primary_button(self.bottom, tr("playlist.add", count=0), self.confirm_selection, height=40)
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
        self.lbl_count.configure(text=tr("playlist.selected", count=count))
        # An empty selection cannot be confirmed (ISSUES.md #24).
        set_primary_state(self.btn_confirm, "normal" if count else "disabled",
                          text=tr("playlist.add", count=count) if count else tr("playlist.none"))

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

class SettingsView(ctk.CTkFrame):
    """The settings page, shown inside the main window in place of the
    download page: appearance and language, downloads and what happens
    after them, updates, and the keyboard shortcuts.

    The page never scrolls: its cards sit in two columns, each setting on
    one line with a hint under its name. When the window is too short
    (large text on a small screen) the page first hides the hints, then
    tightens the spacing, then leaves out the keyboard shortcuts card.
    Below ``TWO_COLUMNS`` units of width the cards stack in one column.

    Every change applies at once and is saved; ``on_change(name, value)``
    tells the app which setting changed. ``on_back`` returns to the
    download page (also Esc).
    """

    SHORTCUTS = (
        ("Enter", "shortcut.analyze"),
        ("Ctrl+Enter", "shortcut.download"),
        ("Esc", "shortcut.cancel"),
        ("Ctrl+O", "shortcut.folder"),
        ("Ctrl+,", "shortcut.settings"),
    )
    TWO_COLUMNS = 680  # narrowest width (in unscaled units) for two columns
    FRAGMENT_CHOICES = (1, 2, 4, 8, 16)

    def __init__(self, parent, settings, on_change, on_back, on_check_updates=None, update_status=None):
        super().__init__(parent, fg_color="transparent", corner_radius=0)
        self.on_change = on_change
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._hints = []
        self._columns = None
        self.hints_shown = True
        self.shortcuts_shown = True
        self.content_fits = True
        self._spacing = []  # (widget, normal pady, tight pady) for short windows
        self.tight = False
        self._fit_pending = False

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=32, pady=(14, 10))
        self._spacing.append((header, (14, 10), (8, 8)))
        header.grid_columnconfigure(2, weight=1)
        self.btn_back = secondary_button(header, "←  " + tr("settings.back"), on_back, width=100, height=34)
        self.btn_back.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text=tr("settings.title"), font=font(20, "bold"), text_color=TEXT).grid(
            row=0, column=1, sticky="w", padx=16)
        ctk.CTkLabel(header, text=f"{DISPLAY_NAME} {__version__}", font=font(12), text_color=MUTED).grid(
            row=0, column=2, sticky="e", padx=12)
        self.btn_logs = secondary_button(header, tr("settings.logs"), self.open_logs, height=34)
        self.btn_logs.grid(row=0, column=3, sticky="e")

        self.body = body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="new", padx=32, pady=(0, 16))
        # Each column stacks its cards (see _layout).
        self.columns = [ctk.CTkFrame(body, fg_color="transparent") for _ in range(2)]
        for column in self.columns:
            column.grid_columnconfigure(0, weight=1)

        # Appearance
        self.card_look = look = self._section(body, tr("settings.appearance"))
        languages = [i18n.AUTO, *i18n.LANGUAGES]
        self.cmb_language = option_menu(
            look, languages, lambda v: self.on_change("language", v), width=200,
            label=lambda c: tr("settings.language_auto") if c == i18n.AUTO else i18n.LANGUAGES[c])
        self.cmb_language.set(settings.language)
        self._setting_row(look, 1, tr("settings.language"), tr("settings.language_hint"), self.cmb_language)
        self.seg_theme = segmented(look, list(settings_store.THEMES), lambda v: self.on_change("theme", v),
                                   label=lambda v: tr(f"theme.{v}"))
        self.seg_theme.set(settings.theme)
        self._setting_row(look, 3, tr("settings.theme"), tr("settings.theme_hint"), self.seg_theme)
        self.seg_text = segmented(look, list(settings_store.TEXT_SIZES), lambda v: self.on_change("text_size", v),
                                  label=lambda v: tr(f"size.{v}"))
        self.seg_text.set(settings.text_size)
        self._setting_row(look, 5, tr("settings.text_size"), tr("settings.text_size_hint"), self.seg_text)
        self.cmb_accent = option_menu(look, list(settings_store.ACCENTS), lambda v: self.on_change("accent", v),
                                      width=200, label=lambda a: tr(f"accent.{a}"))
        self.cmb_accent.set(settings.accent)
        self._setting_row(look, 7, tr("settings.accent"), tr("settings.accent_hint"), self.cmb_accent, last=True)

        # Downloads, and what happens after them
        self.card_finish = after = self._section(body, tr("settings.downloads"))
        self.cmb_fragments = option_menu(after, list(self.FRAGMENT_CHOICES),
                                         lambda v: self.on_change("fragments", v), width=80, label=str)
        self.cmb_fragments.set(settings.fragments if settings.fragments in self.FRAGMENT_CHOICES else 4)
        self._setting_row(after, 1, tr("settings.fragments"), tr("settings.fragments_hint"), self.cmb_fragments)
        self.sw_auto_paste = self._switch(after, 3, tr("settings.auto_paste"), settings.auto_paste, "auto_paste")
        self.sw_awake = self._switch(after, 4, tr("settings.keep_awake"), settings.keep_awake, "keep_awake")
        self.sw_history = self._switch(after, 5, tr("settings.save_history"), settings.save_history,
                                       "save_history")
        self.sw_summary = self._switch(after, 6, tr("settings.summary"), settings.show_summary, "show_summary")
        self.sw_open = self._switch(after, 7, tr("settings.open_folder"), settings.open_folder_when_done,
                                    "open_folder_when_done")
        self._spacing[-1] = (self.sw_open, (0, 14), (0, 10))

        # Updates
        self.card_updates = upd = self._section(body, tr("settings.updates"))
        self.sw_updates = self._switch(upd, 1, tr("settings.check_updates"), settings.check_updates,
                                       "check_updates")
        row = ctk.CTkFrame(upd, fg_color="transparent")
        row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16)
        self._spacing.append((row, (0, 10), (0, 8)))
        self.btn_check = secondary_button(row, tr("settings.check_now"), on_check_updates or (lambda: None),
                                          height=32)
        self.btn_check.pack(side="left", padx=(0, 8))
        self.btn_whats_new = secondary_button(row, tr("settings.whats_new"), self.open_whats_new, height=32)
        self.btn_whats_new.pack(side="left")
        self.lbl_update = ctk.CTkLabel(upd, text="", font=font(12), text_color=MUTED, anchor="w", justify="left")
        self.lbl_update.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 12))
        self.show_update_status(update_status)

        # Keyboard
        self.card_keys = keys = self._section(body, tr("settings.shortcuts"))
        keys.grid_columnconfigure(1, weight=1)
        for i, (key, action) in enumerate(self.SHORTCUTS, start=1):
            last = i == len(self.SHORTCUTS)
            chip = ctk.CTkLabel(keys, text=key, font=font(12, "bold"), text_color=TEXT, fg_color=FIELD,
                                corner_radius=6, width=88, height=24)
            chip.grid(row=i, column=0, sticky="w", padx=(16, 10))
            text = ctk.CTkLabel(keys, text=tr(action), font=font(12), text_color=TEXT, anchor="w", justify="left",
                                height=24)
            text.grid(row=i, column=1, sticky="ew", padx=(0, 16))
            for widget in (chip, text):
                self._spacing.append((widget, (0, 14 if last else 6), (0, 10 if last else 3)))
        self.card_keys.grid_columnconfigure(0, weight=0)

        self._set_tight(False)
        # The frame's own resize event (CTkFrame.bind would bind its canvas).
        tkinter.Misc.bind(self, "<Configure>", self._schedule_fit, "+")

    def _section(self, parent, title):
        frame = card(parent)
        frame.grid_columnconfigure(0, weight=1)
        label = ctk.CTkLabel(frame, text=title, font=font(15, "bold"), text_color=TEXT, anchor="w")
        label.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16)
        self._spacing.append((label, (12, 8), (8, 4)))
        return frame

    def _setting_row(self, parent, row, title, hint, widget, last=False):
        """A setting on one line, its name left and ``widget`` right, with a hint under both."""
        name = ctk.CTkLabel(parent, text=title, font=font(13, "bold"), text_color=TEXT, anchor="w",
                            justify="left")
        name.grid(row=row, column=0, sticky="ew", padx=(16, 8))
        widget.grid(row=row, column=1, sticky="e", padx=(0, 16))
        label = ctk.CTkLabel(parent, text=hint, font=font(12), text_color=MUTED, anchor="w", justify="left",
                             wraplength=300)
        # Hints are not in _spacing: grid_configure would show a hidden hint again.
        label.grid(row=row + 1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 12 if last else 8))
        self._hints.append(label)
        for w in (name, widget):
            self._spacing.append((w, (0, 4), (0, 10 if last else 6)))
        if not getattr(parent, "_wraps_hints", False):
            parent._wraps_hints = True
            tkinter.Misc.bind(parent, "<Configure>", lambda _e: self._wrap_hints(parent), "+")

    def _wrap_hints(self, parent):
        """Long hints wrap at the card's width."""
        try:
            width = parent.winfo_width() / ctk.ScalingTracker.get_widget_scaling(self) - 36
            for label in self._hints:
                if label.master is parent and abs(label.cget("wraplength") - width) > 2:
                    label.configure(wraplength=max(120, width))
        except tkinter.TclError:
            pass

    def _switch(self, parent, row, text, value, name):
        widget = switch(parent, text, lambda: self.on_change(name, bool(widget.get())))
        if value:
            widget.select()
        widget.grid(row=row, column=0, columnspan=2, sticky="w", padx=16)
        self._spacing.append((widget, (0, 10), (0, 6)))
        return widget

    def _layout(self, columns):
        """Place the cards in one column or two."""
        self._columns = columns
        body = self.body
        body.grid_columnconfigure(0, weight=1, uniform="col")
        body.grid_columnconfigure(1, weight=1 if columns == 2 else 0, uniform="col" if columns == 2 else "")
        left, right = self.columns
        if columns == 2:
            left.grid(row=0, column=0, columnspan=1, sticky="new", padx=(0, 8))
            right.grid(row=0, column=1, sticky="new", padx=(8, 0))
            order = ((self.card_look, left), (self.card_updates, left), (self.card_finish, right),
                     (self.card_keys, right))
        else:
            left.grid(row=0, column=0, columnspan=2, sticky="new", padx=0)
            right.grid_remove()
            order = ((self.card_look, left), (self.card_finish, left), (self.card_updates, left),
                     (self.card_keys, left))
        rows = {}
        for widget, column in order:
            row = rows.get(column, 0)
            rows[column] = row + 1
            widget.grid(in_=column, row=row, column=0, sticky="ew", pady=(0 if row == 0 else 12, 0))
        if not self.shortcuts_shown:
            self.card_keys.grid_remove()

    def _set_tight(self, tight):
        self.tight = tight
        for widget, normal, small in self._spacing:
            widget.grid_configure(pady=small if tight else normal)

    def _show_hints(self, show):
        self.hints_shown = show
        for label in self._hints:
            label.grid() if show else label.grid_remove()

    def _show_shortcuts(self, show):
        self.shortcuts_shown = show
        self.card_keys.grid() if show else self.card_keys.grid_remove()

    def _schedule_fit(self, _event=None):
        if not self._fit_pending:
            self._fit_pending = True
            self.after_idle(self._fit)

    FIT_STEPS = ((True, False, True), (False, False, True), (False, True, True), (False, True, False))

    def _fit(self):
        """Choose the columns for the width, then the roomiest layout that fits:
        hints and normal spacing, no hints, tight spacing, then no shortcuts card."""
        self._fit_pending = False
        try:
            scale = ctk.ScalingTracker.get_widget_scaling(self)
            columns = 2 if self.winfo_width() / scale >= self.TWO_COLUMNS else 1
            if columns != self._columns:
                self._layout(columns)
            self.update_idletasks()
            available = self.winfo_height()
            for hints, tight, shortcuts in self.FIT_STEPS:
                if (hints, tight, shortcuts) != (self.hints_shown, self.tight, self.shortcuts_shown):
                    self._show_hints(hints)
                    self._set_tight(tight)
                    self._show_shortcuts(shortcuts)
                    self.update_idletasks()
                need = self.winfo_reqheight()
                if need <= available + 1:
                    break
            self.content_fits = need <= available + 1
        except tkinter.TclError:
            pass  # page closed

    def open_logs(self):
        open_path(app_setup.data_dir())

    def show_update_status(self, text):
        """``text`` is a function giving the (translated) result of the last check, or None."""
        try:
            self.lbl_update.configure(text=text() if text else "")
            self.lbl_update.grid() if text else self.lbl_update.grid_remove()
        except tkinter.TclError:
            return
        self._schedule_fit()

    @staticmethod
    def open_whats_new():
        webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/tag/{updates.TAG_PREFIX}{__version__}")


def open_file(path):
    """Open ``path`` with its default app."""
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


def show_in_folder(path):
    """Show the folder of ``path`` with the file selected (Explorer), or just the folder."""
    if sys.platform == "win32" and os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        open_path(os.path.dirname(path) or ".")


class HistoryView(ctk.CTkFrame):
    """The History page: recent downloads with Open, Folder and Remove.

    Shown inside the main window in place of the download page, like the
    settings page. At most ``SHOWN`` entries are drawn, newest first.
    """

    SHOWN = 100

    def __init__(self, parent, history, on_back):
        super().__init__(parent, fg_color="transparent", corner_radius=0)
        self.history = history
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=32, pady=(14, 10))
        header.grid_columnconfigure(2, weight=1)
        self.btn_back = secondary_button(header, "\u2190  " + tr("settings.back"), on_back, width=100, height=34)
        self.btn_back.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text=tr("history.title"), font=font(20, "bold"), text_color=TEXT).grid(
            row=0, column=1, sticky="w", padx=16)
        self.btn_clear = secondary_button(header, tr("history.clear"), self.clear, height=34)
        self.btn_clear.grid(row=0, column=3, sticky="e")
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.list.grid(row=1, column=0, sticky="nsew", padx=(32, 16), pady=(0, 16))
        self.list.grid_columnconfigure(0, weight=1)
        self.rows = []
        self.refresh()

    def refresh(self):
        for row in self.rows:
            row.destroy()
        self.rows = []
        entries = self.history.entries[:self.SHOWN]
        self.btn_clear.configure(state="normal" if entries else "disabled")
        if not entries:
            empty = ctk.CTkLabel(self.list, text=tr("history.empty"), font=font(13), text_color=MUTED)
            empty.grid(row=0, column=0, pady=40)
            self.rows.append(empty)
            return
        for i, entry in enumerate(entries):
            self.rows.append(self._row(i, entry))

    def _row(self, index, entry):
        row = card(self.list)
        row.grid(row=index, column=0, sticky="ew", pady=(0, 8), padx=(0, 16))
        row.grid_columnconfigure(0, weight=1)
        exists = os.path.exists(entry.path)
        ctk.CTkLabel(row, text=entry.title or os.path.basename(entry.path), font=font(13, "bold"),
                     text_color=TEXT if exists else MUTED, anchor="w", justify="left").grid(
            row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.time)) if entry.time else ""
        parts = [p for p in (when, tr(MODE_KEYS[entry.mode]) if entry.mode in MODE_KEYS else "") if p]
        parts.append(shorten_path(entry.path, 70) if exists else tr("history.missing"))
        ctk.CTkLabel(row, text="  \u00b7  ".join(parts), font=font(12), text_color=MUTED, anchor="w",
                     justify="left").grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        buttons = ctk.CTkFrame(row, fg_color="transparent")
        buttons.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 12))
        state = "normal" if exists else "disabled"
        secondary_button(buttons, tr("history.open"), lambda: self._run(open_file, entry.path), height=30,
                         width=70, state=state).pack(side="left", padx=(0, 6))
        secondary_button(buttons, tr("history.folder"), lambda: self._run(show_in_folder, entry.path), height=30,
                         width=70, state=state).pack(side="left", padx=(0, 6))
        secondary_button(buttons, tr("history.remove"), lambda: self.remove(entry.path), height=30,
                         width=70).pack(side="left")
        return row

    def _run(self, action, path):
        try:
            action(path)
        except OSError as e:
            messagebox.showerror(tr("history.title"), str(e), parent=self)

    def remove(self, path):
        self.history.remove(path)
        self.refresh()

    def clear(self):
        if messagebox.askyesno(tr("history.title"), tr("history.clear_confirm"), parent=self):
            self.history.clear()
            self.refresh()


class UpdateDialog(ctk.CTkToplevel):
    """Offers a newer release: its notes, then download, verify and install.

    The download runs on a worker thread that posts UPDATE_* events; the
    app forwards them to :meth:`show_progress`, :meth:`show_error`. Where
    the app cannot install (not the installed Windows app), the button
    opens the release page instead.
    """

    def __init__(self, app, release, can_install):
        super().__init__(app)
        self.app, self.release, self.can_install = app, release, can_install
        self.title(tr("update.title"))
        self.configure(fg_color=BG)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.later)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=tr("update.available", version=release.version), font=font(17, "bold"),
                     text_color=TEXT, anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        notes = ctk.CTkTextbox(self, font=font(12), fg_color=CARD, text_color=TEXT, wrap="word", height=200,
                               border_width=1, border_color=CARD_BORDER)
        notes.insert("1.0", updates.notes_summary(release.notes) or release.page)
        notes.configure(state="disabled")
        notes.grid(row=1, column=0, sticky="nsew", padx=20)
        self.lbl_note = ctk.CTkLabel(self, text=tr("update.restart_note") if can_install else "", font=font(12),
                                     text_color=MUTED, anchor="w", justify="left")
        self.lbl_note.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.progress = ctk.CTkProgressBar(self, height=8, progress_color=ACCENT, fg_color=SECONDARY)
        self.progress.set(0)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, sticky="e", padx=20, pady=(12, 18))
        self.btn_page = secondary_button(buttons, tr("update.page"), lambda: webbrowser.open(release.page))
        if can_install:  # otherwise the main button opens the page
            self.btn_page.pack(side="left", padx=(0, 8))
        self.btn_later = secondary_button(buttons, tr("update.later"), self.later)
        self.btn_later.pack(side="left", padx=(0, 8))
        self.btn_install = primary_button(buttons, tr("update.install") if can_install else tr("update.page"),
                                          self.install)
        self.btn_install.pack(side="left")
        set_window_icon(self)
        self.after(200, lambda: set_window_icon(self))
        fit_dialog(self, (560, 440), (420, 320))
        self.lift()
        self.btn_install.focus_set()

    def install(self):
        if not self.can_install:
            webbrowser.open(self.release.page)
            self.later()
            return
        if not self.app.start_update(self.release):
            return
        set_primary_state(self.btn_install, "disabled")
        self.btn_page.configure(state="disabled")
        self.progress.grid(row=3, column=0, sticky="ew", padx=20, pady=(10, 0))
        self.show_progress(0, 0)

    def show_progress(self, done, total):
        if total:
            self.progress.set(done / total)
            text = tr("update.downloading", percent=int(done * 100 / total))
        else:
            text = tr("update.downloading", percent=0)
        self.lbl_note.configure(text=text, text_color=MUTED)

    def show_error(self, error):
        self.lbl_note.configure(text=tr("update.error", error=error), text_color=DANGER)
        self.progress.grid_remove()
        set_primary_state(self.btn_install, "normal")
        self.btn_page.configure(state="normal")

    def later(self):
        self.app.cancel_update()
        self.app.update_dialog = None
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

    def __init__(self, instance=None):
        super().__init__()
        # app_setup.SingleInstance held by main(); released before an update installs.
        self.instance = instance
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
        i18n.set_language(self.settings.language)
        apply_accent(self.settings.accent)
        self.history = download_history.History(os.path.join(app_setup.data_dir(), "history.json"))
        self._job_mode = None
        # Widgets whose text is translated: (widget, option) -> function giving
        # the text, re-run when the language changes (see _live).
        self._texts = {}

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
        self.events.register(events.UPDATE_CHECKED, self._on_update_checked)
        self.events.register(events.UPDATE_PROGRESS, self._on_update_progress)
        self.events.register(events.UPDATE_READY, self._on_update_ready)
        self.events.register(events.UPDATE_FAILED, self._on_update_failed)
        self.available_update = None   # updates.Release newer than this version
        self.update_dialog = None
        self._update_status = None     # function giving the last check's result text
        self._update_cancel = threading.Event()
        self._update_thread = None
        self.last_summary = None
        self.playlist_dialog = None
        self._pending_skipped = []
        self.skipped_items = []
        self._poll_id = None
        self.tools = None

        self.settings_view = None
        self.history_view = None
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
        self._note_version_change()
        self._startup_calls = []  # cancelled if the window closes first
        if self.settings.auto_paste:
            self._startup_calls.append(self.after(350, self.auto_paste))
        if self.settings.check_updates:
            self._startup_calls.append(self.after(1500, self.check_for_updates))

    POLL_INTERVAL_MS = 50

    def _poll_events(self):
        """Drain the event queue on the main thread, then reschedule."""
        try:
            self.events.dispatch_pending()
        finally:
            self._poll_id = self.after(self.POLL_INTERVAL_MS, self._poll_events)

    def destroy(self):
        for call in getattr(self, "_startup_calls", ()):
            try:
                self.after_cancel(call)
            except Exception:
                pass
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
        ctk.CTkLabel(brand, text=DISPLAY_NAME, font=font(17, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(brand, text=f"v{__version__}", font=font(12), text_color=MUTED).pack(side="left", padx=(8, 0))

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=(0, 24), pady=12)
        status = ctk.CTkFrame(right, fg_color=FIELD, corner_radius=16)
        status.pack(side="left", padx=(0, 12))
        self.lbl_status_dot = ctk.CTkLabel(status, text="\u25cf", font=font(13), text_color=MUTED, width=14)
        self.lbl_status_dot.pack(side="left", padx=(12, 4), pady=4)
        self.lbl_status = ctk.CTkLabel(status, text="", font=font(12), text_color=MUTED)
        self._live(self.lbl_status, lambda: tr("top.ffmpeg_checking"))
        self.lbl_status.pack(side="left", padx=(0, 14), pady=4)
        # Shown once a newer version is found.
        self.btn_update = primary_button(right, "", self.show_update_dialog, height=36)
        self.btn_history = secondary_button(right, "", self.toggle_history, width=110, height=36)
        self._live(self.btn_history, lambda: "\u23f2  " + tr("top.history"))
        self.btn_history.pack(side="left", padx=(0, 8))
        self.btn_settings = secondary_button(right, "", self.toggle_settings, width=120, height=36)
        self._live(self.btn_settings, lambda: "\u2699  " + tr("top.settings"))
        self.btn_settings.pack(side="left")
        self._refresh_logo_bg()

    def _section_label(self, parent, key):
        label = section_label(parent, "")
        self._live(label, lambda: tr(key))
        return label

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
        self.btn_paste = secondary_button(url_card, "", self.paste_url, width=80, height=44)
        self._live(self.btn_paste, lambda: tr("link.paste"))
        self.btn_paste.grid(row=0, column=1, padx=(0, 8), pady=16)
        self.btn_analyze = primary_button(url_card, "", self.start_analysis_thread, width=120, height=44,
                                          font=font(14, "bold"))
        self._live(self.btn_analyze, lambda: tr("link.analyze"))
        self.btn_analyze.grid(row=0, column=2, padx=(0, 16), pady=16)
        self.lbl_media = ctk.CTkLabel(url_card, text="", font=font(13), text_color=MUTED,
                                      anchor="w", justify="left")
        self.lbl_media.grid(row=1, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 14))
        self._show_media(lambda: tr("link.hint"), MUTED)

        # Options
        opt_card = card(self.main_frame)
        opt_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        opt_card.grid_columnconfigure((1, 3), weight=1)
        self._section_label(opt_card, "options.mode").grid(row=0, column=0, sticky="w", padx=(16, 12), pady=(16, 8))
        self.cmb_mode = segmented(opt_card, list(formats.MODES), self._on_mode_changed,
                                  label=lambda m: tr(MODE_KEYS[m]))
        self.cmb_mode.grid(row=0, column=1, columnspan=3, sticky="w", pady=(16, 8))
        self._section_label(opt_card, "options.format").grid(row=1, column=0, sticky="w", padx=(16, 12), pady=8)
        self.cmb_format = option_menu(opt_card, ["mp4"], lambda _v: self._save_settings(), width=150)
        self.cmb_format.grid(row=1, column=1, sticky="w", pady=8)
        self._section_label(opt_card, "options.quality").grid(row=1, column=2, sticky="w", padx=(16, 12), pady=8)
        self.cmb_quality = option_menu(opt_card, ["Best"], lambda _v: self._save_settings(), width=170,
                                       label=lambda q: tr("quality.best") if q == "Best" else q)
        self.cmb_quality.grid(row=1, column=3, sticky="w", pady=8)

        self._section_label(opt_card, "options.trim").grid(row=2, column=0, sticky="w", padx=(16, 12), pady=(8, 12))
        trim_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        trim_row.grid(row=2, column=1, columnspan=3, sticky="w", pady=(8, 12))
        self.chk_trim = switch(trim_row, "", self.toggle_trim)
        self._live(self.chk_trim, lambda: tr("trim.switch"))
        self.chk_trim.grid(row=0, column=0, padx=(0, 16))
        self.ent_start = ctk.CTkEntry(trim_row, width=110, height=32, fg_color=FIELD, border_width=0)
        self._live(self.ent_start, lambda: tr("trim.start"), "placeholder_text")
        self.ent_start.grid(row=0, column=1, padx=(0, 6))
        lbl_to = ctk.CTkLabel(trim_row, text="", text_color=MUTED, font=font(13))
        lbl_to.grid(row=0, column=2, padx=4)
        self._live(lbl_to, lambda: tr("trim.to"))
        self.ent_end = ctk.CTkEntry(trim_row, width=110, height=32, fg_color=FIELD, border_width=0)
        self._live(self.ent_end, lambda: tr("trim.end"), "placeholder_text")
        self.ent_end.grid(row=0, column=3, padx=(6, 12))
        self.lbl_trim_hint = ctk.CTkLabel(trim_row, text="", text_color=MUTED, font=font(12))
        self._live(self.lbl_trim_hint, lambda: tr("trim.hint"))
        self.lbl_trim_hint.grid(row=0, column=4)
        self.toggle_trim()

        ctk.CTkFrame(opt_card, height=1, corner_radius=0, fg_color=CARD_BORDER).grid(row=3, column=0, columnspan=4, sticky="ew",
                                                                    padx=16)
        self._section_label(opt_card, "options.save_to").grid(row=4, column=0, sticky="w", padx=(16, 12), pady=12)
        folder_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        folder_row.grid(row=4, column=1, columnspan=3, sticky="ew", padx=(0, 16), pady=12)
        folder_row.grid_columnconfigure(0, weight=1)
        self.lbl_folder = ctk.CTkLabel(folder_row, text="", font=font(13), text_color=TEXT, fg_color=FIELD,
                                       corner_radius=8, height=36, anchor="w")
        self.lbl_folder.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.lbl_folder.bind("<Double-Button-1>", lambda _e: self.open_folder())
        self.btn_dest = secondary_button(folder_row, "", self.select_folder, width=100)
        self._live(self.btn_dest, lambda: tr("folder.change"))
        self.btn_dest.grid(row=0, column=1, padx=(0, 8))
        self.btn_open = secondary_button(folder_row, "", self.open_folder, width=80)
        self._live(self.btn_open, lambda: tr("folder.open"))
        self.btn_open.grid(row=0, column=2)
        self._show_folder()

        # Actions
        actions = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        actions.grid_columnconfigure(0, weight=1)
        self.btn_download = primary_button(actions, "", self.start_download_queue, height=48,
                                           corner_radius=10, font=font(16, "bold"))
        set_primary_state(self.btn_download, "disabled")
        self._live(self.btn_download, lambda: tr("action.download"))
        self.btn_download.grid(row=0, column=0, sticky="ew")
        self.btn_cancel = secondary_button(actions, "", self.cancel_job, width=110, height=48, state="disabled")
        self._live(self.btn_cancel, lambda: tr("action.cancel"))
        self.btn_cancel.grid(row=0, column=1, padx=(10, 0))
        self.btn_retry = secondary_button(actions, "", self.retry_failed, width=140, height=48, state="disabled")
        self._live(self.btn_retry, lambda: tr("action.retry"))
        self.btn_retry.grid(row=0, column=2, padx=(10, 0))

        # Progress
        prog_card = card(self.main_frame)
        prog_card.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        prog_card.grid_columnconfigure(0, weight=1)
        self.lbl_item = ctk.CTkLabel(prog_card, text="", font=font(13, "bold"), text_color=TEXT, anchor="w")
        self._live(self.lbl_item, lambda: tr("progress.ready"))
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
        self._section_label(log_card, "activity.title").grid(row=0, column=0, sticky="w", padx=16, pady=(12, 4))
        self.console = ctk.CTkTextbox(log_card, height=100, font=ctk.CTkFont(family="Consolas", size=12),
                                      fg_color="transparent", text_color=TEXT, wrap="word")
        self.console.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        # Keep a gap between the cards and the (usually hidden) scrollbar.
        for card_widget in self.main_frame.grid_slaves():
            card_widget.grid_configure(padx=(0, 16))
        self._scroll_canvas.bind("<Configure>", lambda _e: self.after_idle(self._fill_height), add="+")
        self.log(tr("activity.welcome"))

    # --- small UI helpers ---------------------------------------------------

    def _live(self, widget, text, option="text"):
        """Show ``text()`` on ``widget`` now and again after a language change."""
        self._texts[(widget, option)] = text
        widget.configure(**{option: text()})

    def _show_media(self, text, color):
        """The line under the link field: a hint, what was found, or an error."""
        self.lbl_media.configure(text_color=color)
        self._live(self.lbl_media, text)

    def _apply_language(self):
        """Redraw every translated text in the current language."""
        for (widget, option), text in list(self._texts.items()):
            try:
                widget.configure(**{option: text()})
            except tkinter.TclError:
                del self._texts[(widget, option)]  # widget gone
        for choice in (self.cmb_mode, self.cmb_quality):
            choice.relabel()
        if self.settings_view is not None:
            # Rebuilt after the language menu's own callback has returned.
            self.after_idle(self._rebuild_settings_view)
        if self.available_update is not None:
            self._show_update_button()

    def log(self, message):
        """Queue a console line; safe to call from any thread."""
        self.events.post(events.LOG, message=message)
    def _append_log(self, message):
        self.console.insert("end", f"> {message}\n")
        self.console.see("end")
    def _show_progress(self, fraction, text, detail=""):
        """``text`` and ``detail`` are strings, or functions for translated text."""
        self.progress_bar.set(fraction)
        self._live(self.lbl_progress, text if callable(text) else (lambda: text))
        self._live(self.lbl_detail, detail if callable(detail) else (lambda: detail))
    def _show_stage(self, text):
        self._live(self.lbl_detail, lambda: i18n.tr_message(text))
    def _on_item_started(self, position, total, title):
        if total > 1:
            self._live(self.lbl_item, lambda: tr("progress.item", position=position, total=total, title=title))
        else:
            self._live(self.lbl_item, lambda: title)
        self.progress_bar.configure(progress_color=ACCENT)
        self._show_progress(0, lambda: tr("progress.starting"))
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
        """Called by the settings page; applies and saves one setting."""
        if name == "theme":
            self._on_theme_changed(value)
            return
        setattr(self.settings, name, value)
        if name == "accent":
            recolor(self, apply_accent(value))
        elif name == "text_size":
            ctk.set_widget_scaling(settings_store.TEXT_SIZES[value])
            self.after(50, self._fit_to_content)
        elif name == "language":
            i18n.set_language(value)
            self._apply_language()
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
        """Show the settings page in place of the download page."""
        if self.settings_view is not None:
            return
        self.close_history()
        self._build_settings_view()
        self.main_frame.grid_remove()
        self.settings_view.btn_back.focus_set()
    def toggle_settings(self):
        if self.settings_view is None:
            self.open_settings()
        else:
            self.close_settings()
    def _rebuild_settings_view(self):
        if self.settings_view is not None:
            self._build_settings_view()
            self.settings_view.cmb_language.focus_set()
    def _build_settings_view(self):
        if self.settings_view is not None:
            self.settings_view.destroy()
        self.settings_view = SettingsView(self, self.settings, self._on_setting_changed, self.close_settings,
                                          on_check_updates=lambda: self.check_for_updates(manual=True),
                                          update_status=self._update_status)
        self.settings_view.grid(row=1, column=0, sticky="nsew")
    def close_settings(self):
        """Back to the download page."""
        if self.settings_view is None:
            return
        self.settings_view.destroy()
        self.settings_view = None
        self.main_frame.grid()
        self.after_idle(self._fill_height)
    def open_history(self):
        """Show the History page in place of the download page."""
        if self.history_view is not None:
            return
        self.close_settings()
        self.history_view = HistoryView(self, self.history, self.close_history)
        self.history_view.grid(row=1, column=0, sticky="nsew")
        self.main_frame.grid_remove()
        self.history_view.btn_back.focus_set()

    def toggle_history(self):
        if self.history_view is None:
            self.open_history()
        else:
            self.close_history()

    def close_history(self):
        if self.history_view is None:
            return
        self.history_view.destroy()
        self.history_view = None
        self.main_frame.grid()
        self.after_idle(self._fill_height)

    def _on_escape(self):
        if self.settings_view is not None:
            self.close_settings()
        elif self.history_view is not None:
            self.close_history()
        else:
            self.cancel_job()
    def _bind_shortcuts(self):
        self.bind("<Control-Return>", lambda _e: self._shortcut(self.start_download_queue, self.btn_download))
        self.bind("<Escape>", lambda _e: self._on_escape())
        self.bind("<Control-o>", lambda _e: self._shortcut(self.select_folder, self.btn_dest))
        self.bind("<Control-comma>", lambda _e: self.open_settings())
        # The link field's own Enter binding would otherwise also run.
        self.url_entry.bind("<Control-Return>",
                            lambda _e: self._shortcut(self.start_download_queue, self.btn_download))
        self.after(300, self.url_entry.focus_set)
    def _shortcut(self, action, button):
        # A shortcut does what its button does, and only when it is enabled
        # and on screen.
        if self.settings_view is None and self.history_view is None and button.cget("state") == "normal":
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
        self.cmb_format.set_choices(choices)
        if self.cmb_format.get() not in choices:
            self.cmb_format.set(choices[0])
        qualities = formats.qualities_for_mode(mode)
        self.cmb_quality.set_choices(qualities)
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
            self._append_log(tr("log.folder", folder=self.download_folder))
    def open_folder(self):
        folder = self.download_folder
        try:
            open_path(folder)
        except OSError as e:
            self._append_log(f"Could not open {folder}: {e}")
    def auto_paste(self):
        """Put a link from the clipboard into the empty link field (Settings: auto-paste)."""
        if self._job_kind == "setup":
            # The field is disabled until the FFmpeg check at start is done.
            self._startup_calls.append(self.after(200, self.auto_paste))
            return
        if self.is_busy() or self.url_entry.get().strip():
            return
        try:
            text = self.clipboard_get().strip()
        except tkinter.TclError:
            return
        if not text.lower().startswith(("http://", "https://")) or len(text) > 2000:
            return
        try:
            url = urls.normalize_url(text)
        except urls.UrlError:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        self._append_log(tr("log.auto_paste"))

    def paste_url(self):
        try:
            text = self.clipboard_get().strip()
        except tkinter.TclError:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)
        self._on_url_changed()
    def _set_status(self, text, color):
        """``text`` is a function returning the (translated) status text."""
        self.lbl_status.configure(text_color=color)
        self._live(self.lbl_status, text)
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
        if kind == "download" and self.settings.keep_awake:
            app_setup.keep_awake(True)
        self._job_thread = threading.Thread(target=target, args=args, name=f"uvd-{kind}", daemon=True)
        self._job_thread.start()
        return True

    def _end_job(self):
        if self._job_kind == "download":
            app_setup.keep_awake(False)
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
        self.btn_cancel.configure(state="normal" if busy and self._job_kind == "download" else "disabled")
        self._live(self.btn_cancel, lambda: tr("action.cancel"))
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
            set_primary_state(self.btn_download, "disabled")
            self._live(self.btn_download, lambda: tr("top.ffmpeg_missing"))
        else:
            set_primary_state(self.btn_download, "normal" if count else "disabled")
            self._live(self.btn_download,
                       lambda: tr("action.download_n", count=count) if count > 1 else tr("action.download"))

    def _failed_items(self):
        if self.last_summary is None:
            return []
        return [r.source or {'url': r.url, 'title': r.title}
                for r in self.last_summary.with_status(ItemStatus.FAILED)]

    def _refresh_retry_button(self):
        count = len(self._failed_items())
        self.btn_retry.configure(state="normal" if count else "disabled")
        self._live(self.btn_retry, lambda: tr("action.retry_n", count=count) if count else tr("action.retry"))

    def cancel_job(self):
        """Ask the running download to stop; results arrive via job_done."""
        if self._job_kind != "download" or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.btn_cancel.configure(state="disabled")
        self._live(self.btn_cancel, lambda: tr("action.cancelling"))
        self._append_log(tr("action.cancelling"))

    def retry_failed(self):
        items = self._failed_items()
        if not items or self.is_busy():
            return
        self._append_log(tr("log.retrying", count=len(items)))
        self.download_queue = items
        self.skipped_items = []
        self.start_download_queue()

    CLOSE_TIMEOUT_MS = 15000

    def on_close(self):
        """Window close: confirm, cancel a running download, wait, then exit."""
        if self._closing:
            return
        if self._job_kind == "download":
            if not messagebox.askyesno(tr("quit.title"), tr("quit.body"), parent=self):
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
        except urls.UrlError as e:
            # Rejected before any network request (ISSUES.md #32).
            key, values = e.key, e.values  # ``e`` is unbound after the except block
            self._show_media(lambda: tr(key, **values), DANGER)
            return
        if url != self.url_entry.get().strip():
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
        # A new analysis invalidates the previous queue and progress.
        self.analyzed_url = None
        self.set_queue([])
        self._show_progress(0, "0%")
        self._live(self.lbl_item, lambda: tr("progress.ready"))
        if self._start_job("analysis", self.run_analysis, url):
            self._live(self.btn_analyze, lambda: tr("link.checking"))
            self._show_media(lambda: tr("link.reading"), MUTED)
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
            version = status.version.split('-')[0]
            self._set_status(lambda: tr("top.ffmpeg_ready", version=version), SUCCESS)
        else:
            self._set_status(lambda: tr("top.ffmpeg_missing"), DANGER)
            messagebox.showerror(tr("top.ffmpeg_missing"), tr("ffmpeg.body", error=status.error), parent=self)
    def run_analysis(self, url):
        """Worker thread: fetch info and post the result; no widget access."""
        try:
            self.log(tr("log.fetching"))
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
        self._live(self.btn_analyze, lambda: tr("link.analyze"))
        self._show_media(lambda: message, DANGER)
        self._end_job()
    def _on_analysis_done(self, analysis, url):
        self._live(self.btn_analyze, lambda: tr("link.analyze"))
        self._end_job()
        self._describe_analysis(analysis)
        for item in analysis.skipped:
            self._append_log(tr("log.skipped_entry", title=item.title, reason=i18n.tr_message(item.skip_reason)))
        if not analysis.items:
            message = tr("link.nothing")
            if analysis.skipped:
                message = tr("link.nothing_reason", reason=i18n.tr_message(analysis.skipped[0].skip_reason))
            self._append_log(message)
            messagebox.showwarning(tr("link.nothing_title"), message, parent=self)
            return
        if analysis.is_playlist:
            self._append_log(tr("log.playlist", title=analysis.title, count=len(analysis.items),
                                skipped=len(analysis.skipped)))
            self._pending_skipped = [item.as_dict() for item in analysis.skipped]
            self.playlist_dialog = PlaylistSelector(
                self, analysis, lambda items: self._on_playlist_selected(url, items))
        else:
            self._append_log(tr("log.video", title=analysis.title))
            self.analyzed_url = url
            self.set_queue([item.as_dict() for item in analysis.items])
    def _describe_analysis(self, analysis):
        title = analysis.title
        if not analysis.items:
            self._show_media(lambda: tr("link.nothing_short", title=title), WARNING)
            return
        count, skipped = len(analysis.items), len(analysis.skipped)
        duration = analysis.items[0].duration

        def text():
            if analysis.is_playlist:
                parts = [tr("media.playlist"), tr("media.videos", count=count)]
                if skipped:
                    parts.append(tr("media.unavailable", count=skipped))
            else:
                parts = [tr("media.video")] + ([format_duration(duration)] if duration else [])
            return f"{title}\n" + "  \u00b7  ".join(parts)
        self._show_media(text, TEXT)
    def _on_playlist_selected(self, url, items):
        self.playlist_dialog = None
        if items is None:
            self._append_log(tr("log.selection_cancelled"))
            return
        if self.url_entry.get().strip() != url:
            self._append_log(tr("link.changed"))
            return
        self.analyzed_url = url
        self.set_queue([item.as_dict() for item in items], skipped=self._pending_skipped)
    def set_queue(self, items, skipped=()):
        self.download_queue = list(items)
        # Entries that cannot be downloaded; reported as skipped in the result.
        self.skipped_items = list(skipped) if self.download_queue else []
        if self.download_queue:
            self.log(tr("log.queue", count=len(self.download_queue)))
        if not self.is_busy():
            self._refresh_download_button()
    def start_download_queue(self):
        if not self.download_queue or self.is_busy(): return
        if self.chk_trim.get():
            # Kötü trim değerleriyle kuyruğu hiç başlatma
            try:
                if parse_trim_range(self.ent_start.get(), self.ent_end.get()) is None:
                    raise TrimError(tr("trim.empty"))
            except TrimError as e:
                self.log(f"Trim error: {e}")
                messagebox.showerror(tr("trim.error_title"), str(e), parent=self)
                return
        error, warning = filenames.check_folder(self.download_folder)
        if error:
            self._append_log(error)
            messagebox.showerror(tr("folder.error_title"), error, parent=self)
            return
        if warning:
            self._append_log(f"Warning: {warning}")
        self._show_progress(0, "0%")
        items = list(self.download_queue) + list(self.skipped_items)
        opts = {
            'save_path': self.download_folder, 'mode': self.cmb_mode.get(),
            'format': self.cmb_format.get(), 'quality': self.cmb_quality.get(),
            'trim_start': self.ent_start.get() if self.chk_trim.get() else None,
            'trim_end': self.ent_end.get() if self.chk_trim.get() else None,
            **settings_store.download_speed_options(self.settings),
        }
        self._job_mode = opts['mode']
        if self._start_job("download", self._run_queue_with_cancel, items, opts):
            self._live(self.btn_download, lambda: tr("action.downloading"))
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
        self._append_log(describe_result(result))
        if result.status is ItemStatus.COMPLETED and result.path and self.settings.save_history:
            self.history.add(result.title, result.path, result.url, self._job_mode or "")
    def _on_job_done(self, summary):
        self._append_log(tr("log.result", summary=summary.headline(
            label=lambda status: tr("status." + status.value), nothing=tr("summary.nothing"))))
        self.last_summary = summary
        self._end_job()
        if self._closing:
            return
        def headline():
            return summary.headline(label=lambda status: tr("status." + status.value), nothing=tr("summary.nothing"))
        self._live(self.lbl_item, lambda: f"{tr(summary.title_key())}: {headline()}")
        done = len(summary.with_status(ItemStatus.COMPLETED))
        self.progress_bar.configure(progress_color=SUCCESS if summary.all_ok else WARNING if done else DANGER)
        if summary.all_ok:
            self._show_progress(1, lambda: tr("progress.complete"))
        else:
            self._show_progress(done / len(summary.results) if summary.results else 0, headline)
        if done and self.settings.open_folder_when_done:
            self.open_folder()
        if self.settings.show_summary:
            show = messagebox.showinfo if summary.all_ok else messagebox.showwarning
            report = summary.report(label=lambda status: tr("status." + status.value),
                                    nothing=tr("summary.nothing"), more=tr("summary.more", count="{count}"))
            show(tr(summary.title_key()), report, parent=self)
    def progress_hook(self, d):
        """yt-dlp progress and postprocessor hook; runs on the worker thread."""
        stage = events.stage_from_hook(d)
        if stage is not None:
            self.events.post(events.STAGE, text=stage)
            return
        progress = events.progress_from_hook(d)
        if progress is not None:
            fraction, text = progress
            self.events.post(events.PROGRESS, fraction=fraction, text=text, detail=events.detail_from_hook(d, left=tr("progress.left", time="{time}")))


    # --- updates ------------------------------------------------------------

    def _note_version_change(self):
        """Log once after an update, and remember the version that ran."""
        previous = self.settings.last_version
        if previous != __version__:
            if previous:
                self._append_log(tr("log.updated", version=__version__))
            self.settings.last_version = __version__
            self._save_settings()

    def check_for_updates(self, manual=False):
        """Look for a newer release on a worker thread (UPDATE_CHECKED event)."""
        if self._update_thread is not None and self._update_thread.is_alive():
            return
        if manual:
            self._set_update_status(lambda: tr("update.checking"))

        def work():
            try:
                release, error = updates.check(), None
            except updates.UpdateError as e:
                release, error = None, str(e)
            except Exception as e:  # never let a check break the app
                release, error = None, f"{type(e).__name__}: {e}"
            self.events.post(events.UPDATE_CHECKED, release=release, error=error, manual=manual)

        self._update_thread = threading.Thread(target=work, name="orbida-update-check", daemon=True)
        self._update_thread.start()

    def _set_update_status(self, text):
        self._update_status = text
        if self.settings_view is not None:
            self.settings_view.show_update_status(text)

    def _on_update_checked(self, release, error, manual):
        if error:
            _log.info("Update check failed: %s", error)
            if manual:
                self._set_update_status(lambda: tr("update.failed"))
                self._append_log(f"{tr('update.failed')} ({error})")
            return
        if release is None:
            self._set_update_status(lambda: tr("update.latest", version=__version__))
            return
        self.available_update = release
        version = release.version
        self._set_update_status(lambda: tr("update.available", version=version))
        self._show_update_button()
        self._append_log(tr("log.update_available", version=version))
        if manual:
            self.show_update_dialog()

    def _show_update_button(self):
        version = self.available_update.version
        self._live(self.btn_update, lambda: "\u2b07  " + tr("top.update", version=version))
        if not self.btn_update.winfo_ismapped():
            self.btn_update.pack(side="left", padx=(0, 8), before=self.btn_history)

    @staticmethod
    def can_install_updates():
        """Only the installed Windows app can replace itself; a source run opens the release page."""
        return sys.platform == "win32" and getattr(sys, "frozen", False)

    def show_update_dialog(self):
        if self.available_update is None:
            return
        if self.update_dialog is not None:
            try:
                self.update_dialog.lift()
                return
            except tkinter.TclError:
                self.update_dialog = None
        self.update_dialog = UpdateDialog(self, self.available_update, self.can_install_updates())

    def start_update(self, release):
        """Download the installer on a worker thread; False while a media download runs."""
        if self._job_kind == "download":
            messagebox.showinfo(tr("update.title"), tr("update.busy"), parent=self.update_dialog or self)
            return False
        if self._update_thread is not None and self._update_thread.is_alive():
            return False
        self._update_cancel = cancel = threading.Event()
        folder = os.path.join(app_setup.data_dir(), "updates")

        def progress(done, total):
            self.events.post(events.UPDATE_PROGRESS, done=done, total=total)

        def work():
            try:
                path = updates.download_installer(release, folder, progress, cancel)
            except updates.UpdateError as e:
                if not cancel.is_set():
                    self.events.post(events.UPDATE_FAILED, error=str(e))
                return
            if not cancel.is_set():
                self.events.post(events.UPDATE_READY, path=path)

        self._update_thread = threading.Thread(target=work, name="orbida-update", daemon=True)
        self._update_thread.start()
        return True

    def cancel_update(self):
        self._update_cancel.set()

    def _on_update_progress(self, done, total):
        if self.update_dialog is not None:
            self.update_dialog.show_progress(done, total)

    def _on_update_failed(self, error):
        _log.warning("Update failed: %s", error)
        self._append_log(tr("update.error", error=error))
        if self.update_dialog is not None:
            self.update_dialog.show_error(error)

    def _on_update_ready(self, path):
        """Start the verified installer and close, so it can replace the app."""
        if self._job_kind == "download":
            self._on_update_failed(tr("update.busy"))
            return
        _log.info("Starting the installer %s", path)
        # Setup refuses to run while the app holds its single-instance lock,
        # so free it first; the window closes right after.
        if self.instance is not None:
            self.instance.release()
        try:
            flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0  # detached, own process group
            subprocess.Popen(updates.installer_command(path), creationflags=flags, close_fds=True)
        except OSError as e:
            self._on_update_failed(str(e))
            return
        self._closing = True
        self.destroy()


def describe_result(result):
    """One translated activity line for a finished item (see ItemResult.describe)."""
    if result.status is ItemStatus.COMPLETED:
        return tr("log.saved", path=result.path)
    line = tr("log." + result.status.value, title=result.title)
    return line + (f" ({i18n.tr_message(result.error)})" if result.error else "")


def format_duration(seconds):
    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
