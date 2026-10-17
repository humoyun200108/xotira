; Xotira installer — per-user, no administrator rights needed.
; Contents: the official embeddable Python (signed by the Python Software Foundation) + Xotira's readable source.
; Build with installer\build.ps1 (it stages the files and passes the version).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef RepoUrl
  #define RepoUrl "https://github.com/humoyun200108/xotira"
#endif

[Setup]
AppId={{8C1B7F2A-5E44-4C59-9E4A-6A2E1F0B7D31}
AppName=Xotira
AppVersion={#AppVersion}
AppVerName=Xotira {#AppVersion}
AppPublisher=Humoyun Safarov
AppPublisherURL={#RepoUrl}
AppSupportURL=https://t.me/humoyunsafarov
AppUpdatesURL={#RepoUrl}/releases
AppCopyright=Copyright (c) 2026 Humoyun Safarov. MIT License.
AppComments=Smart disk cleaner for Windows: explains why your disk is full and frees space safely.
DefaultDirName={localappdata}\Programs\Xotira
DefaultGroupName=Xotira
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=Xotira-Setup-{#AppVersion}
SetupIconFile=..\app\assets\xotira.ico
UninstallDisplayIcon={app}\app\assets\xotira.ico
UninstallDisplayName=Xotira
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany=Humoyun Safarov
VersionInfoDescription=Xotira - smart disk cleaner setup
VersionInfoProductName=Xotira
VersionInfoProductVersion={#AppVersion}
VersionInfoCopyright=Copyright (c) 2026 Humoyun Safarov

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\build\stage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Xotira"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\launcher.pyw"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\assets\xotira.ico"; Comment: "Xotira - smart disk cleaner"
Name: "{autodesktop}\Xotira"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\launcher.pyw"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\assets\xotira.ico"; Comment: "Xotira - smart disk cleaner"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\launcher.pyw"""; WorkingDir: "{app}\app"; Description: "{cm:LaunchProgram,Xotira}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\launcher.pyw"" --quit"; Flags: runhidden waituntilterminated; RunOnceId: "QuitXotira"

[UninstallDelete]
; app files, the window profile, history and log — a disk cleaner should leave nothing behind
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{localappdata}\Xotira"

[Code]
// stop a running Xotira before files are replaced on upgrade
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Py: String;
begin
  Py := ExpandConstant('{app}\runtime\pythonw.exe');
  if FileExists(Py) then
    Exec(Py, '"' + ExpandConstant('{app}\app\launcher.pyw') + '" --quit', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
