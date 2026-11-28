; Echo 瀹夎鍖呰剼鏈紙Inno Setup 6锛?
; 鍏堣繍琛?build.bat 鐢熸垚 dist\Echo\Echo.exe锛屽啀鐢ㄦ湰鑴氭湰缂栬瘧銆?

#ifndef MyAppName
  #define MyAppName "Echo"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "2.7.0"
#endif
#define MyAppPublisher "Echo"
#define MyAppExeName "Echo.exe"
; 浜х墿鍚嶅悗缂€銆俠uild_release.py --with-model 浼氫紶 /DMyAppSuffix=-with-model锛?
; 璁┿€屽甫璇煶妯″瀷鐨勮儢鍖呫€嶅拰榛樿鐨勭槮鍖呭苟瀛橈紝涓嶄簰鐩歌鐩栥€?
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
#ifdef ECHO_BETA
OutputBaseFilename=Echo-Beta-Setup-{#MyAppVersion}
#else
OutputBaseFilename=Echo-Setup-{#MyAppVersion}{#MyAppSuffix}
#endif
#endif
SetupIconFile=..\assets\echo.ico
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern dark hidebevels
WizardBackColor=$001E1D1B
WizardSizePercent=120,120
DisableWelcomePage=yes
DisableDirPage=yes
DisableReadyPage=yes
DisableFinishedPage=no
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
CloseApplicationsFilter=Echo.exe
RestartApplications=no
SetupLogging=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UsePreviousPrivileges=no
LicenseFile=license.txt

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "assets\setup-brand.bmp"; Flags: dontcopy
; 璇煶璇嗗埆妯″瀷涓嶅啀闅忓寘鍒嗗彂锛?83MB 鐨勫ぇ澶达級鈥斺€?绗竴娆″紑璇炬椂鍚庡彴涓嬭浇鍒?%APPDATA%\Echo\models
#ifndef ECHO_PREVIEW
Source: "..\dist\Echo\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Check: not IsQAInstall
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Check: WantDesktopIcon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "鍚姩 {#MyAppName}"; Flags: nowait postinstall skipifsilent

#include "echo_wizard.iss"

[Registry]
Root: HKCU; Subkey: "Software\Classes\echo"; ValueType: string; ValueData: "URL:Echo classroom"; Flags: uninsdeletekey; Check: not IsQAInstall
Root: HKCU; Subkey: "Software\Classes\echo"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Check: not IsQAInstall
Root: HKCU; Subkey: "Software\Classes\echo\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Check: not IsQAInstall

[Messages]
chinesesimp.LicenseLabel=下面几句就够了。
chinesesimp.LicenseLabel3=同意之后才能继续。
chinesesimp.LicenseAcceptedRadio=&我同意，继续安装
chinesesimp.LicenseNotAcceptedRadio=&先不装
chinesesimp.PrivilegesRequiredOverrideTitle=安装给谁
chinesesimp.PrivilegesRequiredOverrideInstruction=Echo 可以只装给你，也可以装给这台电脑上的每个人。
chinesesimp.PrivilegesRequiredOverrideAllUsers=装给这台电脑的所有用户
chinesesimp.PrivilegesRequiredOverrideCurrentUser=只装给我
