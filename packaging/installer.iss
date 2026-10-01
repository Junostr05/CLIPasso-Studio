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
const
  AppGuid = '{7C1E2B64-3F7A-4E56-9B8B-C1A55C0D2A11}';
  ReparsePoint = $400;

function IsAppUpdate: Boolean;
begin
  Result := WizardSilent and (Pos('/UPDATE', Uppercase(GetCmdTail)) > 0);
end;

{ ----------------------------------------------------------------- uninstall: models and app data }

function OtherEditionInstalled: Boolean;
var
  Key: String;
begin
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + AppGuid + '_{#OtherEdition}_is1';
  Result := RegKeyExists(HKLM64, Key) or RegKeyExists(HKLM32, Key) or RegKeyExists(HKCU, Key);
end;

function FolderSize(const Dir: String): Int64;
var
  FindRec: TFindRec;
begin
  Result := 0;
  if FindFirst(Dir + '\*', FindRec) then
  try
    repeat
      if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
      begin
        if FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
        begin
          if FindRec.Attributes and ReparsePoint = 0 then  { not into links to other folders }
            Result := Result + FolderSize(Dir + '\' + FindRec.Name);
        end
        else
          Result := Result + FindRec.SizeLow + Int64(FindRec.SizeHigh) * 65536 * 65536;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

function SizeText(Size: Int64): String;
var
  MB: Int64;
begin
  MB := Size div 1000000;
  if MB >= 1000 then
    Result := IntToStr(MB div 1000) + '.' + IntToStr((MB mod 1000) div 100) + ' GB'
  else
    Result := IntToStr(MB) + ' MB';
end;

function IsInside(const Path, Folder: String): Boolean;
begin
  Result := Pos(Lowercase(AddBackslash(Folder)), Lowercase(AddBackslash(Path))) = 1;
end;

function SafeName(const Name: String): Boolean;
begin
  Result := (Name <> '') and (Pos('\', Name) = 0) and (Pos('/', Name) = 0) and (Pos(':', Name) = 0)
    and (Name <> '.') and (Name <> '..');
end;

{ The app writes models_location.txt (the folder of the downloaded models, then the model folders in it)
  and output_location.txt (the output folder). The models in a folder the user chose are removed folder
  by folder: that folder may hold other files. Nothing is removed while the other edition is installed
  (it shares the data), in a silent uninstall, or when the output folder lies inside the app data. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data, Models, Output: String;
  Lines, OutLines: TArrayOfString;
  Size: Int64;
  I: Integer;
  OwnModels: Boolean;
begin
  if (CurUninstallStep <> usPostUninstall) or UninstallSilent or OtherEditionInstalled then
    Exit;
  Data := ExpandConstant('{localappdata}\{#AppDataName}');
  if not DirExists(Data) then
    Exit;
  if LoadStringsFromFile(Data + '\output_location.txt', OutLines) and (GetArrayLength(OutLines) > 0) then
  begin
    Output := Trim(OutLines[0]);
    if (Output <> '') and IsInside(Output, Data) then
      Exit;
  end;
  Size := FolderSize(Data);
  OwnModels := False;
  if LoadStringsFromFile(Data + '\models_location.txt', Lines) and (GetArrayLength(Lines) > 0) then
  begin
    Models := RemoveBackslashUnlessRoot(Trim(Lines[0]));
    OwnModels := (Models <> '') and DirExists(Models) and not IsInside(Models, Data);
    if OwnModels then
      for I := 1 to GetArrayLength(Lines) - 1 do
        if SafeName(Trim(Lines[I])) then
          Size := Size + FolderSize(Models + '\' + Trim(Lines[I]));
  end;
  if MsgBox(FmtMessage(CustomMessage('DeleteData'), [SizeText(Size)]), mbConfirmation,
            MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    Exit;
  if OwnModels then
  begin
    for I := 1 to GetArrayLength(Lines) - 1 do
      if SafeName(Trim(Lines[I])) and DirExists(Models + '\' + Trim(Lines[I])) then
        DelTree(Models + '\' + Trim(Lines[I]), True, True, True);
    RemoveDir(Models);  { only when it is empty now }
  end;
  DelTree(Data, True, True, True);
end;
