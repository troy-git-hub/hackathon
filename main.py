"""
Echo - 入口
网课里的 AI 学习副驾驶。
"""
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# !!! 必须在 import PyQt5 之前预加载 Whisper 模型 !!!
# PyQt5 与 ctranslate2 的 native 库加载顺序冲突：先 import PyQt5 再加载 WhisperModel 会访问违例
# 必须在主线程、QApplication 创建之前、且未 import 任何 PyQt5 模块时加载
def _preload_whisper():
    try:
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        from echo.backend import config
        from faster_whisper import WhisperModel
        WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE,
                      compute_type=config.WHISPER_COMPUTE,
                      cpu_threads=min(8, os.cpu_count() or 4),
                      local_files_only=True)
        print(f"[Echo] Whisper 预加载完成: {config.WHISPER_MODEL}")
    except Exception as e:
        print(f"[Echo] Whisper 预加载失败（将在后台重试）: {e}")

# 在 import PyQt5 之前执行预加载
_preload_whisper()

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from echo.theme import apply_theme
from echo.widgets.floating_window import FloatingWindow
from echo.widgets.tray import EchoTray
from echo.widgets.desk_pet import DeskPet


def main():
    # 高分屏（如 2880x1800 @200%）按系统缩放渲染，否则整个界面只有一半大
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(QApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    apply_theme(app)

    win = FloatingWindow()
    # 定位到屏幕中央
    screen = app.primaryScreen().availableGeometry()
    win.move(screen.center().x() - win.width() // 2,
             screen.center().y() - win.height() // 2)
    win.show()
    tray = EchoTray(app, win)   # 托盘 + 关闭到托盘 + 全局快捷键（Ctrl+Alt+L 掉队 / Ctrl+Alt+E 显示隐藏 / Ctrl+Alt+Q 圈一下问 AI）

    pet = DeskPet(win, tray)    # 桌宠：跟着课堂变表情，双击圈一下问 AI
    pet.circle_ask.connect(tray.circle_ask)
    tray.pet = pet
    pet.place_default()
    pet.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
