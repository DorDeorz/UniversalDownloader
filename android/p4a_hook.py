"""python-for-android build hook (buildozer.spec: p4a.hook).

p4a writes AndroidManifest.xml from its own template, which has no place
for a Java service with a foreground service type. Android 14+ refuses to
start a foreground service whose manifest entry has no type, so the entry
for DownloadService (java/.../DownloadService.java) is added here, after
p4a has written the manifest and before Gradle builds the APK.
"""

import os

SERVICE = (
    '<service android:name="io.github.dordeorz.universaldownloader.DownloadService"'
    ' android:foregroundServiceType="dataSync" android:exported="false" />'
)


def add_service(manifest):
    """The manifest text with the DownloadService entry (added once)."""
    if "DownloadService" in manifest:
        return manifest
    head, tail = manifest.rsplit("</application>", 1)
    return f"{head}    {SERVICE}\n    </application>{tail}"


def before_apk_assemble(toolchain):
    # p4a runs this hook inside the distribution folder.
    for path in ("src/main/AndroidManifest.xml", "AndroidManifest.xml"):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            with open(path, "w", encoding="utf-8") as f:
                f.write(add_service(text))
            print(f"p4a_hook: DownloadService added to {path}")
