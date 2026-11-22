; Inno Setup script. Build: iscc /DMyAppVersion=0.1.0 installer\edi_assistant.iss  (run from repo root or anywhere)
#if Ver < EncodeVer(6,3,0)
  #error Inno Setup 6.3 or newer is required (ArchitecturesInstallIn64BitMode=x64compatible)
#endif
#ifndef MyAppVersion
  #define MyAppVersion "0.1.6"
#endif

[Setup]
AppId={{B5B7B8D2-6C1B-4F4C-9E7B-EDIASSIST0001}
AppName=EDI Assistant
AppVersion={#MyAppVersion}
AppPublisher=SHYFT GLOBAL LLC
DefaultDirName={localappdata}\Programs\EDI Assistant
DefaultGroupName=EDI Assistant
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=EDI-Assistant-Setup-{#MyAppVersion}
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
SetupIconFile=..\edi_assistant\app\resources\app.ico
UninstallDisplayIcon={app}\EDI Assistant.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.AutostartTask=Start with Windows
english.DesktopIconTask=Create a desktop icon
english.RemoveUserData=Delete user data (settings, templates, factories) in AppData\Roaming\EDI Assistant and AppData\Local\EDI Assistant?

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIconTask}"; Flags: unchecked
Name: "autostart"; Description: "{cm:AutostartTask}"; Flags: unchecked

[Files]
Source: "..\dist\EDI Assistant\*"; DestDir: "{app}"; Excludes: "portable.flag"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README_VI.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\EDI Assistant"; Filename: "{app}\EDI Assistant.exe"; AppUserModelID: "ShyftGlobal.EDIAssistant"
Name: "{autodesktop}\EDI Assistant"; Filename: "{app}\EDI Assistant.exe"; Tasks: desktopicon; AppUserModelID: "ShyftGlobal.EDIAssistant"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "EDIAssistant"; ValueData: """{app}\EDI Assistant.exe"" --minimized"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\EDI Assistant.exe"; Description: "EDI Assistant"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox(ExpandConstant('{cm:RemoveUserData}'), mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(ExpandConstant('{userappdata}\EDI Assistant'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\EDI Assistant'), True, True, True);
    end;
  end;
end;
