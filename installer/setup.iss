; Echo 安装包脚本（Inno Setup 6）
; 先运行 build.bat 生成 dist\Echo\Echo.exe，再用本脚本编译。

#define MyAppName "Echo"
#define MyAppVersion "2.1"
#define MyAppPublisher "Echo"
#define MyAppExeName "Echo.exe"

[Setup]
AppId={{7C1F9A3E-0E4B-4A5C-9E2D-1B3A5F6C8D9E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Echo-Setup-{#MyAppVersion}
SetupIconFile=..\assets\echo.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
; 语音识别模型不再随包分发（483MB 的大头）—— 第一次开课时后台下载到 %APPDATA%\Echo\models
Source: "..\dist\Echo\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
