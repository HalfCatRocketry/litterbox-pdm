; Inno Setup script: packs dist\Litterbox\ into one Litterbox-Setup-X.Y.Z.exe.
; Built by the release pipeline:  ISCC.exe /DAppVersion=0.1.0 packaging\installer.iss
;
; Per-user install (no administrator rights, nothing to approve): it goes in
; %LOCALAPPDATA%\Programs\Litterbox. Your settings, logs and vault live in C:\Litterbox and are never touched,
; not even by uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7A2A8C0B-2CAC-4E66-A63B-73828FEC23D2}
AppName=Litterbox
AppVersion={#AppVersion}
AppPublisher=Litterbox PDM
AppPublisherURL=https://github.com/
DefaultDirName={autopf}\Litterbox
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=Litterbox-Setup-{#AppVersion}
SetupIconFile=..\app\litterbox\gui\assets\litterbox_icon_white.ico
UninstallDisplayIcon={app}\Litterbox.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; An update runs while Litterbox might still be open: close it, replace the files, and (see [Run]) start it again.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Litterbox\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Litterbox"; Filename: "{app}\Litterbox.exe"
Name: "{autodesktop}\Litterbox"; Filename: "{app}\Litterbox.exe"; Tasks: desktopicon

[Run]
; Also runs after a quiet update (no skipifsilent), which is how Litterbox comes back after updating itself.
Filename: "{app}\Litterbox.exe"; Description: "Start Litterbox"; Flags: nowait postinstall

[Code]
// Litterbox runs the real git and git lfs commands, so both must be installed. We can't install them for you
// (they are other people's programs); this just says so, once, instead of leaving a mystery error later.
function CommandWorks(const Command: String): Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/C ' + Command + ' >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, Code)
            and (Code = 0);
end;

function InitializeSetup(): Boolean;
var
  Missing, NewLine, Text: String;
begin
  Result := True;
  if WizardSilent then
    Exit;
  Missing := '';
  if not CommandWorks('git --version') then
    Missing := 'Git for Windows'
  else if not CommandWorks('git lfs version') then
    Missing := 'Git LFS (it comes with Git for Windows)';
  if Missing <> '' then
  begin
    // NewLine is built here, and no line below starts with a "#": the Inno Setup preprocessor would read that as
    // one of its own directives.
    NewLine := Chr(13) + Chr(10);
    Text := 'Litterbox needs ' + Missing + ', which was not found on this computer.' + NewLine + NewLine;
    Text := Text + 'You can install Litterbox now and Git afterwards. Get Git for Windows (it includes Git LFS) from:';
    Text := Text + NewLine + 'https://git-scm.com/download/win';
    MsgBox(Text, mbInformation, MB_OK);
  end;
end;
