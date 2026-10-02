@echo off
REM ============================================================
REM  Echo 打包脚本：用 PyInstaller 生成独立 exe（dist\Echo\Echo.exe）
REM  需要先：pip install pyinstaller
REM ============================================================
setlocal

pyinstaller --noconfirm --clean --windowed --name Echo --icon assets\echo.ico ^
  --add-data "assets;assets" ^
  --add-data "echo\backend\demo_lesson.txt;echo\backend" ^
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
