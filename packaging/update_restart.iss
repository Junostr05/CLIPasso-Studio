{ Included by installer.iss and patch.iss. An update started from within the app (silent, /UPDATE) starts the app
  again afterwards, as the user who ran it - also when the update was not installed (refused or failed): then the
  version that is there starts, so the app is never left closed and the phone page comes back by itself. }

var
  UpdateInstalled, AppRestarted: Boolean;

function IsAppUpdate: Boolean;
begin
  Result := WizardSilent and (Pos('/UPDATE', Uppercase(GetCmdTail)) > 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    UpdateInstalled := True;
end;

{ The folder of the installed app (from Inno Setup's uninstall entry); '' if there is none. }
function InstalledFolder: String;
var
  Key: String;
begin
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C1E2B64-3F7A-4E56-9B8B-C1A55C0D2A11}_{#Edition}_is1';
  Result := '';
  if not RegQueryStringValue(HKCU, Key, 'InstallLocation', Result) then
    if not RegQueryStringValue(HKLM64, Key, 'InstallLocation', Result) then
      RegQueryStringValue(HKLM32, Key, 'InstallLocation', Result);
end;

{ The update did not get installed: start the version that is there. }
procedure RestartInstalledApp;
var
  Exe: String;
  ResultCode: Integer;
begin
  if AppRestarted or not IsAppUpdate then
    Exit;
  AppRestarted := True;
  Exe := AddBackslash(InstalledFolder) + '{#AppExe}';
  if FileExists(Exe) then
    ExecAsOriginalUser(Exe, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
end;

procedure DeinitializeSetup;
begin
  if not UpdateInstalled then
    RestartInstalledApp;
end;
