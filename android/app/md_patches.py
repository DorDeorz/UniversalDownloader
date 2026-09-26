"""Works around KivyMD 2.0 behaviour that crashes or slows down real phones.

KivyMD's Material 3 ripple draws every touch through an ``Fbo`` whose shader
is assigned after the ``Fbo`` exists. Qualcomm Adreno drivers (most Xiaomi
and Samsung phones) crash while drawing it, so the app closes on the first
tap: kivymd/KivyMD#1900 and #1508 report the same, and kivy/kivy#8098 fixed
this very pattern in Kivy's own ``BoxShadow``. The emulator's software GPU
draws it fine, which is why CI never saw it.

The app switches the ripple off. Buttons still show the press through their
Material 3 state layer, which draws with plain instructions.

On Android it also switches off mouse hover tracking; see ``disable_hover``.
"""

from kivymd.uix.behaviors.ripple_behavior import M3CommonRipple


def _init_without_fbo(self):
    self.fbo = None
    self._phase = 0.0
    self.ripple_pos = (0, 0)


def disable_gpu_ripple():
    """Stop every KivyMD widget from creating or drawing the ripple ``Fbo``."""
    M3CommonRipple.init_fbos = _init_without_fbo
    M3CommonRipple.call_ripple_animation_methods = lambda self, touch: None
    M3CommonRipple.lay_canvas_instructions = lambda self: None


def disable_hover():
    """Stop KivyMD widgets from following the mouse pointer (for touch screens).

    Every KivyMD button, list item, text field and switch binds itself to
    ``Window.mouse_pos`` when it is made and never lets go. Android turns
    each finger movement into a mouse movement too, so every touch and
    scroll called hundreds of these handlers (and widgets long gone from the
    screen kept being called). A phone has no pointer to hover with.
    """
    from kivymd.uix.behaviors.hover_behavior import HoverBehavior

    def __init__(self, *args, **kwargs):
        super(HoverBehavior, self).__init__(*args, **kwargs)

    HoverBehavior.__init__ = __init__
