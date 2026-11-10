; Echo 安装包脚本（Inno Setup 6）
; 先运行 build.bat 生成 dist\Echo\Echo.exe，再用本脚本编译。

#define MyAppName "Echo"
#define MyAppVersion "2.2.0"
#define MyAppPublisher "Echo"
#define MyAppExeName "Echo.exe"
; 产物名后缀。build_release.py --with-model 会传 /DMyAppSuffix=-with-model，
; 让「带语音模型的胖包」和默认的瘦包并存，不互相覆盖。
#ifndef MyAppSuffix
  #define MyAppSuffix ""
#endif

[Setup]
AppId={code:EchoAppId}
UsePreviousLanguage=no
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
#ifdef ECHO_PREVIEW
OutputBaseFilename=Echo-Installer-Preview
#else
OutputBaseFilename=Echo-Setup-{#MyAppVersion}{#MyAppSuffix}
#endif
SetupIconFile=..\assets\echo.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern dark hidebevels
WizardBackColor=$001E1D1B
WizardSizePercent=120,120
DisableWelcomePage=yes
DisableDirPage=yes
DisableReadyPage=yes
DisableFinishedPage=no
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=no
SetupLogging=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Files]
; 语音识别模型不再随包分发（483MB 的大头）—— 第一次开课时后台下载到 %APPDATA%\Echo\models
#ifndef ECHO_PREVIEW
Source: "..\dist\Echo\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Check: not IsQAInstall
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Check: WantDesktopIcon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

#include "echo_wizard.iss"
