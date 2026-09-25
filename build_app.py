import PyInstaller.__main__
import os
import re

# Dosya yolları
ffmpeg_path = os.path.join("bin", "ffmpeg.exe")
ffprobe_path = os.path.join("bin", "ffprobe.exe")
icon_file = "app.ico"  # Sadece ICO kullanıyoruz

# Versiyonlama
dist_folder = "dist"
base_name = "UniversalDownloader"
version = 1
if not os.path.exists(dist_folder): os.makedirs(dist_folder)
existing_files = os.listdir(dist_folder)
versions = []
for f in existing_files:
    match = re.search(r'UniversalDownloader_v(\d+)\.exe', f)
    if match: versions.append(int(match.group(1)))
if versions: version = max(versions) + 1
exe_name = f"{base_name}_v{version:02d}"
print(f"🚀 BUILDING VERSION: {exe_name}...")

# İkon kontrolü
if not os.path.exists(icon_file):
    print("❌ HATA: app.ico bulunamadı!")
    exit()

separator = ';' if os.name == 'nt' else ':'

# Build Komutu
PyInstaller.__main__.run([
    'main.py',
    f'--name={exe_name}',
    '--onefile',
    '--windowed',
    f'--icon={icon_file}',        # EXE İkonu
    f'--add-binary={ffmpeg_path}{separator}bin',
    f'--add-binary={ffprobe_path}{separator}bin',
    f'--add-data={icon_file}{separator}.',   # İkonu EXE içine göm
    '--collect-all=customtkinter',
    '--clean',
    '--noconfirm'
])
print(f"✅ COMPLETED! Output: dist/{exe_name}.exe")