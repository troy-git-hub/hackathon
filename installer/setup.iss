; Echo 安装包脚本（Inno Setup 6）
; 先运行 build.bat 生成 dist\Echo\Echo.exe，再用本脚本编译。

#define MyAppName "Echo"
#define MyAppVersion "1.1"
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
; 464MB 的模型是二进制，压缩既慢又压不动，单独放进来且不压缩
Source: "..\dist\Echo\_internal\models\faster-whisper-small\model.bin"; DestDir: "{app}\_internal\models\faster-whisper-small"; Flags: ignoreversion nocompression dontverifychecksum
Source: "..\dist\Echo\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Excludes: "_internal\models\faster-whisper-small\model.bin"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
