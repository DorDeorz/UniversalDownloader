# -*- mode: python ; coding: utf-8 -*-
# The only build definition. Run it through build_app.py, which checks the
# inputs first and records checksums; see docs/building.md.
import os
import sys

from PyInstaller.utils.hooks import collect_all

sys.path.insert(0, SPECPATH)
from version import APP_NAME, __version__  # noqa: E402

# UVD_ONEDIR=1 builds a folder (for the installer: fast start, nothing
# unpacked on every launch); otherwise one portable EXE.
ONEDIR = os.environ.get('UVD_ONEDIR') == '1'

datas = [('app.ico', '.'), ('app.png', '.'), ('THIRD_PARTY_NOTICES.md', '.'), ('locales', 'locales')]
binaries = [(os.path.join('bin', 'ffmpeg.exe'), 'bin'), (os.path.join('bin', 'ffprobe.exe'), 'bin')]
# Deno runs YouTube's JavaScript challenges. It sits next to FFmpeg, whose
# folder the app puts first on PATH, where yt-dlp looks for it. Only the
# folder build takes it: in a single EXE it would be unpacked on every start.
if ONEDIR and os.path.isfile(os.path.join('bin', 'deno.exe')):
    binaries.append((os.path.join('bin', 'deno.exe'), 'bin'))
hiddenimports = []
for package in ('customtkinter', 'yt_dlp_ejs'):
    tmp_ret = collect_all(package)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe_options = dict(
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed executables trigger more antivirus false positives.
    upx=False,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
)

if ONEDIR:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME, **exe_options)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[], name=APP_NAME)
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=f'{APP_NAME}-{__version__}', runtime_tmpdir=None,
              **exe_options)
