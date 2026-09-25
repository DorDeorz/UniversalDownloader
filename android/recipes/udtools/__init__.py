"""python-for-android recipe that adds the prebuilt FFmpeg, ffprobe and QuickJS.

``android/native/build_tools.sh`` builds them per ABI as ``lib<name>.so``.
This recipe copies them into the APK's native libraries, which Android
unpacks into a folder where the app may run them (the manifest keeps
``extractNativeLibs="true"``). ``UD_NATIVE_TOOLS_DIR`` points at the build
output, laid out as ``<dir>/<abi>/lib<name>.so``.
"""

import os

from pythonforandroid.logger import info
from pythonforandroid.recipe import Recipe

TOOLS = ("libffmpeg.so", "libffprobe.so", "libqjs.so")


class UDToolsRecipe(Recipe):
    version = "1"
    url = None
    depends = []

    def should_build(self, arch):
        return True

    def build_arch(self, arch):
        root = os.environ.get("UD_NATIVE_TOOLS_DIR")
        if not root:
            raise RuntimeError("UD_NATIVE_TOOLS_DIR is not set; run android/native/build_tools.sh first")
        folder = os.path.join(root, arch.arch)
        missing = [name for name in TOOLS if not os.path.isfile(os.path.join(folder, name))]
        if missing:
            raise RuntimeError(f"Missing prebuilt tools for {arch.arch} in {folder}: {', '.join(missing)}")
        info(f"Adding {', '.join(TOOLS)} for {arch.arch} from {folder}")
        self.install_libs(arch, *(os.path.join(folder, name) for name in TOOLS))


recipe = UDToolsRecipe()
