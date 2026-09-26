"""Installs charset-normalizer's pure-Python wheel.

Kivy pulls in requests, which needs charset-normalizer. python-for-android
2026.5.9 resolves it to a compiled Android wheel and then fails to install
that wheel with the build machine's pip. The pure-Python wheel works the
same.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wheel_recipe import WheelRecipe  # noqa: E402


class CharsetNormalizerRecipe(WheelRecipe):
    version = "3.5.1"
    wheels = {"any": (
        "https://files.pythonhosted.org/packages/cc/61/d01fc49b8dea277640b55a9e15960dbca9fdc8c9fde18e572d39c59f4019/"
        "charset_normalizer-3.5.1-py3-none-any.whl",
        "6df0ec430f9a831772c23ca5a224cba36517a58a84bb32c32bb59a9fa67c47f6")}


recipe = CharsetNormalizerRecipe()
