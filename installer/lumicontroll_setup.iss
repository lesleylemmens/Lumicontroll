#define AppName "LumiControLL"
#define AppVersion "1.0"
#define AppPublisher "Lesley Lemmens"
#define AppExeName "lumicontroll.exe"

[Setup]
AppId={{D9D4C741-7B37-4B4D-9E5C-7E887E4F2B75}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\installer_output
OutputBaseFilename=lumicontroll setup
SetupIconFile=..\dist\an.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
Name: "{commonappdata}\LumiControLL"; Permissions: users-modify

[Files]
Source: "..\dist\lumicontroll.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\viewer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\viewer.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\libusb-1.0.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\an.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\dist\readme.pdf"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\dist\zadig-2.9.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\dist\settings.config"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\sound_settings.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\adm.config"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\shows\*"; DestDir: "{app}\shows"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\third_party_licenses\*"; DestDir: "{app}\third_party_licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\an.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\an.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
  ResultCode: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{commonappdata}\LumiControLL');
    if DirExists(DataDir) then
    begin
      ResultCode := MsgBox(
        'Wil je ook de LumiControLL gebruikersdata verwijderen?' + #13#10#13#10 +
        'Dit verwijdert settings, shows en geluidsinstellingen uit:' + #13#10 +
        DataDir,
        mbConfirmation,
        MB_YESNO
      );
      if ResultCode = IDYES then
      begin
        DelTree(DataDir, True, True, True);
      end;
    end;
  end;
end;
