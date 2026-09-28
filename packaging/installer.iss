; Inno Setup 6 script. Built by scripts/build.ps1, which passes /DAppVersion=x.y.z.
; Per-user install: no admin prompt, installs to %LOCALAPPDATA%\Programs\SnapNarrate.
; User settings live in %APPDATA%\SnapNarrate and survive upgrades and uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C1B7C35-5E0B-4F6E-9D57-3F4C2D9A1E21}
AppName=SnapNarrate
AppVersion={#AppVersion}
AppVerName=SnapNarrate {#AppVersion}
AppPublisher=SnapNarrate
DefaultDirName={localappdata}\Programs\SnapNarrate
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=SnapNarrate-Setup-{#AppVersion}
SetupIconFile=..\assets\snapnarrate.ico
UninstallDisplayIcon={app}\SnapNarrate.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Must match MUTEX_NAME in src/snap_narrate/windows.py: lets setup close a running copy.
AppMutex=SnapNarrateSingleInstance
CloseApplications=yes
VersionInfoVersion={#AppVersion}

[Tasks]
Name: "startup"; Description: "Start SnapNarrate when I sign in"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\SnapNarrate\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; Remove files from the previous version's _internal folder before copying the new one.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\SnapNarrate"; Filename: "{app}\SnapNarrate.exe"
Name: "{userdesktop}\SnapNarrate"; Filename: "{app}\SnapNarrate.exe"; Tasks: desktopicon

[Registry]
; Same command line as StartupManager.launch_command() so the in-app toggle and installer agree.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SnapNarrate"; \
  ValueData: """{app}\SnapNarrate.exe"" run --config ""{userappdata}\SnapNarrate\config.toml"""; Tasks: startup
; Always remove the Run entry on uninstall, even if it was turned on from inside the app.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "SnapNarrate"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\SnapNarrate.exe"; Description: "Launch SnapNarrate"; Flags: nowait postinstall skipifsilent
