; Inno Setup script of a patch: updates an installed CLIPasso Studio {FromVersion} to {AppVersion} with only the
; files that changed (tools/manifest.py patch). It has the AppId of installer.iss, so it updates that installation,
; its entry in "Apps" and its uninstaller (which gets the same code, uninstall_code.iss).
; Compile with:  ISCC.exe /DEdition=CPU /DAppVersion=3.3.0 /DFromVersion=3.2.0 /DPatchDir=..\build\patch
;                /DRemovedList=..\build\patch-removed.iss /DOutputDir=..\release patch.iss

#ifndef Edition
  #define Edition "CPU"
#endif
#ifndef AppVersion
  #error Pass the version: /DAppVersion=x.y.z
#endif
#ifndef FromVersion
  #error Pass the version the patch updates: /DFromVersion=x.y.z
#endif
#ifndef PatchDir
  #error Pass the folder with the changed files: /DPatchDir=...
#endif
#ifndef RemovedList
  #error Pass the [InstallDelete] lines of the removed files: /DRemovedList=...
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif

#define AppName "CLIPasso Studio"
#define AppExe "CLIPassoStudio.exe"
#define AppDataName "CLIPassoStudio"
#if Edition == "GPU"
  #define OtherEdition "CPU"
#else
  #define OtherEdition "GPU"
#endif

[Setup]
AppId={{7C1E2B64-3F7A-4E56-9B8B-C1A55C0D2A11}_{#Edition}
AppName={#AppName} ({#Edition})
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} ({#Edition})
AppPublisher=CLIPasso Studio
AppPublisherURL=https://github.com/Junostr05/CLIPasso-Studio
AppSupportURL=https://github.com/Junostr05/CLIPasso-Studio/issues
DefaultDirName={autopf}\CLIPasso Studio {#Edition}
; the folder of the installation it updates
UsePreviousAppDir=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=CLIPassoStudio-{#Edition}-Patch-from-{#FromVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
WizardImageFile=wizard_large.bmp
WizardSmallImageFile=wizard_small.bmp
Compression=lzma2/fast
SolidCompression=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[InstallDelete]
; the files the new version does not have any more
#include RemovedList

[Files]
Source: "{#PatchDir}\*"; Excludes: "removed.txt"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
; started from within the app (silent, /UPDATE): the new version right away
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: IsAppUpdate

[CustomMessages]
english.PatchWrongVersion=This update is for CLIPasso Studio %1, but %2 is installed. Please install the full setup of the new version.
german.PatchWrongVersion=Dieses Update ist für CLIPasso Studio %1, installiert ist aber %2. Bitte installiere das vollständige Setup der neuen Version.
english.DeleteData=Also delete the downloaded models and the app data (settings, caches, logs), %1?%n%nYour sketches stay where they are.
german.DeleteData=Auch die geladenen Modelle und die App-Daten (Einstellungen, Zwischenspeicher, Logs) löschen, %1?%n%nDeine Skizzen bleiben, wo sie sind.

[Code]
#include "update_restart.iss"

{ The installed version (Inno Setup keeps it as DisplayVersion of the app's uninstall entry); '' if there is none. }
function InstalledVersion: String;
var
  Key: String;
begin
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C1E2B64-3F7A-4E56-9B8B-C1A55C0D2A11}_{#Edition}_is1';
  Result := '';
  if not RegQueryStringValue(HKA, Key, 'DisplayVersion', Result) then
    if not RegQueryStringValue(HKCU, Key, 'DisplayVersion', Result) then
      if not RegQueryStringValue(HKLM64, Key, 'DisplayVersion', Result) then
        RegQueryStringValue(HKLM32, Key, 'DisplayVersion', Result);
end;

function InitializeSetup: Boolean;
var
  Installed: String;
begin
  Installed := InstalledVersion;
  Result := Installed = '{#FromVersion}';
  if not Result then
  begin
    SuppressibleMsgBox(FmtMessage(CustomMessage('PatchWrongVersion'), ['{#FromVersion}', Installed]),
                       mbError, MB_OK, IDOK);
    RestartInstalledApp;  { (an update from within the app: the app comes back with the version that is there) }
  end;
end;

#include "uninstall_code.iss"
