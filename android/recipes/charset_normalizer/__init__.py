"""Installs charset-normalizer's pure-Python wheel.

Kivy pulls in requests, which needs charset-normalizer. python-for-android
2026.5.9 resolves it to a compiled Android wheel and then fails to install
that wheel with the build machine's pip. The pure-Python wheel works the
same, so this recipe unpacks it straight into the app's site-packages.
"""

import hashlib
import os
import urllib.request
import zipfile

from pythonforandroid.logger import info
from pythonforandroid.recipe import Recipe

WHEEL_URL = ("https://files.pythonhosted.org/packages/cc/61/d01fc49b8dea277640b55a9e15960dbca9fdc8c9fde18e572d39c59f4019/"
             "charset_normalizer-3.5.1-py3-none-any.whl")
WHEEL_SHA256 = "6df0ec430f9a831772c23ca5a224cba36517a58a84bb32c32bb59a9fa67c47f6"


class CharsetNormalizerRecipe(Recipe):
    version = "3.5.1"
    url = None
    depends = ["python3"]

    def should_build(self, arch):
        return True

    def build_arch(self, arch):
        folder = os.path.join(self.ctx.packages_path, self.name)
        os.makedirs(folder, exist_ok=True)
        wheel = os.path.join(folder, os.path.basename(WHEEL_URL))
        if not os.path.isfile(wheel):
            urllib.request.urlretrieve(WHEEL_URL, wheel)
        with open(wheel, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        if digest != WHEEL_SHA256:
            os.remove(wheel)
            raise RuntimeError(f"{wheel}: SHA-256 {digest} does not match {WHEEL_SHA256}")
        target = self.ctx.get_site_packages_dir(arch)
        info(f"Unpacking {os.path.basename(wheel)} into {target}")
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(target)


recipe = CharsetNormalizerRecipe()
