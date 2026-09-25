"""python-for-android recipe that adds the prebuilt FFmpeg, ffprobe and QuickJS.

``android/native/build_tools.sh`` builds them per ABI as ``lib<name>.so``,
next to FFmpeg's shared libraries (``libavcodec.so``, ...). This recipe
copies every ``.so`` there into the APK's native libraries, which Android
unpacks into a folder where the app may run them (the manifest keeps
``extractNativeLibs="true"``). ``UD_NATIVE_TOOLS_DIR`` points at the build
output, laid out as ``<dir>/<abi>/lib<name>.so``.
"""

import os

from pythonforandroid.logger import info
from pythonforandroid.recipe import Recipe

TOOLS = ("libffmpeg.so", "libffprobe.so", "libqjs.so", "libavcodec.so", "libavformat.so", "libavutil.so")


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
        libs = sorted(name for name in os.listdir(folder) if name.endswith(".so"))
        info(f"Adding {', '.join(libs)} for {arch.arch} from {folder}")
        self.install_libs(arch, *(os.path.join(folder, name) for name in libs))


recipe = UDToolsRecipe()
