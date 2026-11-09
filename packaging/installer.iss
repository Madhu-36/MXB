; MXB installer script for Inno Setup 6.3+ (Inno Setup 7 reads it unchanged).
; Built by packaging\build.ps1, which runs:
;     ISCC.exe /DAppVersion=4.1.0 /DAppVersionNumeric=4.1.0 packaging\installer.iss
;
; - Per-user install: no admin prompt. Goes to %LOCALAPPDATA%\Programs\MXB.
; - User data (config, memory, documents index, audit log) lives in %APPDATA%\MXB and is
;   never touched by upgrades or uninstall.
; - "Start with Windows" is owned by MXB itself (setup wizard / "start with windows"), so an
;   upgrade can never silently re-enable it. Uninstall removes it.
; - MXB's updater runs this installer with /SILENT after MXB exits; the skipifnotsilent entry
;   in [Run] relaunches MXB when the upgrade finishes.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppVersionNumeric
  #define AppVersionNumeric AppVersion
#endif
#define AppName "MXB"
#define AppExe "MXB.exe"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"

[Setup]
AppId=MXB.DesktopCompanion
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=MXB contributors
AppPublisherURL=https://github.com/Madhu-36/MXB
AppSupportURL=https://github.com/Madhu-36/MXB/issues
AppUpdatesURL=https://github.com/Madhu-36/MXB/releases
VersionInfoVersion={#AppVersionNumeric}
DefaultDirName={autopf}\MXB
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist
OutputBaseFilename=MXB-Setup-{#AppVersion}
SetupIconFile=mxb.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; PyInstaller 6 keeps everything except MXB.exe in _internal. Clear it on upgrade so files a
; newer version no longer ships can't linger and get loaded by mistake.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\MXB\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Interactive install: offer to launch (first launch shows MXB's setup wizard).
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Silent install = MXB's own updater: bring MXB back once the upgrade is done.
Filename: "{app}\{#AppExe}"; Flags: nowait skipifnotsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, '{#RunKey}', 'MXB');
end;
