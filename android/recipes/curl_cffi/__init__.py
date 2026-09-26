"""Installs curl_cffi, which lets yt-dlp impersonate a browser (TikTok needs it).

PyPI has an Android wheel for 64-bit ARM phones only, so other
architectures (the x86_64 emulator in CI) build without it; yt-dlp then
simply has no impersonation. cffi comes from python-for-android's recipe.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wheel_recipe import WheelRecipe  # noqa: E402


class CurlCffiRecipe(WheelRecipe):
    version = "0.16.3"
    depends = ["python3", "cffi"]
    wheels = {"arm64-v8a": (
        "https://files.pythonhosted.org/packages/fb/f4/3dedff1a31c93a9b18acaa346e23832c29bc18075138e90e9af795188e5e/"
        "curl_cffi-0.16.3-cp314-cp314-android_24_arm64_v8a.whl",
        "0c8b70191dc88ea770a5c39d7e213bff1606e248c13566777e6527f0d8cf96ec")}


recipe = CurlCffiRecipe()
