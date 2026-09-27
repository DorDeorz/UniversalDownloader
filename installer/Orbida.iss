; Windows installer for Orbida (Inno Setup 6).
;
; Packs the folder build (python build_app.py --onedir) into one setup EXE:
;   iscc /DAppVersion=1.0.0 installer\Orbida.iss
; Output: dist\Orbida-Setup-<version>.exe
;
; Installs for the current user (no administrator prompt) into
; %LOCALAPPDATA%\Programs\Orbida. Everything the app needs is in the folder:
; Python, the libraries, FFmpeg, ffprobe and Deno. See docs/building.md.
;
; Orbida was called Universal Video Downloader before 1.0.0. The AppId is
; unchanged, so this setup upgrades an existing install in place (in its
; old folder) and removes the old program file and shortcuts.
;
; The in-app updater runs this setup with /SILENT /RELAUNCH=1: setup shows
; only its progress window and starts the new version when it is done.

#ifndef AppVersion
  #error Pass the version: iscc /DAppVersion=1.0.0 installer\Orbida.iss
#endif

#define AppName "Orbida"
#define AppExe "Orbida.exe"
#define SourceDir "..\dist\Orbida"
#define OldAppName "Universal Video Downloader"

[Setup]
; Keep AppId stable: upgrades and the uninstaller find the install by it.
AppId={{e8038cf9-18b8-5008-80cf-c77018ad8eca}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=DorDeorz
AppPublisherURL=https://github.com/DorDeorz/UniversalDownloader
AppSupportURL=https://github.com/DorDeorz/UniversalDownloader/issues
AppUpdatesURL=https://github.com/DorDeorz/UniversalDownloader/releases/latest
DefaultDirName={autopf}\Orbida
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=Orbida-Setup-{#AppVersion}
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
; Left over from Universal Video Downloader 1.0.x.
Type: files; Name: "{app}\UniversalDownloader.exe"
Type: files; Name: "{autoprograms}\{#OldAppName}.lnk"
Type: files; Name: "{autodesktop}\{#OldAppName}.lnk"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; After an in-app update (/SILENT /RELAUNCH=1) start the new version.
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: RelaunchRequested

; Settings, history and logs in %LOCALAPPDATA%\Orbida are kept on
; uninstall, like downloaded videos, so a reinstall keeps the user's choices.

[Code]
function RelaunchRequested: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;
