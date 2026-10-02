@echo off
REM ============================================================
REM  Echo 打包脚本：用 PyInstaller 生成独立 exe（dist\Echo\Echo.exe）
REM  需要先：pip install pyinstaller
REM ============================================================
setlocal

REM 环境里同时装了 PyQt5 和 PyQt6 时，PyInstaller 会直接中止打包，
REM 必须显式排除没用到的 Qt 绑定。
pyinstaller --noconfirm --clean --windowed --name Echo --icon assets\echo.ico ^
  --exclude-module PyQt6 ^
  --exclude-module PySide2 ^
  --exclude-module PySide6 ^
  --exclude-module torch ^
  --exclude-module torchvision ^
  --exclude-module torchaudio ^
  --exclude-module sympy ^
  --exclude-module tkinter ^
  --exclude-module matplotlib ^
  --exclude-module IPython ^
  --exclude-module jupyter ^
  --add-data "assets;assets" ^
  --add-data ".env.example;." ^
  --hidden-import openai ^
  --hidden-import echo.widgets.desk_pet ^
  --hidden-import echo.widgets.snip ^
  --hidden-import echo.widgets.settings ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all tokenizers ^
  --collect-all onnxruntime ^
  --collect-all pyaudiowpatch ^
  --collect-all sounddevice ^
  --collect-all opencc_python_reimplemented ^
  --collect-all opencc ^
  main.py

echo.
echo 完成。exe 在 dist\Echo\Echo.exe
echo 用 Inno Setup 打开 installer\setup.iss 即可生成安装包。
endlocal
