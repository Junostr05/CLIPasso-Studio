{ The uninstaller (installer.iss and patch.iss: every setup writes its own uninstaller, so a patch must
  bring the same code). Needs the defines OtherEdition and AppDataName. }

const
  AppGuid = '{7C1E2B64-3F7A-4E56-9B8B-C1A55C0D2A11}';
  ReparsePoint = $400;

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
