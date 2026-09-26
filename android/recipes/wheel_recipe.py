"""Shared base for the local recipes that install a prebuilt wheel.

python-for-android 2026.5.9 resolves some requirements to Android wheels
from PyPI and then fails to install them with the build machine's pip, and
installing a package through pip also pulls in its dependencies, which may
need native builds the app does not use. A :class:`WheelRecipe` instead
downloads one pinned wheel, checks its SHA-256 and unpacks it straight into
the app's site-packages, without dependencies.

Each recipe folder's ``__init__.py`` puts this folder on ``sys.path`` and
subclasses :class:`WheelRecipe`.
"""

import hashlib
import os
import shlex
import subprocess
import urllib.request
import zipfile

from pythonforandroid.logger import info
from pythonforandroid.recipe import Recipe


class WheelRecipe(Recipe):
    url = None
    depends = ["python3"]
    # {arch name or "any": (url, sha256)}; an arch with no wheel is skipped.
    wheels = {}
    # Files in the wheel to leave out, matched by suffix.
    exclude = ()

    def should_build(self, arch):
        return True

    def wheel_for(self, arch):
        return self.wheels.get(arch.arch) or self.wheels.get("any")

    def build_arch(self, arch):
        wheel = self.wheel_for(arch)
        if wheel is None:
            info(f"{self.name}: no wheel for {arch.arch}; the app runs without it there")
            return
        url, sha256 = wheel
        path = self.fetch_wheel(url, sha256)
        target = self.ctx.get_site_packages_dir(arch)
        info(f"Unpacking {os.path.basename(path)} into {target}")
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if not n.endswith(tuple(self.exclude))]
            archive.extractall(target, members=names)
        self.strip_native(arch, [os.path.join(target, n) for n in names if n.endswith(".so")])

    def fetch_wheel(self, url, sha256):
        folder = os.path.join(self.ctx.packages_path, self.name)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, os.path.basename(url))
        if not os.path.isfile(path):
            urllib.request.urlretrieve(url, path)
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        if digest != sha256:
            os.remove(path)
            raise RuntimeError(f"{path}: SHA-256 {digest} does not match {sha256}")
        return path

    def strip_native(self, arch, paths):
        """Drop debug symbols; python-for-android does not strip site-packages."""
        if not paths:
            return
        strip = shlex.split(arch.get_env()["STRIP"])
        for path in paths:
            before = os.path.getsize(path)
            subprocess.run([*strip, path], check=True)
            info(f"Stripped {os.path.basename(path)}: {before >> 20} MB -> {os.path.getsize(path) >> 20} MB")
