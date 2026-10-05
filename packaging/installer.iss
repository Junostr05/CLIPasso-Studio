; Inno Setup script for CLIPasso Studio.
; Compile with:  ISCC.exe /DEdition=CPU /DAppVersion=x.y.z /DSourceDir=..\dist\CLIPassoStudio /DOutputDir=..\release installer.iss
; The GPU edition is larger than 2 GB and is split into Setup.exe + *.bin slices (DiskSpanning).

#ifndef Edition
  #define Edition "CPU"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\CLIPassoStudio"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif
#ifndef AppVersion
  #error Pass the version: /DAppVersion=x.y.z (the CI takes it from clipasso_studio.__version__)
#endif

#define AppName "CLIPasso Studio"
#define AppExe "CLIPassoStudio.exe"
; the app data folder %LOCALAPPDATA%\<clipasso_studio.APP_ID>
#define AppDataName "CLIPassoStudio"
; both editions can be installed side by side: their shortcuts need different names
#if Edition == "GPU"
  #define ShortcutName "CLIPasso Studio GPU"
  #define OtherEdition "CPU"
#else
  #define ShortcutName "CLIPasso Studio"
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
DefaultGroupName=CLIPasso Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=CLIPassoStudio-{#Edition}-Setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
WizardImageFile=wizard_large.bmp
WizardSmallImageFile=wizard_small.bmp
LicenseFile=license_notice.txt
Compression=lzma2/fast
SolidCompression=no
#if Edition == "GPU"
DiskSpanning=yes
DiskSliceSize=1900000000
SlicesPerDisk=1
#endif

[Languages]
; Setup picks the Windows display language; the first entry is the fallback for all other languages
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; the libraries of the previous version: files it had and this one does not would stay and could be
; loaded instead of the new ones (e.g. another PyTorch / CUDA build)
Type: filesandordirs; Name: "{app}\_internal"
; shortcut names up to 2.4 (the uninstall shortcut was the same for both editions: the CPU edition,
; which keeps that name, replaces it)
Type: files; Name: "{group}\CLIPasso Studio ({#Edition}).lnk"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#ShortcutName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#ShortcutName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#ShortcutName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#ShortcutName}}"; Flags: nowait postinstall skipifsilent
; an update installed from within the app (silent, /UPDATE) starts the new version right away
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: IsAppUpdate

[CustomMessages]
english.DeleteData=Also delete the downloaded models and the app data (settings, caches, logs), %1?%n%nYour sketches stay where they are.
german.DeleteData=Auch die geladenen Modelle und die App-Daten (Einstellungen, Zwischenspeicher, Logs) löschen, %1?%n%nDeine Skizzen bleiben, wo sie sind.

[Code]
function IsAppUpdate: Boolean;
begin
  Result := WizardSilent and (Pos('/UPDATE', Uppercase(GetCmdTail)) > 0);
end;

#include "uninstall_code.iss"
