# -*- mode: python ; coding: utf-8 -*-
# The only build definition. Run it through build_app.py, which checks the
# inputs first and records checksums; see docs/building.md.
import os
import sys

from PyInstaller.utils.hooks import collect_all

sys.path.insert(0, SPECPATH)
from version import APP_NAME, __version__  # noqa: E402

datas = [('app.ico', '.'), ('app.png', '.'), ('THIRD_PARTY_NOTICES.md', '.')]
binaries = [(os.path.join('bin', 'ffmpeg.exe'), 'bin'), (os.path.join('bin', 'ffprobe.exe'), 'bin')]
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f'{APP_NAME}-{__version__}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed executables trigger more antivirus false positives.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
)
