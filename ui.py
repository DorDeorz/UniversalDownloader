import functools
import logging
import math
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
import browser_cookies
import download_history
import events
import filenames
import formats
import i18n
import logic
import media_tools
import playlist
import settings as settings_store
import tray
import updates
import urls
import ytdlp_updates
from logic import DownloadManager, TrimError, parse_trim_range
from results import ItemResult, ItemStatus, JobSummary
from utils import default_download_dir, resource_path
from i18n import tr
from version import APP_NAME, DISPLAY_NAME, GITHUB_REPO, __version__

_log = logging.getLogger(__name__)

ctk.set_default_color_theme("blue")

# Design tokens: (light, dark) pairs, the CustomTkinter convention. Text
# colours keep at least 4.5:1 contrast on the backgrounds they are used on.
# The surfaces, shapes and type follow the FitWren step counter app's
# Material 3 look: warm neutral surfaces, borderless filled cards with large
# corners, pill-shaped buttons and a progress ring.
ACCENT = ("#5b5bd6", "#5f5ae6")
ACCENT_HOVER = ("#4848c2", "#4d48d4")
ACCENT_DISABLED = ("#b4b4ea", "#3a3970")
ON_ACCENT = "#ffffff"
ON_ACCENT_DISABLED = ("#f1f1fc", "#8e8cc0")
BG = ("#f2f2ee", "#1b1c1a")
TOPBAR = BG  # the page title sits on the background, as in FitWren
CARD = ("#e6e7e1", "#262825")
CARD_BORDER = ("#c5c7bf", "#44473f")  # divider lines (cards have no border)
FIELD = ("#dcddd7", "#33352f")
MUTED = ("#52554d", "#b4b7ad")
TEXT = ("#1b1c1a", "#e4e4de")
SECONDARY = ("#dcddd7", "#33352f")
SECONDARY_HOVER = ("#cfd0ca", "#3e413a")
DANGER = ("#b3261e", "#f2b8b5")
SUCCESS = ("#1b6b3a", "#7fd49a")
WARNING = ("#7a5300", "#f0c05a")

CARD_RADIUS = 16
FIELD_RADIUS = 12

# Accent colours offered in Settings (the names match the Android app's).
# Every accent keeps white text readable (4.5:1) in both themes.
ACCENTS = {
    "Indigo": {"accent": ACCENT, "hover": ACCENT_HOVER, "disabled": ACCENT_DISABLED,
               "on_disabled": ON_ACCENT_DISABLED},
    "Blue": {"accent": ("#256fe7", "#256fe7"), "hover": ("#175ed1", "#175ed1"),
             "disabled": ("#b7cbeb", "#293a57"), "on_disabled": ("#f3f6fc", "#9cadc9")},
    "Teal": {"accent": ("#128176", "#128176"), "hover": ("#0e625a", "#0e625a"),
             "disabled": ("#b9e9e4", "#2a5551"), "on_disabled": ("#f3fcfb", "#9cc9c5")},
    # FitWren's own green.
    "Green": {"accent": ("#2e7d32", "#2e7d32"), "hover": ("#25672a", "#25672a"),
              "disabled": ("#bfdcc0", "#2d4a2f"), "on_disabled": ("#f3faf3", "#9cbf9e")},
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
    """A filled, borderless card (Material 3 "filled card", as in FitWren)."""
    return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=CARD_RADIUS, border_width=0, **kw)


# Seconds between progress updates while bytes arrive.
PROGRESS_INTERVAL = 0.1

# Room for the title bar and frame, which geometry() sizes do not include.
WINDOW_FRAME_PX = 48


def work_area(window):
    """(left, top, right, bottom) of the usable screen in pixels.

    On Windows this is the monitor the window is on (the nearest one)
    minus the taskbar, so a window on a second monitor stays there;
    elsewhere the screen minus room for a panel.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            # Own function prototypes: handles are 64-bit, ctypes' default int is not.
            user32 = ctypes.WinDLL("user32")
            user32.GetParent.argtypes = [wintypes.HWND]
            user32.GetParent.restype = wintypes.HWND
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HMONITOR
            user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
            hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
            monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
            info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                rect = info.rcWork
                return rect.left, rect.top, rect.right, rect.bottom
            rect = wintypes.RECT()
            if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError, tkinter.TclError):
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
                   "button_color", "button_hover_color", "border_color", "text_color_disabled", "bg_color",
                   "unselected_color", "unselected_hover_color", "track_color", "scrollbar_button_color",
                   "scrollbar_button_hover_color")

# The Black theme (AMOLED): the dark theme's surfaces become black, cards and
# fields stay slightly grey so they still show. Light values are unchanged.
_SURFACES = ("BG", "TOPBAR", "CARD", "CARD_BORDER", "FIELD", "SECONDARY", "SECONDARY_HOVER")
_DARK_SURFACES = {name: globals()[name][1] for name in _SURFACES}
_BLACK_SURFACES = {"BG": "#000000", "TOPBAR": "#000000", "CARD": "#121212", "CARD_BORDER": "#2e2e2e",
                   "FIELD": "#1f1f1f", "SECONDARY": "#1f1f1f", "SECONDARY_HOVER": "#2b2b2b"}


def appearance_mode(theme):
    """CustomTkinter's appearance mode for a theme setting ("Black" is a dark theme)."""
    return "Dark" if theme == "Black" else theme


def apply_pure_black(on):
    """Use black (or the normal dark) surfaces for widgets built from now on.

    Returns {old colour: new colour} for :func:`recolor`.
    """
    global NAV_SELECTED
    table = _BLACK_SURFACES if on else _DARK_SURFACES
    mapping = {}
    for name in _SURFACES:
        old = globals()[name]
        new = (old[0], table[name])
        globals()[name] = new
        if old != new:
            mapping[old] = new
    old_nav, NAV_SELECTED = NAV_SELECTED, tonal(ACCENT)
    if old_nav != NAV_SELECTED:
        mapping[old_nav] = NAV_SELECTED
    return mapping


def apply_accent(name):
    """Make ``name`` the accent for widgets built from now on.

    Returns {old colour: new colour} for :func:`recolor`, which repaints
    the widgets that already exist.
    """
    global ACCENT, ACCENT_HOVER, ACCENT_DISABLED, ON_ACCENT_DISABLED, SEGMENT_SELECTED, SEGMENT_SELECTED_HOVER
    global NAV_SELECTED
    tokens = ACCENTS.get(name, ACCENTS["Indigo"])
    old = (ACCENT, ACCENT_HOVER, ACCENT_DISABLED, ON_ACCENT_DISABLED, SEGMENT_SELECTED, SEGMENT_SELECTED_HOVER,
           NAV_SELECTED)
    ACCENT, ACCENT_HOVER = tokens["accent"], tokens["hover"]
    ACCENT_DISABLED, ON_ACCENT_DISABLED = tokens["disabled"], tokens["on_disabled"]
    SEGMENT_SELECTED = ("#ffffff", ACCENT[1])
    SEGMENT_SELECTED_HOVER = ("#f4f4fb", ACCENT_HOVER[1])
    NAV_SELECTED = tonal(ACCENT)
    new = (ACCENT, ACCENT_HOVER, ACCENT_DISABLED, ON_ACCENT_DISABLED, SEGMENT_SELECTED, SEGMENT_SELECTED_HOVER,
           NAV_SELECTED)
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
        kw.setdefault("corner_radius", kw["height"] // 2)  # a pill
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
    return ChoiceMenu(parent, choices, label, command, height=34, corner_radius=17, font=font(13), fg_color=SECONDARY,
                      button_color=SECONDARY, button_hover_color=SECONDARY_HOVER, text_color=TEXT,
                      dropdown_font=font(13), **kw)


def switch(parent, text, command, **kw):
    return ctk.CTkSwitch(parent, text=text, command=command, font=font(13), text_color=TEXT, progress_color=ACCENT,
                         fg_color=("#c5c7bf", "#44473f"), button_color=("#5d6057", "#e4e4de"),
                         button_hover_color=("#44473f", "#ffffff"), **kw)


def primary_button(parent, text, command, **kw):
    kw.setdefault("height", 36)
    kw.setdefault("font", font(13, "bold"))
    kw.setdefault("corner_radius", kw["height"] // 2)  # Material 3 buttons are pills
    return ctk.CTkButton(parent, text=text, command=command, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                         text_color=ON_ACCENT, text_color_disabled=ON_ACCENT_DISABLED, **kw)


def set_primary_state(button, state, **kw):
    """Enable or disable a primary button; a disabled one gets a muted fill."""
    button.configure(state=state, fg_color=ACCENT if state == "normal" else ACCENT_DISABLED, **kw)


def secondary_button(parent, text, command, **kw):
    kw.setdefault("height", 36)
    kw.setdefault("corner_radius", kw["height"] // 2)
    kw.setdefault("font", font(13))
    return ctk.CTkButton(parent, text=text, command=command, fg_color=SECONDARY, hover_color=SECONDARY_HOVER,
                         text_color=TEXT, **kw)


def _hex(colour):
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def mix(colour, other, amount):
    """``colour`` laid over ``other`` at ``amount`` (0-1) opacity, as "#rrggbb"."""
    a, b = _hex(colour), _hex(other)
    return "#%02x%02x%02x" % tuple(round(x * amount + y * (1 - amount)) for x, y in zip(a, b))


def tonal(accent):
    """A Material 3 style container colour for ``accent``: a light tint in the
    light theme, a deep one in the dark theme (for selected navigation items)."""
    return mix(accent[0], BG[0], 0.18), mix(accent[1], BG[1], 0.35)


NAV_SELECTED = tonal(ACCENT)


@functools.lru_cache(maxsize=8)
def _ring_shape(size, thickness):
    """Per pixel: how much of it the ring covers (0-1) and its angle from the
    top, clockwise; pixels outside the ring are None."""
    c = (size - 1) / 2
    outer = size / 2 - 0.5
    inner = outer - thickness
    rows = []
    for y in range(size):
        dy = y - c
        row = []
        for x in range(size):
            dx = x - c
            d = math.hypot(dx, dy)
            cover = min(max(outer - d + 0.5, 0.0), 1.0) * min(max(d - inner + 0.5, 0.0), 1.0)
            row.append((cover, math.atan2(dx, -dy) % (2 * math.pi)) if cover > 0 else None)
        rows.append(row)
    return rows


def ring_pixels(size, thickness, fraction, progress, track, background):
    """Rows of "#rrggbb" pixels drawing a progress ring, for PhotoImage.put.

    The ring starts at the top and runs clockwise with round ends, like
    FitWren's step ring. Edges are anti-aliased by pixel coverage.
    """
    fraction = min(max(fraction, 0.0), 1.0)
    c = (size - 1) / 2
    mid = size / 2 - 0.5 - thickness / 2
    half = thickness / 2
    sweep = fraction * 2 * math.pi
    # The round ends: circles at the start (top) and the end of the arc.
    ends = [(c, c - mid), (c + mid * math.sin(sweep), c - mid * math.cos(sweep))] if 0 < fraction < 1 else []
    steps = 24
    track_shades = [mix(track, background, i / steps) for i in range(steps + 1)]
    cache = {}

    def shade(on, cover):
        # ``on`` of the pixel is progress, the rest of ``cover`` is track.
        key = (round(min(on / cover, 1.0) * steps), round(cover * steps))
        if key not in cache:
            cache[key] = mix(mix(progress, track, key[0] / steps), background, key[1] / steps)
        return cache[key]

    rows = []
    for y, shape in enumerate(_ring_shape(size, thickness)):
        row = []
        near = [(ex, ey) for ex, ey in ends if abs(y - ey) <= half + 1]
        for x, cell in enumerate(shape):
            if cell is None:
                row.append(background)
                continue
            cover, angle = cell
            under = round(cover * steps)
            on = cover if fraction >= 1 or angle <= sweep and fraction > 0 else 0.0
            for ex, ey in near:
                if abs(x - ex) <= half + 1:
                    on = max(on, min(max(half - math.hypot(x - ex, y - ey) + 0.5, 0.0), 1.0))
            row.append(shade(on, cover) if on else track_shades[under])
        rows.append("{" + " ".join(row) + "}")
    return " ".join(rows)


class ProgressRing(ctk.CTkFrame):
    """A round progress indicator with the percentage in its middle.

    Works like CTkProgressBar for the app: ``set``, ``get`` and the
    ``progress_color`` option (which :func:`recolor` repaints).
    """

    def __init__(self, master, size=96, thickness=9, progress_color=None, track_color=None, **kw):
        super().__init__(master, width=size, height=size, fg_color="transparent", corner_radius=0, **kw)
        self._ring_size, self._thickness = size, thickness
        self._progress_color = progress_color or ACCENT
        self._track_color = track_color or SECONDARY
        self._value = 0.0
        self._drawn = None
        self._image = None
        self._label = tkinter.Label(self, borderwidth=0, highlightthickness=0, compound="center")
        self._label.place(relx=0.5, rely=0.5, anchor="center")
        self._render()

    def set(self, value):
        self._value = min(max(float(value), 0.0), 1.0)
        self._render()

    def get(self):
        return self._value

    def configure(self, require_redraw=False, **kwargs):
        for option in ("progress_color", "track_color"):
            if option in kwargs:
                setattr(self, "_" + option, self._check_color_type(kwargs.pop(option)))
                require_redraw = True
        super().configure(require_redraw=require_redraw, **kwargs)

    def cget(self, attribute_name):
        if attribute_name in ("progress_color", "track_color"):
            return getattr(self, "_" + attribute_name)
        return super().cget(attribute_name)

    def _draw(self, no_color_updates=False):
        super()._draw(no_color_updates)
        if hasattr(self, "_label"):
            self._render()

    def _render(self):
        size = max(16, round(self._apply_widget_scaling(self._ring_size)))
        thickness = max(2, round(self._apply_widget_scaling(self._thickness)))
        bg = self._apply_appearance_mode(self._bg_color)
        colours = (self._apply_appearance_mode(self._progress_color), self._apply_appearance_mode(self._track_color))
        percent = round(self._value * 100)
        key = (size, thickness, percent, colours, bg)
        if key == self._drawn:
            return
        self._drawn = key
        image = tkinter.PhotoImage(master=self, width=size, height=size)
        image.put(ring_pixels(size, thickness, percent / 100, colours[0], colours[1], bg))
        self._image = image
        self._label.configure(image=image, text=f"{percent}%", bg=bg, fg=self._apply_appearance_mode(TEXT),
                              font=self._apply_font_scaling(("", max(12, round(self._ring_size / 4.4)), "bold")))


class PlaylistSelector(ctk.CTkToplevel):
    """Modal list of playlist entries to pick from.

    Calls ``callback(items)`` with the chosen queue items on confirm, or
    ``callback(None)`` when the dialog is cancelled or closed.
    """

    BATCH = 50  # checkboxes created per idle step, so big playlists stay responsive

    def __init__(self, parent, analysis, callback, downloaded=()):
        """``downloaded``: items downloaded before, which start unticked."""
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
        self.downloaded = {id(item) for item in downloaded}
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
        if self.downloaded:
            self.btn_new = secondary_button(self.btn_frame, tr("playlist.select_new"), self.select_new, height=32)
            self.btn_new.pack(side="left", padx=(8, 0))
        self.lbl_count = ctk.CTkLabel(self.btn_frame, text="", font=font(12, "bold"), text_color=MUTED)
        self.lbl_count.pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=CARD_RADIUS, border_width=0,
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
            before = id(item) in self.downloaded
            var = ctk.IntVar(value=0 if before else 1)
            label = f"{item.index:>3}. {item.title}" if item.index else item.title
            if before:
                label += f"  ({tr('playlist.downloaded')})"
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
    def select_new(self):
        for item, var in zip(self.items, self.vars):
            var.set(0 if id(item) in self.downloaded else 1)
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
    tightens the spacing, then leaves out the keyboard shortcuts card, and
    last tightens the spacing further.
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
        ctk.CTkLabel(header, text=tr("settings.title"), font=font(26, "bold"), text_color=TEXT).grid(
            row=0, column=1, sticky="w", padx=16)
        ctk.CTkLabel(header, text=f"{DISPLAY_NAME} {__version__}", font=font(12), text_color=MUTED).grid(
            row=0, column=2, sticky="e", padx=12)
        self.btn_extension = secondary_button(header, tr("extension.title"), self.open_extension_help, height=34)
        self.btn_extension.grid(row=0, column=3, sticky="e", padx=(0, 8))
        self.btn_logs = secondary_button(header, tr("settings.logs"), self.open_logs, height=34)
        self.btn_logs.grid(row=0, column=4, sticky="e")

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

        # Downloads: how they connect, then what happens around them
        self.card_finish = after = self._section(body, tr("settings.downloads"))
        self.card_net = after  # connection settings share the card (the page must not scroll)
        self.cmb_fragments = option_menu(after, list(self.FRAGMENT_CHOICES),
                                         lambda v: self.on_change("fragments", v), width=80, label=str)
        self.cmb_fragments.set(settings.fragments if settings.fragments in self.FRAGMENT_CHOICES else 4)
        self._setting_row(after, 1, tr("settings.fragments"), tr("settings.fragments_hint"), self.cmb_fragments)
        self.cmb_speed = option_menu(after, list(settings_store.SPEED_LIMITS),
                                     lambda v: self.on_change("speed_limit", v), width=130,
                                     label=lambda n: f"{n} MB/s" if n else tr("speed.unlimited"))
        self.cmb_speed.set(settings.speed_limit)
        self._inline_row(after, 3, tr("settings.speed_limit"), self.cmb_speed)
        self.ent_proxy = ctk.CTkEntry(after, width=200, height=34, fg_color=FIELD, border_width=0,
                                      corner_radius=FIELD_RADIUS, font=font(13),
                                      placeholder_text="host:port")
        if settings.proxy:
            self.ent_proxy.insert(0, settings.proxy)
        self.ent_proxy.bind("<Return>", lambda _e: self._save_proxy())
        self.ent_proxy.bind("<FocusOut>", lambda _e: self._save_proxy())
        self._saved_proxy = settings.proxy
        self._setting_row(after, 4, tr("settings.proxy"), tr("settings.proxy_hint"), self.ent_proxy)
        self.cmb_clipboard = option_menu(after, list(settings_store.CLIPBOARD_CHOICES),
                                         lambda v: self.on_change("clipboard", v), width=170,
                                         label=lambda c: tr(f"clipboard.{c}"))
        self.cmb_clipboard.set(settings.clipboard)
        self._inline_row(after, 6, tr("settings.clipboard"), self.cmb_clipboard)
        # Reddit shows NSFW posts only to signed-in accounts: lend it the browser's sign-in.
        self.sw_reddit = self._switch(after, 7, tr("settings.reddit_sign_in"), settings.reddit_browser_sign_in,
                                      "reddit_browser_sign_in")
        self.sw_awake = self._switch(after, 8, tr("settings.keep_awake"), settings.keep_awake, "keep_awake")
        self.sw_history = self._switch(after, 9, tr("settings.save_history"), settings.save_history,
                                       "save_history")
        self.sw_summary = self._switch(after, 10, tr("settings.summary"), settings.show_summary, "show_summary")
        self.sw_open = self._switch(after, 11, tr("settings.open_folder"), settings.open_folder_when_done,
                                    "open_folder_when_done")
        if tray.supported():
            self.sw_tray = self._switch(after, 12, tr("settings.tray"), settings.close_to_tray, "close_to_tray")
        self._spacing[-1] = (self._spacing[-1][0], (0, 14), (0, 10))

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

    def _inline_row(self, parent, row, title, widget, last=False):
        """A setting on one line without a hint: its name left, ``widget`` right."""
        name = ctk.CTkLabel(parent, text=title, font=font(13, "bold"), text_color=TEXT, anchor="w",
                            justify="left")
        name.grid(row=row, column=0, sticky="ew", padx=(16, 8))
        widget.grid(row=row, column=1, sticky="e", padx=(0, 16))
        for w in (name, widget):
            self._spacing.append((w, (0, 14 if last else 10), (0, 10 if last else 6)))

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
        self._spacing.append((widget, (0, 10), (0, 4)))
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
            # Balance the columns: the shortcuts card goes under Appearance while it shows;
            # without it, Updates does.
            if self.shortcuts_shown:
                order = ((self.card_look, left), (self.card_keys, left), (self.card_finish, right),
                         (self.card_updates, right))
            else:
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

    # Spacing taken off every tight gap at the tightest level (TIGHTEST).
    TIGHTEST_TRIM = 4
    TIGHTEST = 2

    def _set_tight(self, tight):
        """Spacing level: 0 (False) normal, 1 (True) tight, TIGHTEST tight with less between rows."""
        self.tight = tight
        trim = self.TIGHTEST_TRIM if tight == self.TIGHTEST else 0
        for widget, normal, small in self._spacing:
            widget.grid_configure(pady=tuple(max(0, v - trim) for v in small) if tight else normal)
        self.body.grid_configure(pady=(0, 4 if trim else 16))

    def _show_hints(self, show):
        self.hints_shown = show
        for label in self._hints:
            label.grid() if show else label.grid_remove()

    def _show_shortcuts(self, show):
        self.shortcuts_shown = show
        if self._columns == 2:
            self._layout(2)  # the cards change columns (see _layout)
        else:
            self.card_keys.grid() if show else self.card_keys.grid_remove()

    def _schedule_fit(self, _event=None):
        if not self._fit_pending:
            self._fit_pending = True
            self.after_idle(self._fit)

    FIT_STEPS = ((True, False, True), (False, False, True), (False, True, True), (False, True, False),
                 (False, TIGHTEST, False))

    def _fit(self):
        """Choose the columns for the width, then the roomiest layout that fits:
        hints and normal spacing, no hints, tight spacing, no shortcuts card, then even less spacing."""
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
        open_path(app_setup.log_dir())

    def _save_proxy(self):
        """Save the proxy field once it holds a valid address (or is empty)."""
        text = self.ent_proxy.get().strip()
        try:
            proxy = urls.proxy_url(text)
        except ValueError:
            self.ent_proxy.configure(border_width=2, border_color=DANGER)
            return
        self.ent_proxy.configure(border_width=0)
        if proxy != text:
            self.ent_proxy.delete(0, "end")
            self.ent_proxy.insert(0, proxy)
        if proxy != self._saved_proxy:
            self._saved_proxy = proxy
            self.on_change("proxy", proxy)

    def open_extension_help(self):
        ExtensionDialog(self.winfo_toplevel())

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
        ctk.CTkLabel(header, text=tr("history.title"), font=font(26, "bold"), text_color=TEXT).grid(
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


def extension_folder():
    """The browser extension, copied to the data folder so its path stays the same.

    The browser keeps loading an unpacked extension from the folder it was
    loaded from; the program folder is replaced on every update, the data
    folder is not. The copy is refreshed when the app's copy differs.
    """
    import filecmp
    import shutil
    source = resource_path("browser_extension")
    target = os.path.join(app_setup.data_dir(), "browser-extension")
    try:
        same = os.path.isdir(target) and not filecmp.dircmp(source, target).diff_files and \
            filecmp.cmp(os.path.join(source, "manifest.json"), os.path.join(target, "manifest.json"), shallow=False)
        if not same:
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source, target)
        return target
    except OSError as e:
        _log.warning("Could not copy the browser extension: %s", e)
        return source


class ExtensionDialog(ctk.CTkToplevel):
    """How to add the browser extension.

    Chromium browsers load it unpacked from the data folder (it is not in a
    store); Firefox installs the Mozilla-signed copy the installer ships
    (app_setup.FIREFOX_XPI), which stays after Firefox closes.
    """

    ADDRESS = "chrome://extensions"

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(tr("extension.title"))
        self.configure(fg_color=BG)
        self.transient(app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=tr("extension.title"), font=font(17, "bold"), text_color=TEXT,
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        steps = ctk.CTkTextbox(self, font=font(13), fg_color=CARD, text_color=TEXT, wrap="word", height=220,
                               border_width=0, corner_radius=CARD_RADIUS)
        steps.insert("1.0", tr("extension.steps", address=self.ADDRESS) + "\n\n" + tr("extension.firefox"))
        steps.configure(state="disabled")
        steps.grid(row=1, column=0, sticky="nsew", padx=20)
        self.lbl_note = ctk.CTkLabel(self, text="", font=font(12), text_color=MUTED, anchor="w",
                                    justify="left", wraplength=620)
        self.lbl_note.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="e", padx=20, pady=(12, 18))
        self.btn_copy = secondary_button(buttons, tr("extension.copy_address"), self.copy_address)
        self.btn_copy.pack(side="left", padx=(0, 8))
        self.btn_close = secondary_button(buttons, tr("extension.close"), self.destroy)
        self.btn_close.pack(side="left", padx=(0, 8))
        self.btn_firefox = secondary_button(buttons, tr("extension.add_firefox"), self.add_to_firefox)
        self.btn_firefox.pack(side="left", padx=(0, 8))
        self.btn_folder = primary_button(buttons, tr("extension.open_folder"), self.open_folder)
        self.btn_folder.pack(side="left")
        set_window_icon(self)
        self.after(200, lambda: set_window_icon(self))
        fit_dialog(self, (680, 460), (480, 320))
        self.lift()
        self.btn_folder.focus_set()

    def open_folder(self):
        folder = extension_folder()
        open_path(folder)
        self.lbl_note.configure(text=folder)

    def add_to_firefox(self):
        xpi = resource_path(app_setup.FIREFOX_XPI)
        if not os.path.isfile(xpi):  # a copy built without the signed add-on (not a release)
            webbrowser.open(updates.RELEASES_PAGE)
            self.lbl_note.configure(text=tr("extension.firefox_missing"))
        elif app_setup.open_in_firefox(xpi):
            self.lbl_note.configure(text=tr("extension.firefox_opened"))
        else:
            open_path(os.path.dirname(xpi))
            self.lbl_note.configure(text=tr("extension.firefox_file"))

    def copy_address(self):
        self.clipboard_clear()
        self.clipboard_append(self.ADDRESS)
        self.lbl_note.configure(text=tr("extension.copied"))


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
                               border_width=0, corner_radius=CARD_RADIUS)
        notes.insert("1.0", updates.notes_summary(release.notes) or release.page)
        notes.configure(state="disabled")
        notes.grid(row=1, column=0, sticky="nsew", padx=20)
        self.lbl_note = ctk.CTkLabel(self, text=tr("update.restart_note") if can_install else "", font=font(12),
                                     text_color=MUTED, anchor="w", justify="left")
        self.lbl_note.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.progress = ctk.CTkProgressBar(self, height=8, progress_color=ACCENT, fg_color=SECONDARY)
        self.progress.set(0)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="e", padx=20, pady=(12, 18))
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

    def __init__(self, instance=None, link=None):
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
        logic.set_network_options(self.settings.proxy)
        self._reddit = None  # browser_cookies.RedditSignIn while the setting is on
        self._apply_reddit_sign_in()
        ctk.set_appearance_mode(appearance_mode(self.settings.theme))
        ctk.set_widget_scaling(settings_store.TEXT_SIZES[self.settings.text_size])
        i18n.set_language(self.settings.language)
        apply_accent(self.settings.accent)
        apply_pure_black(self.settings.theme == "Black")
        self.history = download_history.History(os.path.join(app_setup.data_dir(), "history.json"))
        self._job_mode = None
        self._analysed = None  # (time, url, info) of the last single video analysed
        # Widgets whose text is translated: (widget, option) -> function giving
        # the text, re-run when the language changes (see _live).
        self._texts = {}

        self.manager = DownloadManager()
        self.download_folder = self.settings.download_folder
        self.download_queue = []
        self.link_queue = []      # links added while a download runs; downloaded one after another
        self._from_queue = False  # the running analysis came from link_queue
        self.analyzed_url = None
        # Only one job (analysis or download) runs at a time; see _start_job.
        self._job_thread = None
        self._job_kind = None
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
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
        self._ytdlp_ready = None       # yt-dlp version downloaded for the next start
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
        self._clip_poll = None
        self._clip_seen = ""
        self._copied = []         # links offered by the clipboard banner
        self._offer = self.use_copied  # what the banner's button does (copied links or a Mix)
        self._mix = None          # the Mix the link being analyzed was opened in
        self._watch_clipboard()
        if link:
            self._startup_calls.append(self.after(350, lambda: self.open_link(link)))
        elif self.settings.auto_paste:
            self._startup_calls.append(self.after(350, self.auto_paste))
        # Links sent by the browser extension while the app runs (app_setup.send_link).
        self.events.register(events.LINK_RECEIVED, self.open_link)
        try:
            self.link_server = app_setup.LinkServer(lambda url: self.events.post(events.LINK_RECEIVED, url=url))
        except OSError as e:
            _log.warning("Links from the browser extension cannot reach this window: %s", e)
            self.link_server = None
        if self.settings.check_updates:
            self._startup_calls.append(self.after(1500, self.check_for_updates))
        # The notification-area icon, while "keep running in the tray" is on.
        self.tray = None
        self._told_tray = False
        self.events.register(events.TRAY_SHOW, self.show_window)
        self.events.register(events.TRAY_QUIT, self.quit_from_tray)
        self._apply_tray()

    POLL_INTERVAL_MS = 50
    LOG_LINES = 2000  # activity lines kept on screen

    def _poll_events(self):
        """Drain the event queue on the main thread, then reschedule."""
        try:
            self.events.dispatch_pending()
        finally:
            self._poll_id = self.after(self.POLL_INTERVAL_MS, self._poll_events)

    def report_callback_exception(self, kind, value, tb):
        """An error in a button, key or timer callback: log it and keep running.

        Tk would print it to the console, which the installed app does not have.
        """
        _log.error("Error in a window callback", exc_info=(kind, value, tb))
        if sys.stderr is not None:
            super().report_callback_exception(kind, value, tb)

    def destroy(self):
        for call in getattr(self, "_startup_calls", ()):
            try:
                self.after_cancel(call)
            except Exception:
                pass
        for call in (getattr(self, "_clip_poll", None),):
            if call is not None:
                try:
                    self.after_cancel(call)
                except Exception:
                    pass
        self._clip_poll = None
        if getattr(self, "link_server", None) is not None:
            self.link_server.close()
            self.link_server = None
        if getattr(self, "tray", None) is not None:
            self.tray.stop()
            self.tray = None
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
        ctk.CTkLabel(brand, text=DISPLAY_NAME, font=font(22, "bold"), text_color=TEXT).pack(side="left")
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
        # The pages, as a navigation bar: the open one sits on a tonal pill,
        # like the selected tab in FitWren.
        nav = self.nav = ctk.CTkFrame(right, fg_color="transparent")
        nav.pack(side="left")
        self.btn_home = self._nav_button(nav, lambda: "\u2193  " + tr("action.download"), self.show_download_page)
        self.btn_history = self._nav_button(nav, lambda: "\u23f2  " + tr("top.history"), self.toggle_history)
        self.btn_settings = self._nav_button(nav, lambda: "\u2699  " + tr("top.settings"), self.toggle_settings)
        for i, button in enumerate((self.btn_home, self.btn_history, self.btn_settings)):
            button.pack(side="left", padx=(0 if i == 0 else 4, 0))
        self._sync_nav()
        self._refresh_logo_bg()

    def _nav_button(self, parent, text, command):
        button = ctk.CTkButton(parent, text="", command=command, height=36, corner_radius=18, width=72,
                               fg_color="transparent", hover_color=SECONDARY_HOVER, text_color=TEXT,
                               font=font(13, "bold"))
        self._live(button, text)
        return button

    def _sync_nav(self):
        """Mark the page on screen in the navigation bar."""
        page = "settings" if self.settings_view is not None else "history" if self.history_view is not None \
            else "home"
        for name, button in (("home", self.btn_home), ("history", self.btn_history), ("settings", self.btn_settings)):
            button.configure(fg_color=NAV_SELECTED if name == page else "transparent")

    def show_download_page(self):
        self.close_settings()
        self.close_history()

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
                                      font=font(14), fg_color=FIELD, border_width=0, corner_radius=22)
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
        # Links waiting in the queue (shown while there are any).
        self.queue_row = ctk.CTkFrame(url_card, fg_color="transparent")
        self.lbl_queue = ctk.CTkLabel(self.queue_row, text="", font=font(13, "bold"), text_color=TEXT, anchor="w")
        self.lbl_queue.pack(side="left")
        self.btn_clear_queue = secondary_button(self.queue_row, "", self.clear_link_queue, height=28)
        self._live(self.btn_clear_queue, lambda: tr("queue.clear"))
        self.btn_clear_queue.pack(side="left", padx=(10, 0))
        # A link just copied to the clipboard (Settings: clipboard "watch").
        self.copied_row = ctk.CTkFrame(url_card, fg_color=FIELD, corner_radius=FIELD_RADIUS)
        self.copied_row.grid_columnconfigure(0, weight=1)
        self.lbl_copied = ctk.CTkLabel(self.copied_row, text="", font=font(13), text_color=TEXT, anchor="w")
        self.lbl_copied.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=6)
        self.btn_copied = primary_button(self.copied_row, "", lambda: self._offer(), height=28)
        self.btn_copied.grid(row=0, column=1, pady=6)
        self.btn_copied_close = secondary_button(self.copied_row, "\u2715", self._hide_copied, width=28, height=28)
        self.btn_copied_close.grid(row=0, column=2, padx=(6, 8), pady=6)
        self._show_media(lambda: tr("link.hint"), MUTED)

        # Options
        opt_card = card(self.main_frame)
        opt_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        opt_card.grid_columnconfigure((1, 3), weight=1)
        self._section_label(opt_card, "options.mode").grid(row=0, column=0, sticky="w", padx=(16, 12), pady=(16, 8))
        self.cmb_mode = segmented(opt_card, list(formats.MODES), self._on_mode_changed,
                                  label=lambda m: tr(MODE_KEYS[m]))
        self.cmb_mode.grid(row=0, column=1, columnspan=2, sticky="w", pady=(16, 8))
        toggles = ctk.CTkFrame(opt_card, fg_color="transparent")
        toggles.grid(row=0, column=3, sticky="e", padx=(8, 16), pady=(16, 8))
        # Subtitles are saved next to videos (not in Audio Only mode); remembered in the settings.
        self.chk_subtitles = switch(toggles, "", self._on_subtitles_toggled)
        self._live(self.chk_subtitles, lambda: tr("options.subtitles"))
        if self.settings.subtitles:
            self.chk_subtitles.select()
        self.chk_subtitles.grid(row=0, column=0)
        # SponsorBlock cuts sponsors and intros out of YouTube videos; remembered in the settings.
        self.chk_sponsorblock = switch(toggles, "", self._on_sponsorblock_toggled)
        self._live(self.chk_sponsorblock, lambda: tr("options.sponsorblock"))
        if self.settings.sponsorblock:
            self.chk_sponsorblock.select()
        self.chk_sponsorblock.grid(row=0, column=1, padx=(16, 0))
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
        self.ent_start = ctk.CTkEntry(trim_row, width=110, height=32, fg_color=FIELD, border_width=0,
                                      corner_radius=FIELD_RADIUS)
        self._live(self.ent_start, lambda: tr("trim.start"), "placeholder_text")
        self.ent_start.grid(row=0, column=1, padx=(0, 6))
        lbl_to = ctk.CTkLabel(trim_row, text="", text_color=MUTED, font=font(13))
        lbl_to.grid(row=0, column=2, padx=4)
        self._live(lbl_to, lambda: tr("trim.to"))
        self.ent_end = ctk.CTkEntry(trim_row, width=110, height=32, fg_color=FIELD, border_width=0,
                                    corner_radius=FIELD_RADIUS)
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
                                       corner_radius=18, height=36, anchor="w")
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
                                           font=font(16, "bold"))
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
        # FitWren's step ring, here for the current download.
        prog_card.grid_columnconfigure(1, weight=1)
        prog_card.grid_rowconfigure((0, 4), weight=1)
        self.progress_bar = ProgressRing(prog_card, size=76, thickness=8)
        self.progress_bar.grid(row=0, column=0, rowspan=5, padx=(14, 16), pady=12)
        self.lbl_item = ctk.CTkLabel(prog_card, text="", font=font(15, "bold"), text_color=TEXT, anchor="w",
                                     justify="left")
        self._live(self.lbl_item, lambda: tr("progress.ready"))
        self.lbl_item.grid(row=1, column=1, sticky="ew", padx=(0, 16))
        self.lbl_progress = ctk.CTkLabel(prog_card, text="0%", font=font(13), text_color=MUTED, anchor="w")
        self.lbl_progress.grid(row=2, column=1, sticky="w", padx=(0, 16), pady=(2, 0))
        self.lbl_detail = ctk.CTkLabel(prog_card, text="", font=font(13), text_color=MUTED, anchor="w")
        self.lbl_detail.grid(row=3, column=1, sticky="w", padx=(0, 16))

        # Activity log
        log_card = self.log_card = card(self.main_frame)
        log_card.grid(row=5, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        self._section_label(log_card, "activity.title").grid(row=0, column=0, sticky="w", padx=16, pady=(12, 4))
        self.console = ctk.CTkTextbox(log_card, height=100, font=ctk.CTkFont(family="Consolas", size=12),
                                      fg_color="transparent", text_color=TEXT, wrap="word",
                                      state="disabled")  # read-only; text can still be selected and copied
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
        self.console.configure(state="normal")
        self.console.insert("end", f"> {message}\n")
        # A long playlist would otherwise grow the box without end.
        lines = int(self.console.index("end-1c").split(".")[0])
        if lines > self.LOG_LINES:
            self.console.delete("1.0", f"{lines - self.LOG_LINES}.0")
        self.console.configure(state="disabled")
        self.console.see("end")
    def _show_progress(self, fraction, text, detail=""):
        """``text`` and ``detail`` are strings, or functions for translated text."""
        self.progress_bar.set(fraction)
        self._live(self.lbl_progress, text if callable(text) else (lambda: text))
        if self.tray is not None and self.state() == "withdrawn":
            self.tray.set_title(f"{APP_NAME} · {text() if callable(text) else text}")
        if self._job_kind == "download" and self._pause_event.is_set():
            detail = lambda: tr("progress.paused")  # an update sent just before the pause  # noqa: E731
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
        mapping = apply_pure_black(theme == "Black")
        if mapping:
            recolor(self, mapping)
            self.configure(fg_color=BG)
        ctk.set_appearance_mode(appearance_mode(theme))
        self.settings.theme = theme
        self._refresh_logo_bg()
        self._save_settings()
    def _apply_reddit_sign_in(self):
        """Send Reddit the browser's sign-in while the setting is on (Settings › Downloads)."""
        if self.settings.reddit_browser_sign_in:
            if self._reddit is None:
                self._reddit = browser_cookies.RedditSignIn(os.path.join(app_setup.data_dir(), "reddit-cookies"))
            self._reddit.refresh()
            logic.set_reddit_sign_in(self._reddit)
        else:
            logic.set_reddit_sign_in(None)
            if self._reddit is not None:
                self._reddit.remove_copy()
                self._reddit = None

    def reddit_status(self):
        """The translated state of the Reddit sign-in, or its description while it is off."""
        sign_in = self._reddit
        if sign_in is None:
            return tr("settings.reddit_sign_in_hint")
        sign_in.ydl_options()  # reads the browser again when the last look is old
        return tr(f"reddit.{sign_in.status}", browser=browser_cookies.browser_name(sign_in.browser_database),
                  sites=", ".join(sign_in.sites))

    def _on_setting_changed(self, name, value):
        """Called by the settings page; applies and saves one setting."""
        if name == "theme":
            self._on_theme_changed(value)
            return
        if name == "clipboard":
            self.settings = self.settings.with_clipboard(value)
            self._watch_clipboard()
            self._save_settings()
            return
        setattr(self.settings, name, value)
        if name == "proxy":
            logic.set_network_options(value)
        if name == "reddit_browser_sign_in":
            self._apply_reddit_sign_in()
            if value and self.settings_view is not None:
                # Turned on in Settings: say whether the browser is signed in to Reddit.
                messagebox.showinfo(tr("reddit.ask_title"), self.reddit_status(), parent=self)
        if name == "close_to_tray":
            self._apply_tray()
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
            # Never narrower than the top bar, whose navigation grows with the
            # text size and the language.
            base_min = (max(self.MIN_SIZE[0] * scale, self.top_bar.winfo_reqwidth()), self.MIN_SIZE[1] * scale)
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
        self._sync_nav()
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
        self._sync_nav()
        self.after_idle(self._fill_height)
    def open_history(self):
        """Show the History page in place of the download page."""
        if self.history_view is not None:
            return
        self.close_settings()
        self.history_view = HistoryView(self, self.history, self.close_history)
        self.history_view.grid(row=1, column=0, sticky="nsew")
        self.main_frame.grid_remove()
        self._sync_nav()
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
        self._sync_nav()
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
        self.chk_subtitles.configure(state="disabled" if mode == formats.AUDIO_ONLY else "normal")
        if save:
            self._save_settings()

    def _on_sponsorblock_toggled(self):
        self.settings.sponsorblock = bool(self.chk_sponsorblock.get())
        self._save_settings()

    def _on_subtitles_toggled(self):
        self.settings.subtitles = bool(self.chk_subtitles.get())
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
        if self.is_busy() or self.url_entry.get().strip() or self.link_queue or self._from_queue:
            return  # never mix a pasted link into queued work
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
        links = urls.split_links(text)
        if len(links) > 1:
            self.queue_links(links)
            return
        if len(links) == 1 and len(text.split()) > 1:
            text = links[0]  # "Watch this: https://..." pastes only the link
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

    def _start_job(self, kind, target, *args, with_cancel=False):
        """Start a worker thread unless another job is running.

        ``with_cancel`` passes the job's cancel event to ``target`` as its last argument.

        Returns False (and starts nothing) when a job is already active, so a
        second click cannot run two workers against the same state.
        """
        if self.is_busy():
            self._append_log(f"Busy: wait for the current {self._job_kind} to finish.")
            return False
        self._job_kind = kind
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()  # set while the download is paused
        if with_cancel:
            args = (*args, self._cancel_event)
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
        # While a download runs, more links can be added to the queue.
        queueing = busy and self._job_kind == "download"
        for widget in (self.url_entry, self.btn_paste):
            widget.configure(state="normal" if queueing else state)
        for widget in (self.btn_dest, self.chk_trim, self.chk_sponsorblock, self.cmb_mode, self.cmb_format,
                       self.cmb_quality):
            widget.configure(state=state)
        self.chk_subtitles.configure(
            state="disabled" if busy or self.cmb_mode.get() == formats.AUDIO_ONLY else "normal")
        trim_state = "normal" if (not busy and self.chk_trim.get()) else "disabled"
        self.ent_start.configure(state=trim_state)
        self.ent_end.configure(state=trim_state)
        # Downloads and analyses can be cancelled (a long playlist takes a while to read).
        self.btn_cancel.configure(state="normal" if busy and self._job_kind in ("download", "analysis")
                                  else "disabled")
        self._live(self.btn_cancel, lambda: tr("action.cancel"))
        set_primary_state(self.btn_analyze, "normal" if queueing else state)
        self._live(self.btn_analyze, lambda: tr("queue.add") if queueing else tr("link.analyze"))
        if busy:
            self._refresh_pause_button()
            self.btn_retry.configure(state="disabled")
        else:
            self._refresh_download_button()
            self._refresh_retry_button()

    def _refresh_pause_button(self):
        """While a download runs, the Download button pauses and resumes it."""
        if self._job_kind != "download" or self._cancel_event.is_set():
            set_primary_state(self.btn_download, "disabled")
            return
        set_primary_state(self.btn_download, "normal")
        paused = self._pause_event.is_set()
        self._live(self.btn_download, lambda: tr("action.resume") if paused else tr("action.pause"))

    def toggle_pause(self):
        """Pause the running download where it is, or let it go on (logic.wait_while_paused)."""
        if self._job_kind != "download" or self._cancel_event.is_set():
            return
        if self._pause_event.is_set():
            self._pause_event.clear()
            self._append_log(tr("log.resumed"))
        else:
            self._pause_event.set()
            self._append_log(tr("log.paused"))
            self._live(self.lbl_detail, lambda: tr("progress.paused"))
        self._refresh_pause_button()

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
        """Ask the running download to stop (results arrive via job_done), or drop the analysis."""
        if self._job_kind == "analysis" and not self._cancel_event.is_set():
            self._cancel_analysis()
            return
        if self._job_kind != "download" or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.btn_cancel.configure(state="disabled")
        self._live(self.btn_cancel, lambda: tr("action.cancelling"))
        self._append_log(tr("action.cancelling"))
        self._refresh_pause_button()

    def _cancel_analysis(self):
        """Stop waiting for the analysis at once.

        The worker stops at the next page it reads (logic.fetch_info); what
        it still posts is dropped, so a new analysis can start right away.
        """
        self._cancel_event.set()
        self._append_log(tr("log.analysis_cancelled"))
        self._live(self.btn_analyze, lambda: tr("link.analyze"))
        self._show_media(lambda: tr("log.analysis_cancelled"), MUTED)
        self._mix = None
        self._from_queue = False
        self.clear_link_queue()  # Cancel stops the whole queue
        self._end_job()

    def retry_failed(self):
        items = self._failed_items()
        if not items or self.is_busy():
            return
        self._append_log(tr("log.retrying", count=len(items)))
        self.download_queue = items
        self.skipped_items = []
        self.start_download_queue()

    CLOSE_TIMEOUT_MS = 15000

    def _apply_tray(self):
        """Show the tray icon while the setting is on (Windows only)."""
        if self.settings.close_to_tray and self.tray is None:
            icon = tray.Tray(APP_NAME, lambda: self.events.post(events.TRAY_SHOW),
                             lambda: self.events.post(events.TRAY_QUIT), tr)
            if icon.start():
                self.tray = icon
        elif not self.settings.close_to_tray and self.tray is not None:
            self.tray.stop()
            self.tray = None
            self.show_window()

    def hide_to_tray(self):
        self.withdraw()
        if not self._told_tray:
            self._told_tray = True
            app_setup.notify(tr("tray.hidden_title"), tr("tray.hidden_body"))

    def show_window(self):
        if self._closing:
            return
        self.deiconify()
        self.lift()
        self.focus_force()
        if self.tray is not None:
            self.tray.set_title(APP_NAME)

    def quit_from_tray(self):
        """Quit in the tray icon's menu: the window's close, without hiding again."""
        self.show_window()
        self.on_close(hide=False)

    def on_close(self, hide=True):
        """Window close: hide to the tray, or confirm, cancel a running download, wait, then exit."""
        if self._closing:
            return
        if hide and self.tray is not None:
            self.hide_to_tray()
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
        links = urls.split_links(self.url_entry.get())
        if len(links) > 1:
            # Several links pasted at once: each is downloaded in turn.
            self.url_entry.delete(0, "end")
            self.queue_links(links)
            return
        if self._job_kind == "download":
            self.add_to_queue()
            return
        if self.is_busy():
            return
        try:
            url = urls.normalize_url(self.url_entry.get())
        except urls.UrlError as e:
            # Rejected before any network request (ISSUES.md #32).
            key, values = e.key, e.values  # ``e`` is unbound after the except block
            self._show_media(lambda: tr(key, **values), DANGER)
            return
        # A song opened in a YouTube Mix is analyzed alone; the Mix is offered after.
        self._begin_analysis(url, mix=urls.youtube_mix(self.url_entry.get()))

    def _begin_analysis(self, url, mix=None):
        if self._offer == self.use_mix:
            self._hide_copied()
        self._mix = mix
        if url != self.url_entry.get().strip():
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
        # A new analysis invalidates the previous queue and progress.
        self.analyzed_url = None
        self.set_queue([])
        self._show_progress(0, "0%")
        self._live(self.lbl_item, lambda: tr("progress.ready"))
        if self._start_job("analysis", self.run_analysis, url, with_cancel=True):
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
            if self.link_queue:
                self._next_in_queue()  # links that came in during the check
        else:
            self._set_status(lambda: tr("top.ffmpeg_missing"), DANGER)
            messagebox.showerror(tr("top.ffmpeg_missing"), tr("ffmpeg.body", error=status.error), parent=self)
    def run_analysis(self, url, cancel=None):
        """Worker thread: fetch info and post the result; no widget access.

        ``cancel`` is the job's cancel event (set by Cancel); a cancelled
        analysis posts nothing.
        """
        def post(kind, **payload):
            if cancel is None:
                self.events.post(kind, **payload)
            elif not cancel.is_set():
                self.events.post(kind, job=cancel, **payload)
        try:
            self.log(tr("log.fetching"))
            info = self.manager.fetch_info(url, cancel_event=cancel)
            if cancel is not None and cancel.is_set():
                return
            if info is None:
                post(events.ANALYSIS_FAILED, message="ERROR: Info is None.")
            elif 'error' in info:
                # A post that needs a sign-in also offers the browser's (offer_reddit_sign_in).
                site = logic.sign_in_offer(info['error'])
                post(events.ANALYSIS_FAILED, message=f"FAILED: {i18n.tr_message(info['error'])}",
                     **({'sign_in': site} if site else {}))
            else:
                analysis = playlist.analyze(info, url)
                if cancel is not None and cancel.is_set():
                    return
                if not analysis.is_playlist and analysis.items and info.get('formats'):
                    # Its download starts from this information (see _known_info).
                    self._analysed = (time.monotonic(), analysis.items[0].url, info)
                post(events.ANALYSIS_DONE, analysis=analysis, url=url)
        except Exception as e:
            post(events.ANALYSIS_FAILED, message=f"Error: {e}")
    def _stale(self, job):
        """True for an event of an analysis that was cancelled (or replaced)."""
        return job is not None and (job.is_set() or job is not self._cancel_event)

    def _on_analysis_failed(self, message, sign_in=False, job=None):
        if self._stale(job):
            return
        self._append_log(message)
        self._live(self.btn_analyze, lambda: tr("link.analyze"))
        self._show_media(lambda: message, DANGER)
        self._end_job()
        if self._from_queue:
            self._from_queue = False
            self._next_in_queue()
        elif sign_in and not self.settings.reddit_browser_sign_in:
            self.offer_reddit_sign_in("Reddit" if sign_in is True else sign_in)

    def offer_reddit_sign_in(self, site="Reddit"):
        """``site`` refused a post without sign-in: offer the browser's sign-in, then try again."""
        if site == "Reddit":
            title, body = tr("reddit.ask_title"), tr("reddit.ask_body")
        else:
            title, body = tr("signin.ask_title", site=site), tr("signin.ask_body", site=site)
        if not messagebox.askyesno(title, body, parent=self):
            return
        self._on_setting_changed("reddit_browser_sign_in", True)
        status = self.reddit_status()
        self._append_log(status)
        if self._reddit.signed_in(site):
            self.start_analysis_thread()
        else:
            if self._reddit.status == browser_cookies.SIGNED_IN:  # signed in elsewhere, not to this site
                status = i18n.tr_message(logic.SIGN_IN_MISSING.format(site=site)) if site != "Reddit" \
                    else i18n.tr_message(logic.REDDIT_SIGN_IN_MISSING)
            messagebox.showinfo(title, status, parent=self)
    def _on_analysis_done(self, analysis, url, job=None):
        if self._stale(job):
            return
        self._live(self.btn_analyze, lambda: tr("link.analyze"))
        self._end_job()
        self._describe_analysis(analysis)
        mix, self._mix = self._mix, None
        if mix and not analysis.is_playlist and analysis.items and not self._from_queue:
            self._show_mix(mix)
        for item in analysis.skipped:
            self._append_log(tr("log.skipped_entry", title=item.title, reason=i18n.tr_message(item.skip_reason)))
        from_queue, self._from_queue = self._from_queue, False
        if playlist.found_by_search(analysis) and self.cmb_mode.get() != formats.AUDIO_ONLY:
            # Spotify links are songs: download them as audio (the user can switch back).
            self._apply_mode(formats.AUDIO_ONLY)
            self._append_log(tr("log.spotify"))
        if not analysis.items:
            message = tr("link.nothing")
            if analysis.skipped:
                message = tr("link.nothing_reason", reason=i18n.tr_message(analysis.skipped[0].skip_reason))
            self._append_log(message)
            if from_queue:
                self._next_in_queue()
            else:
                messagebox.showwarning(tr("link.nothing_title"), message, parent=self)
            return
        if from_queue:
            # Queued links download without questions; for a playlist, only
            # the entries not downloaded before.
            items = analysis.items
            if analysis.is_playlist:
                before = {id(i) for i in playlist.downloaded_before(items, [e.url for e in self.history.entries])}
                items = [i for i in items if id(i) not in before]
                if not items:
                    self._append_log(tr("log.queue_nothing_new", title=analysis.title))
                    self._next_in_queue()
                    return
            self.analyzed_url = url
            self.set_queue([item.as_dict() for item in items],
                           skipped=[item.as_dict() for item in analysis.skipped])
            self.start_download_queue()
            return
        if analysis.is_playlist:
            self._append_log(tr("log.playlist", title=analysis.title, count=len(analysis.items),
                                skipped=len(analysis.skipped)))
            self._pending_skipped = [item.as_dict() for item in analysis.skipped]
            before = playlist.downloaded_before(analysis.items, [e.url for e in self.history.entries])
            self.playlist_dialog = PlaylistSelector(
                self, analysis, lambda items: self._on_playlist_selected(url, items), downloaded=before)
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
    # --- link queue ---------------------------------------------------------

    def add_to_queue(self):
        """Put the link in the field at the end of the queue (while a download runs)."""
        try:
            url = urls.normalize_url(self.url_entry.get())
        except urls.UrlError as e:
            key, values = e.key, e.values
            self._show_media(lambda: tr(key, **values), DANGER)
            return
        self.link_queue.append(url)
        self.url_entry.delete(0, "end")
        self._append_log(tr("log.queue_added", url=url))
        self._show_link_queue()

    def queue_links(self, links):
        """Download ``links`` one after another, without questions (like queued links)."""
        self.link_queue.extend(links)
        self._append_log(tr("log.batch", count=len(links)))
        self._show_link_queue()
        if not self.is_busy():
            self._next_in_queue()

    def open_link(self, url):
        """A link from the browser extension: bring the window up and analyze it.

        An empty link only brings the window up (Orbida started again while
        it runs, perhaps hidden in the tray).
        """
        try:
            if self.state() in ("iconic", "withdrawn"):
                self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(300, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except tkinter.TclError:
            return
        if not url:
            return
        if self.settings_view is not None:
            self.close_settings()
        if self.history_view is not None:
            self.close_history()
        try:
            url = urls.normalize_url(url)
        except urls.UrlError:
            return
        self._append_log(tr("log.from_browser"))
        if self.is_busy() and self._job_kind != "download":
            self.queue_links([url])  # an analysis or the start-up check is running
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        self.start_analysis_thread()

    # --- Clipboard watch ----------------------------------------------------------

    CLIPBOARD_POLL_MS = 1000

    def _clipboard_text(self):
        try:
            return self.clipboard_get()
        except tkinter.TclError:
            return ""

    def _watch_clipboard(self):
        """Start or stop looking for copied links (Settings: clipboard)."""
        if self._clip_poll is not None:
            self.after_cancel(self._clip_poll)
            self._clip_poll = None
        if self.settings.watch_clipboard and not self._closing:
            self._clip_seen = self._clipboard_text()  # what was copied before is not new
            self._clip_poll = self.after(self.CLIPBOARD_POLL_MS, self._poll_clipboard)
        else:
            self._hide_copied()

    def _poll_clipboard(self):
        self._clip_poll = None
        if self._closing:
            return
        text = self._clipboard_text()
        if text != self._clip_seen:
            self._clip_seen = text
            links = urls.split_links(text) if len(text) < 100_000 else []
            if links and links != [self.url_entry.get().strip()]:
                self._show_copied(links)
        self._clip_poll = self.after(self.CLIPBOARD_POLL_MS, self._poll_clipboard)

    def _show_copied(self, links):
        self._copied = links
        self._offer = self.use_copied
        if len(links) == 1:
            link = links[0]
            short = link if len(link) <= 60 else link[:57] + "\u2026"
            self._live(self.lbl_copied, lambda: tr("clipboard.copied", link=short))
        else:
            count = len(links)
            self._live(self.lbl_copied, lambda: tr("clipboard.copied_many", count=count))
        self._live(self.btn_copied, lambda: tr("clipboard.download"))
        self.copied_row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 14))

    def _hide_copied(self):
        self._copied = []
        try:
            self.copied_row.grid_remove()
        except (AttributeError, tkinter.TclError):
            pass

    def _show_mix(self, mix):
        self._copied = [mix]
        self._offer = self.use_mix
        self._live(self.lbl_copied, lambda: tr("mix.offer"))
        self._live(self.btn_copied, lambda: tr("mix.download"))
        self.copied_row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 14))

    def use_mix(self):
        """Analyze the whole Mix the last song was opened in (offered after its analysis)."""
        links = self._copied
        self._hide_copied()
        if links and not self.is_busy():
            self._begin_analysis(links[0])

    def use_copied(self):
        links, self._copied = self._copied, []
        self._hide_copied()
        if len(links) > 1:
            self.queue_links(links)
        elif links:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, links[0])
            self.start_analysis_thread()

    def clear_link_queue(self):
        if self.link_queue:
            self.link_queue = []
            self._append_log(tr("log.queue_cleared"))
        self._show_link_queue()

    def _show_link_queue(self):
        count = len(self.link_queue)
        if count:
            self._live(self.lbl_queue, lambda: tr("queue.waiting", count=count))
            self.queue_row.grid(row=2, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 14))
        else:
            self.queue_row.grid_remove()

    def _next_in_queue(self):
        """Analyze and download the next queued link, if any."""
        if not self.link_queue or self.is_busy() or self._closing:
            self._show_link_queue()
            return
        url = self.link_queue.pop(0)
        self._show_link_queue()
        self._append_log(tr("log.queue_next", url=url))
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        self._from_queue = True
        self.start_analysis_thread()
        if not self.is_busy():  # the link was rejected
            self._from_queue = False
            self._next_in_queue()

    def set_queue(self, items, skipped=()):
        self.download_queue = list(items)
        # Entries that cannot be downloaded; reported as skipped in the result.
        self.skipped_items = list(skipped) if self.download_queue else []
        if self.download_queue:
            self.log(tr("log.queue", count=len(self.download_queue)))
        if not self.is_busy():
            self._refresh_download_button()
    def start_download_queue(self):
        if self._job_kind == "download":
            self.toggle_pause()  # the button pauses and resumes while a download runs
            return
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
            _log.warning(warning)
            free = filenames.low_space_mb(self.download_folder)
            self._append_log(tr("folder.low_space", mb=free) if free is not None else warning)
        self._show_progress(0, "0%")
        items = list(self.download_queue) + list(self.skipped_items)
        opts = {
            'save_path': self.download_folder, 'mode': self.cmb_mode.get(),
            'format': self.cmb_format.get(), 'quality': self.cmb_quality.get(),
            'trim_start': self.ent_start.get() if self.chk_trim.get() else None,
            'trim_end': self.ent_end.get() if self.chk_trim.get() else None,
            **settings_store.download_speed_options(self.settings),
        }
        if self.settings.subtitles and opts['mode'] != formats.AUDIO_ONLY:
            opts.update(subtitles=True, subtitle_langs=logic.subtitle_languages(i18n.current()))
        if self.settings.sponsorblock:
            opts['sponsorblock'] = True
        self._job_mode = opts['mode']
        if self._start_job("download", self._run_queue_with_cancel, items, opts):
            # The field is free for the next link, which joins the queue.
            self.url_entry.delete(0, "end")
    def run_queue(self, items, opts, cancel_event=None, pause_event=None):
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
                item_opts = dict(opts, playlist_index=item.get('index'), playlist_title=item.get('playlist'),
                                 meta=item.get('meta'))
                info = self._known_info(item['url'])
                result = self._download_once(item, item_opts, cancel_event, info, pause_event)
                if info is not None and result.status is ItemStatus.FAILED and not (
                        cancel_event is not None and cancel_event.is_set()):
                    # The saved media links may have expired; ask the site again.
                    self._analysed = None
                    self.log(f"Retrying with fresh information ({result.error})")
                    result = self._download_once(item, item_opts, cancel_event, None, pause_event)
                result.source = item
                summary.add(result)
                self.events.post(events.ITEM_DONE, result=result)
        finally:
            self.events.post(events.JOB_DONE, summary=summary)
    # How long an analysed video's information is reused for its download (as
    # on Android): the site is not asked twice, and for YouTube its JavaScript
    # challenge is not solved twice. A stale link only costs a second attempt.
    REUSE_SECONDS = 20 * 60

    def _known_info(self, url):
        """The analysed information for ``url`` while it is fresh, else None."""
        if self._analysed is None:
            return None
        when, known_url, info = self._analysed
        if known_url != url or time.monotonic() - when > self.REUSE_SECONDS:
            return None
        return info

    def _download_once(self, item, options, cancel_event, info, pause_event=None):
        extra = {'info': info} if info is not None else {}
        if pause_event is not None:
            extra['pause_event'] = pause_event
        try:
            return self.manager.download_video(
                item['url'], options, self.progress_hook, log_callback=self.log, title=item['title'],
                cancel_event=cancel_event, **extra)
        except Exception as e:
            return ItemResult(item['url'], item['title'], ItemStatus.FAILED, error=str(e) or type(e).__name__)

    def _run_queue_with_cancel(self, items, opts):
        # Bound at start so a later job's events cannot leak into this one.
        self.run_queue(items, opts, self._cancel_event, self._pause_event)
    def _on_item_done(self, result):
        self._append_log(describe_result(result))
        if result.status is ItemStatus.COMPLETED and result.path and self.settings.save_history:
            self.history.add(result.title, result.path, result.url, self._job_mode or "")
    def _on_job_done(self, summary):
        self._append_log(tr("log.result", summary=summary.headline(
            label=lambda status: tr("status." + status.value), nothing=tr("summary.nothing"))))
        self.last_summary = summary
        cancelled = self._cancel_event.is_set()
        self._end_job()
        if self._closing:
            return
        if cancelled and self.link_queue:
            self.clear_link_queue()  # Cancel stops the whole queue
        more = bool(self.link_queue)
        def headline():
            return summary.headline(label=lambda status: tr("status." + status.value), nothing=tr("summary.nothing"))
        self._live(self.lbl_item, lambda: f"{tr(summary.title_key())}: {headline()}")
        done = len(summary.with_status(ItemStatus.COMPLETED))
        good = summary.all_ok or (done and summary.no_problems)
        self.progress_bar.configure(progress_color=SUCCESS if good else WARNING if done or summary.no_problems
                                    else DANGER)
        if summary.all_ok:
            self._show_progress(1, lambda: tr("progress.complete"))
        else:
            self._show_progress(done / len(summary.results) if summary.results else 0, headline)
        if more:
            self._next_in_queue()
            return
        if not self._in_front():
            # The user is in another window: say that the downloads finished.
            app_setup.notify(tr(summary.title_key()), headline(), window=self)
        if done and self.settings.open_folder_when_done:
            self.open_folder()
        if self.settings.show_summary:
            show = messagebox.showinfo if summary.no_problems and done else messagebox.showwarning
            report = summary.report(label=lambda status: tr("status." + status.value),
                                    nothing=tr("summary.nothing"), more=tr("summary.more", count="{count}"))
            show(tr(summary.title_key()), report, parent=self)
    def _in_front(self):
        """True while Orbida is the window the user works in."""
        try:
            return self.state() != "iconic" and self.focus_get() is not None
        except (KeyError, tkinter.TclError):  # focus in a closed or foreign Tk widget
            return False
    def progress_hook(self, d):
        """yt-dlp progress and postprocessor hook; runs on the worker thread."""
        stage = events.stage_from_hook(d)
        if stage is not None:
            self.events.post(events.STAGE, text=stage)
            return
        # yt-dlp calls the hook for every few kilobytes; a few redraws a second are enough.
        now, last = time.monotonic(), getattr(self, "_last_progress", None)
        if d.get("status") == "downloading" and last is not None and now - last < PROGRESS_INTERVAL:
            return
        progress = events.progress_from_hook(d)
        if progress is not None:
            self._last_progress = now
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
            ytdlp = self.update_ytdlp()
            self.events.post(events.UPDATE_CHECKED, release=release, error=error, manual=manual, ytdlp=ytdlp)

        self._update_thread = threading.Thread(target=work, name="orbida-update-check", daemon=True)
        self._update_thread.start()

    def update_ytdlp(self):
        """Worker thread: download a newer yt-dlp for the next start.

        Returns the version downloaded, or None (up to date, or the check
        failed; that is only logged, since the bundled yt-dlp still works).
        """
        try:
            return ytdlp_updates.update(app_setup.ytdlp_dir(), lambda url: updates._open(url, "*/*"),
                                        cancelled=lambda: self._closing)
        except Exception as e:  # never let a check break the app
            _log.info("yt-dlp update failed: %s", e)
            return None

    def _set_update_status(self, text):
        ready = self._ytdlp_ready
        if ready and text is not None:
            first = text
            text = lambda: f"{first()}\n{tr('update.ytdlp_ready', version=ready)}"  # noqa: E731
        self._update_status = text
        if self.settings_view is not None:
            self.settings_view.show_update_status(text)

    def _on_update_checked(self, release, error, manual, ytdlp=None):
        if ytdlp:
            self._ytdlp_ready = ytdlp
            self._append_log(tr("update.ytdlp_ready", version=ytdlp))
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
            self.btn_update.pack(side="left", padx=(0, 8), before=self.nav)

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
            if self.instance is not None:
                self.instance.acquire()  # the app stays open: keep a second copy out again
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
