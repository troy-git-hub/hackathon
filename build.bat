@echo off
REM ============================================================
REM  Echo 打包脚本：用 PyInstaller 生成独立 exe（dist\Echo\Echo.exe）
REM  需要先：pip install pyinstaller
REM ============================================================
setlocal

REM 环境里同时装了 PyQt5 和 PyQt6 时，PyInstaller 会直接中止打包，
REM 必须显式排除没用到的 Qt 绑定。
REM ctranslate2 / onnxruntime 不能用 --collect-all：ctranslate2\converters\transformers.py
REM 与 onnxruntime\transformers\* 会 import transformers，把 datasets / pyarrow / librosa /
REM h5py 整条链路拖进来，体积涨到几 GB 并触发 PyInstaller 递归崩溃。
pyinstaller --noconfirm --clean --windowed --name Echo --icon assets\echo.ico ^
  --exclude-module PyQt6 ^
  --exclude-module PySide2 ^
  --exclude-module PySide6 ^
  --exclude-module torch ^
  --exclude-module torchvision ^
  --exclude-module torchaudio ^
  --exclude-module tensorflow ^
  --exclude-module keras ^
  --exclude-module sklearn ^
  --exclude-module scipy ^
  --exclude-module sympy ^
  --exclude-module pandas ^
  --exclude-module cv2 ^
  --exclude-module tkinter ^
  --exclude-module matplotlib ^
  --exclude-module IPython ^
  --exclude-module jupyter ^
  --exclude-module pytest ^
  --exclude-module transformers ^
  --exclude-module datasets ^
  --exclude-module librosa ^
  --exclude-module jieba ^
  --exclude-module h5py ^
  --exclude-module sqlalchemy ^
  --exclude-module sphinx ^
  --exclude-module docutils ^
  --exclude-module pyarrow ^
  --exclude-module imageio_ffmpeg ^
  --exclude-module imageio ^
  --exclude-module boto3 ^
  --exclude-module botocore ^
  --exclude-module s3transfer ^
  --exclude-module grpc ^
  --exclude-module lxml ^
  --add-data "assets;assets" ^
  --add-data ".env.example;." ^
  --hidden-import openai ^
  --hidden-import onnxruntime ^
  --hidden-import ctranslate2 ^
  --hidden-import echo.widgets.desk_pet ^
  --hidden-import echo.widgets.snip ^
  --hidden-import echo.widgets.settings ^
  --collect-all faster_whisper ^
  --collect-all tokenizers ^
  --collect-binaries ctranslate2 ^
  --collect-data ctranslate2 ^
  --collect-binaries onnxruntime ^
  --collect-data onnxruntime ^
  --collect-all pyaudiowpatch ^
  --collect-binaries opencc ^
  --collect-data opencc ^
  main.py

echo.
echo 完成。exe 在 dist\Echo\Echo.exe
echo 用 Inno Setup 打开 installer\setup.iss 即可生成安装包。
endlocal
