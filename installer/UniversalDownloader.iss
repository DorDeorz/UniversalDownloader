; Windows installer for Universal Video Downloader (Inno Setup 6).
;
; Packs the folder build (python build_app.py --onedir) into one setup EXE:
;   iscc /DAppVersion=1.0.0 installer\UniversalDownloader.iss
; Output: dist\UniversalDownloader-Setup-<version>.exe
;
; Installs for the current user (no administrator prompt) into
; %LOCALAPPDATA%\Programs\UniversalDownloader. Everything the app needs is in
; the folder: Python, the libraries, FFmpeg, ffprobe and Deno.
; See docs/building.md.

#ifndef AppVersion
  #error Pass the version: iscc /DAppVersion=1.0.0 installer\UniversalDownloader.iss
#endif

#define AppName "Universal Video Downloader"
#define AppExe "UniversalDownloader.exe"
#define SourceDir "..\dist\UniversalDownloader"

[Setup]
; Keep AppId stable: upgrades and the uninstaller find the install by it.
AppId={{e8038cf9-18b8-5008-80cf-c77018ad8eca}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=DorDeorz
AppPublisherURL=https://github.com/DorDeorz/UniversalDownloader
AppSupportURL=https://github.com/DorDeorz/UniversalDownloader/issues
DefaultDirName={autopf}\UniversalDownloader
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=UniversalDownloader-Setup-{#AppVersion}
SetupIconFile=..\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; The app holds this mutex while it runs (app_setup.SingleInstance), so
; setup and uninstall ask the user to close it first.
AppMutex=Local\DorDeorz.UniversalDownloader
CloseApplications=yes
LicenseFile=..\THIRD_PARTY_NOTICES.md

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; An upgrade replaces the whole program folder, so no stale files survive.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Settings and logs in %LOCALAPPDATA%\UniversalDownloader are kept on
; uninstall, like downloaded videos, so a reinstall keeps the user's choices.
