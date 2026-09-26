"""Installs KivyMD 2.0 (Material Design 3 widgets for Kivy) without its dependencies.

Through pip, KivyMD would also pull in Pillow and materialshapes. The app
needs neither: Pillow is only used for image colour schemes and
materialshapes only by the loading indicator widget, which the app avoids.
materialyoucolor comes from its own local recipe.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wheel_recipe import WheelRecipe  # noqa: E402


class KivyMDRecipe(WheelRecipe):
    version = "2.0.0"
    depends = ["python3", "kivy", "materialyoucolor"]
    wheels = {"any": (
        "https://files.pythonhosted.org/packages/e6/59/337322d61404c74cafa8a4da71dfe01f84a5dffedda28ba5a4a306fc6430/"
        "kivymd-2.0.0-py3-none-any.whl",
        "403be9715fba6258fb772206e6c9443dc71237881c56279e7b9a2f7bab99e11b")}


recipe = KivyMDRecipe()
