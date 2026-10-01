; Inno Setup script for CLIPasso Studio.
; Compile with:  ISCC.exe /DEdition=CPU /DSourceDir=..\dist\CLIPassoStudio /DOutputDir=..\release installer.iss
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
  #define AppVersion "2.4.0"
#endif

#define AppName "CLIPasso Studio"
#define AppExe "CLIPassoStudio.exe"

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

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\CLIPasso Studio ({#Edition})"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,CLIPasso Studio}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CLIPasso Studio"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,CLIPasso Studio}"; Flags: nowait postinstall skipifsilent
; an update installed from within the app (silent, /UPDATE) starts the new version right away
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: IsAppUpdate

[Code]
function IsAppUpdate: Boolean;
begin
  Result := WizardSilent and (Pos('/UPDATE', Uppercase(GetCmdTail)) > 0);
end;
