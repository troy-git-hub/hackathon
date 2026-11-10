; Echo's own installation flow. Inno handles extraction, rollback and uninstall.
[Code]
var
  EchoPage: TWizardPage;
  BrandPanel: TPanel;
  StageTitle, StageHint, BrandStep: TNewStaticText;
  InstallPath: TNewEdit;
  DesktopChoice: TNewCheckBox;

function IsQAInstall: Boolean;
begin
  Result := ExpandConstant('{param:ECHOQA|0}') = '1';
end;

function EchoAppId(Param: String): String;
begin
  if IsQAInstall then Result := 'Echo.ReleaseVerification.2.2'
  else Result := '{7C1F9A3E-0E4B-4A5C-9E2D-1B3A5F6C8D9E}';
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
  if BrowseForFolder('选择 Echo 的安装位置', Folder, False) then
    InstallPath.Text := AddBackslash(Folder) + 'Echo';
end;

procedure InitializeWizard;
var L: TNewStaticText; Browse: TNewButton;
begin
  WizardForm.Font.Name := 'Microsoft YaHei UI';
  WizardForm.ClientWidth := ScaleX(800);
  WizardForm.ClientHeight := ScaleY(500);
  WizardForm.Color := $001E1D1B;
  WizardForm.Caption := 'Echo · 安装';
  WizardForm.MainPanel.Visible := False;
  WizardForm.WizardBitmapImage.Visible := False;
  WizardForm.WizardBitmapImage2.Visible := False;
  WizardForm.WizardSmallBitmapImage.Visible := False;
  WizardForm.Bevel.Visible := False;
  WizardForm.Bevel1.Visible := False;

  BrandPanel := TPanel.Create(WizardForm);
  BrandPanel.Parent := WizardForm;
  BrandPanel.SetBounds(0, 0, ScaleX(218), ScaleY(500));
  BrandPanel.Color := $00242622;
  BrandPanel.BevelOuter := bvNone;
  L := EchoText(BrandPanel, 'Echo', 28, 36, 165, 52, 32, $00A7DAFF);
  L.Font.Style := [fsBold];
  EchoText(BrandPanel, '听懂这一课。', 30, 105, 158, 40, 15, $00F2F2F2);
  EchoText(BrandPanel, '跟随知识点的板书'#13#10'讲得清楚的互动演示'#13#10'属于你的学习回响', 30, 176, 160, 110, 11, $00BBB5AD);
  BrandStep := EchoText(BrandPanel, '01  准备你的学习空间', 30, 346, 166, 58, 11, $00A7DAFF);
  EchoText(BrandPanel, 'WINDOWS 64-BIT'#13#10'VERSION {#MyAppVersion}', 30, 437, 164, 44, 8, $00928E88);

  StageTitle := EchoText(WizardForm, '欢迎使用 Echo', 250, 32, 510, 40, 23, $00F2F2F2);
  StageTitle.Font.Style := [fsBold];
  StageHint := EchoText(WizardForm, '安装好，然后安心听课。', 252, 78, 500, 36, 10, $00BBB5AD);
  WizardForm.OuterNotebook.SetBounds(ScaleX(250), ScaleY(126), ScaleX(514), ScaleY(294));
  WizardForm.InnerNotebook.SetBounds(0, 0, ScaleX(514), ScaleY(294));
  WizardForm.BackButton.SetBounds(ScaleX(412), ScaleY(449), ScaleX(100), ScaleY(34));
  WizardForm.NextButton.SetBounds(ScaleX(638), ScaleY(449), ScaleX(126), ScaleY(34));
  WizardForm.CancelButton.SetBounds(ScaleX(526), ScaleY(449), ScaleX(100), ScaleY(34));

  EchoPage := CreateCustomPage(wpWelcome, '准备安装', '');
  EchoText(EchoPage.Surface, '安装位置', 0, 4, 480, 26, 11, $00F2F2F2);
  InstallPath := TNewEdit.Create(WizardForm);
  InstallPath.Parent := EchoPage.Surface;
  InstallPath.SetBounds(0, ScaleY(36), ScaleX(410), ScaleY(30));
  InstallPath.Text := WizardDirValue;
  Browse := TNewButton.Create(WizardForm);
  Browse.Parent := EchoPage.Surface;
  Browse.SetBounds(ScaleX(420), ScaleY(36), ScaleX(90), ScaleY(30));
  Browse.Caption := '更改位置';
  Browse.OnClick := @BrowseEchoFolder;
  DesktopChoice := TNewCheckBox.Create(WizardForm);
  DesktopChoice.Parent := EchoPage.Surface;
  DesktopChoice.SetBounds(0, ScaleY(88), ScaleX(500), ScaleY(28));
  DesktopChoice.Caption := '在桌面创建 Echo 快捷方式';
  DesktopChoice.Checked := True;
  EchoText(EchoPage.Surface, '准备开始新的一课', 0, 150, 500, 28, 14, $00A7DAFF);
  EchoText(EchoPage.Surface, '首次打开时设置你的模型服务。语音识别组件可在应用内按需下载。'#13#10#13#10'更新安装会保留已有的课程记录与个人设置。', 0, 190, 500, 96, 10, $00BBB5AD);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
#ifdef ECHO_PREVIEW
  Result := False;
  Exit;
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
    StageTitle.Caption := '让学习，有迹可循。';
    StageHint.Caption := '选择安装位置，即可开始。';
    WizardForm.NextButton.Caption := '安装 Echo  →';
    BrandStep.Caption := '01  准备你的学习空间';
  end else if CurPageID = wpInstalling then begin
    StageTitle.Caption := '正在准备 Echo';
    StageHint.Caption := '把工具安顿好，接下来专心听课。';
    BrandStep.Caption := '02  正在安装';
    WizardForm.StatusLabel.SetBounds(0, ScaleY(20), ScaleX(500), ScaleY(40));
    WizardForm.ProgressGauge.SetBounds(0, ScaleY(88), ScaleX(510), ScaleY(12));
    WizardForm.FilenameLabel.Visible := False;
  end else if CurPageID = wpFinished then begin
    StageTitle.Caption := '你的学习空间，准备好了。';
    StageHint.Caption := '欢迎开始下一节课。';
    BrandStep.Caption := '03  安装完成';
    WizardForm.FinishedHeadingLabel.Visible := False;
    WizardForm.FinishedLabel.SetBounds(0, ScaleY(18), ScaleX(510), ScaleY(84));
    WizardForm.FinishedLabel.Caption := 'Echo 已安装到你的电脑。'#13#10#13#10'播放网课，让板书、互动讲解和学习回响陪你一起理解。';
    WizardForm.RunList.SetBounds(0, ScaleY(125), ScaleX(510), ScaleY(65));
    WizardForm.NextButton.Caption := '完成  →';
  end;
end;
