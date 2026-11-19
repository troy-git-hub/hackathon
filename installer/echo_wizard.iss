; Original Echo artwork, with Inno providing safe extraction and uninstall.
[Code]
var
  EchoPage: TWizardPage;
  BrandPanel: TPanel;
  BrandArt: TBitmapImage;
  StageTitle, StageHint, BrandStep, Eyebrow: TNewStaticText;
  InstallPath: TNewEdit;
  DesktopChoice: TNewCheckBox;

function IsQAInstall: Boolean;
begin
  Result := ExpandConstant('{param:ECHOQA|0}') = '1';
end;

function InitializeSetup: Boolean;
var
  Args: String;
  Index, ResultCode: Integer;
begin
  Result := True;
  { Older Echo clients supplied UPDATE=1 without the Inno silent flags. }
  if (ExpandConstant('{param:UPDATE|0}') = '1') and (not WizardSilent) then
  begin
    Args := '';
    for Index := 1 to ParamCount do
      Args := Args + ' "' + ParamStr(Index) + '"';
    Args := Args + ' /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CLOSEAPPLICATIONS';
    if not Exec(ExpandConstant('{srcexe}'), Args, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      MsgBox('静默更新未能启动，请稍后重试。', mbError, MB_OK);
    Result := False;
  end;
end;

function EchoAppId(Param: String): String;
begin
  if IsQAInstall then Result := 'Echo.ReleaseVerification.2.2'
#ifdef ECHO_BETA
  else Result := '{F75837B7-7CF6-4738-9B7F-DC8621829B1C}';
#else
  else Result := '{7C1F9A3E-0E4B-4A5C-9E2D-1B3A5F6C8D9E}';
#endif
end;

function WantDesktopIcon: Boolean;
begin
  Result := (not IsQAInstall) and DesktopChoice.Checked;
end;

function EchoText(Parent: TWinControl; Caption: String; X, Y, W, H, Size: Integer; Color: TColor): TNewStaticText;
begin
  Result := TNewStaticText.Create(WizardForm);
  Result.Parent := Parent;
  Result.SetBounds(ScaleX(X), ScaleY(Y), ScaleX(W), ScaleY(H));
  Result.AutoSize := False;
  Result.WordWrap := True;
  Result.Caption := Caption;
  Result.Font.Name := 'Microsoft YaHei UI';
  Result.Font.Size := Size;
  Result.Font.Color := Color;
end;

procedure BrowseEchoFolder(Sender: TObject);
var Folder: String;
begin
  Folder := InstallPath.Text;
  if BrowseForFolder('选择 Echo 的学习角落', Folder, False) then
    InstallPath.Text := AddBackslash(Folder) + 'Echo';
end;

procedure InitializeWizard;
var Browse: TNewButton;
begin
  WizardForm.Font.Name := 'Microsoft YaHei UI';
  WizardForm.ClientWidth := ScaleX(900);
  WizardForm.ClientHeight := ScaleY(560);
  WizardForm.Color := $00262421;
  WizardForm.Caption := 'Echo · 为下一次听懂，准备好';
  WizardForm.MainPanel.Visible := False;
  WizardForm.WizardBitmapImage.Visible := False;
  WizardForm.WizardBitmapImage2.Visible := False;
  WizardForm.WizardSmallBitmapImage.Visible := False;
  WizardForm.Bevel.Visible := False;
  WizardForm.Bevel1.Visible := False;
  BrandPanel := TPanel.Create(WizardForm);
  BrandPanel.Parent := WizardForm;
  BrandPanel.SetBounds(0, 0, ScaleX(330), ScaleY(560));
  BrandPanel.Color := $001B160B;
  BrandPanel.BevelOuter := bvNone;
  BrandArt := TBitmapImage.Create(WizardForm);
  BrandArt.Parent := BrandPanel;
  BrandArt.SetBounds(0, 0, ScaleX(330), ScaleY(560));
  BrandArt.Stretch := True;
  ExtractTemporaryFile('setup-brand.bmp');
  Log('Echo art extracted');
  BrandArt.Bitmap.LoadFromFile(ExpandConstant('{tmp}\setup-brand.bmp'));
  Log('Echo art loaded');
  BrandStep := EchoText(BrandPanel, '01  /  为新一课留个位置', 29, 491, 276, 25, 10, $00CEEDB7);
  Eyebrow := EchoText(WizardForm, '01 / HELLO, ECHO.', 366, 30, 495, 24, 9, $00BDE0A9);
  StageTitle := EchoText(WizardForm, '把 Echo 安顿好，'#13#10'就开始下一课。', 362, 65, 510, 85, 24, $00E9F3F4);
  StageTitle.Font.Style := [fsBold];
  StageHint := EchoText(WizardForm, '你的思路，值得被接住。', 366, 151, 495, 30, 10, $00B4B9B2);
  WizardForm.OuterNotebook.SetBounds(ScaleX(366), ScaleY(207), ScaleX(500), ScaleY(260));
  WizardForm.InnerNotebook.SetBounds(0, 0, ScaleX(500), ScaleY(260));
  WizardForm.BackButton.Visible := False;
  WizardForm.NextButton.SetBounds(ScaleX(742), ScaleY(505), ScaleX(124), ScaleY(36));
  WizardForm.CancelButton.SetBounds(ScaleX(628), ScaleY(505), ScaleX(100), ScaleY(36));
  EchoText(WizardForm, 'ECHO {#MyAppVersion}  /  WINDOWS 64-BIT', 366, 518, 240, 20, 8, $00858D84);
  EchoPage := CreateCustomPage(wpWelcome, '准备安装', '');
  Log('Echo custom page created');
  EchoText(EchoPage.Surface, '让 Echo 住在这里', 0, 0, 480, 26, 12, $00E9F3F4);
  InstallPath := TNewEdit.Create(WizardForm);
  InstallPath.Parent := EchoPage.Surface;
  InstallPath.SetBounds(0, ScaleY(36), ScaleX(392), ScaleY(32));
  InstallPath.Text := WizardDirValue;
  Log('Echo path assigned');
  Browse := TNewButton.Create(WizardForm);
  Browse.Parent := EchoPage.Surface;
  Browse.SetBounds(ScaleX(404), ScaleY(36), ScaleX(94), ScaleY(32));
  Browse.Caption := '换个位置';
  Browse.OnClick := @BrowseEchoFolder;
  DesktopChoice := TNewCheckBox.Create(WizardForm);
  DesktopChoice.Parent := EchoPage.Surface;
  DesktopChoice.SetBounds(0, ScaleY(88), ScaleX(490), ScaleY(28));
  DesktopChoice.Caption := '在桌面留一个 Echo 入口';
  DesktopChoice.Checked := True;
  EchoText(EchoPage.Surface, '字幕跟上讲解，板书接住思路。', 0, 143, 490, 30, 12, $00CEEDB7);
  EchoText(EchoPage.Surface, '语音识别组件可在应用内按需下载。'#13#10'已有的个人资料、课程记录和设置会保留。', 0, 185, 490, 60, 10, $00B4B9B2);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
#ifdef ECHO_PREVIEW
  if CurPageID = EchoPage.ID then begin
    Result := False;
    Exit;
  end;
#endif
  if CurPageID = EchoPage.ID then begin
    if (Length(Trim(InstallPath.Text)) < 3) or
       ((Copy(InstallPath.Text, 2, 2) <> ':\') and (Copy(InstallPath.Text, 1, 2) <> '\\')) then begin
      MsgBox('请选择一个完整的安装路径。', mbError, MB_OK);
      Result := False;
    end else WizardForm.DirEdit.Text := InstallPath.Text;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  WizardForm.MainPanel.Visible := False;
  WizardForm.BackButton.Visible := False;
  if CurPageID = EchoPage.ID then begin
    WizardForm.NextButton.Caption := '安顿好 Echo  →';
  end else if CurPageID = wpInstalling then begin
    Eyebrow.Caption := '02 / MAKING ROOM.';
    StageTitle.Caption := '正在为你，'#13#10'整理一个学习角落。';
    StageHint.Caption := '稍等一下。下一节课，我们一起听。';
    BrandStep.Caption := '02  /  把工具安顿好';
    WizardForm.StatusLabel.SetBounds(0, ScaleY(24), ScaleX(496), ScaleY(40));
    WizardForm.ProgressGauge.SetBounds(0, ScaleY(100), ScaleX(498), ScaleY(12));
    WizardForm.FilenameLabel.Visible := False;
  end else if CurPageID = wpFinished then begin
    Eyebrow.Caption := '03 / YOUR NEXT AHA.';
    StageTitle.Caption := '准备好了。'#13#10'去听懂下一节课吧。';
    StageHint.Caption := '每一次“原来如此”，都值得留下。';
    BrandStep.Caption := '03  /  下一次听懂，见';
    WizardForm.FinishedHeadingLabel.Visible := False;
    WizardForm.FinishedLabel.SetBounds(0, ScaleY(18), ScaleX(496), ScaleY(84));
    WizardForm.FinishedLabel.Caption := 'Echo 已准备就绪。'#13#10#13#10'播放网课，让字幕、板书和学习回响跟上你的思路。';
    WizardForm.RunList.SetBounds(0, ScaleY(136), ScaleX(496), ScaleY(65));
    WizardForm.NextButton.Caption := '开始下一课  →';
  end;
end;

#ifdef ECHO_PREVIEW
procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  Cancel := True;
  Confirm := False;
end;
#endif
