"""Installs materialyoucolor 3.0.4, the Material You colour maths KivyMD 2.0 needs.

python-for-android's own recipe builds version 2.0.10, older than KivyMD
2.0 accepts. The Android wheels on PyPI carry the image quantizer as a C++
module named for desktop Linux, which Android's Python would never load;
KivyMD does not use it (the import is optional), so it is left out and the
pure-Python rest is installed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wheel_recipe import WheelRecipe  # noqa: E402


class MaterialYouColorRecipe(WheelRecipe):
    version = "3.0.4"
    exclude = (".so",)
    wheels = {"any": (
        "https://files.pythonhosted.org/packages/76/22/209bdd523c8f710ffc76558194d900c7fad004d43ebc46066c215e7b6761/"
        "materialyoucolor-3.0.4-cp314-cp314-android_24_arm64_v8a.whl",
        "8afb469e297b6d3ee47f8e6149943aaa8829838d934e5bc53caf4d4d2f599713")}


recipe = MaterialYouColorRecipe()
