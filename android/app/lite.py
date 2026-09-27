"""Light list rows for the Settings and History tabs and the choice dialogs.

KivyMD 2's ``MDListItem`` is made of eight to ten widgets (leading, text and
trailing containers, an ``MDLabel`` per line), each with hover, ripple,
state-layer and theme behaviour and dozens of kv bindings. Building the
Settings tab took about 160 of them and a quarter of a second on a desktop
CPU, several times that on a phone, and every choice dialog paid the same
again before it could open.

These rows draw the same Material 3 list item (sizes, fonts and colours
from KivyMD's theme) with plain Kivy labels: three to five widgets a row
and a handful of bindings, so the tabs and dialogs open without the wait.
Colours are bound to ``app.theme_cls``, so a theme change recolours them
without rebuilding.
"""

from kivy.lang import Builder
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivymd.icon_definitions import md_icons


def glyph(name):
    """The Material Design Icons character for ``name`` ("" if unknown)."""
    return md_icons.get(name, "")


class LiteIcon(Label):
    icon = StringProperty()
    accent = BooleanProperty(False)  # drawn in the primary colour (a chosen radio button)


class LiteText(Label):
    """One line of list text, cut with "…" when it does not fit."""


class LiteWrappedText(LiteText):
    """List text that wraps onto as many lines as it needs."""


class LiteHeadline(LiteWrappedText):
    """A row's main text when it may wrap (switch rows)."""


class LiteSection(LiteText):
    """A section heading ("Appearance", "Downloads"…) in the primary colour."""


class LiteRow(ButtonBehavior, BoxLayout):
    """A one- to three-line list item with a leading and an optional trailing icon.

    Only the lines and icons in use are made (a choice dialog row is three
    widgets), and they appear when their text is first set.
    """

    icon = StringProperty()
    accent = BooleanProperty(False)
    headline = StringProperty()
    supporting = StringProperty()
    tertiary = StringProperty()
    trailing = StringProperty()

    def __init__(self, **kwargs):
        self._lines = {}
        self._trailing = None
        super().__init__(**kwargs)
        self._sync()

    def on_supporting(self, *_):
        self._sync()

    def on_tertiary(self, *_):
        self._sync()

    def on_trailing(self, *_):
        self._sync()

    def _sync(self):
        texts = self.ids.get("texts")
        if texts is None:  # still being made; __init__ calls again
            return
        for name in ("supporting", "tertiary"):
            text = getattr(self, name)
            label = self._lines.get(name)
            if label is None and text:
                label = self._lines[name] = LiteText()
                # Above the tertiary line if that came first.
                texts.add_widget(label, index=1 if name == "supporting" and "tertiary" in self._lines else 0)
            if label is not None:
                label.text = text
        if self.trailing and self._trailing is None:
            self._trailing = LiteIcon(pos_hint={"center_y": .5})
            self.add_widget(self._trailing)
        if self._trailing is not None:
            self._trailing.icon = self.trailing


KV = r"""
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp
#:import glyph lite.glyph

<LiteIcon>:
    font_name: "Icons"
    font_size: sp(24)
    size_hint: None, None
    size: dp(24), dp(24)
    text: glyph(self.icon)
    halign: "center"
    valign: "middle"
    text_size: self.size
    color: app.theme_cls.primaryColor if self.accent else app.theme_cls.onSurfaceVariantColor

<LiteText>:
    font_name: "Roboto"
    font_size: sp(14)
    size_hint_y: None
    height: self.texture_size[1] if self.text else 0
    text_size: self.width, None
    halign: "left"
    shorten: True
    shorten_from: "right"
    max_lines: 1
    color: app.theme_cls.onSurfaceVariantColor

<LiteWrappedText>:
    shorten: False
    max_lines: 0

<LiteHeadline>:
    font_size: sp(16)
    color: app.theme_cls.onSurfaceColor

<LiteSection>:
    padding: dp(16), dp(20), dp(16), dp(4)
    color: app.theme_cls.primaryColor

<LiteRow>:
    size_hint_y: None
    height: dp(88) if root.tertiary else (dp(72) if root.supporting else dp(56))
    padding: dp(16), 0, dp(24), 0
    spacing: dp(16)
    canvas.before:
        Color:
            # Material 3 pressed state layer: the text colour at 10 %.
            rgba: app.theme_cls.onSurfaceColor[:3] + [0.1 if self.state == "down" else 0]
        Rectangle:
            pos: self.pos
            size: self.size
    LiteIcon:
        icon: root.icon
        accent: root.accent
        pos_hint: {"center_y": .5}
    BoxLayout:
        id: texts
        orientation: "vertical"
        size_hint_y: None
        height: self.minimum_height
        spacing: dp(2)
        pos_hint: {"center_y": .5}
        LiteText:
            text: root.headline
            font_size: sp(16)
            bold: True
            color: app.theme_cls.onSurfaceColor
"""

Builder.load_string(KV)
