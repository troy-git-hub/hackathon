"""
Echo - 入口
网课里的 AI 学习副驾驶。
"""
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from echo.theme import apply_theme
from echo.widgets.floating_window import FloatingWindow


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
    # 定位到屏幕右下角偏上
    screen = app.primaryScreen().availableGeometry()
    win.move(screen.right() - win.width() - 8, screen.bottom() - win.height() - 8)
    win.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
