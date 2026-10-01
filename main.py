"""
Echo - 入口
网课里的 AI 学习副驾驶。
"""
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from echo.theme import apply_theme
from echo.widgets.floating_window import FloatingWindow


def main():
    app = QApplication(sys.argv)
    apply_theme(app)

    win = FloatingWindow()
    # 定位到屏幕右下角偏上
    screen = app.primaryScreen().availableGeometry()
    win.move(screen.right() - 300, screen.bottom() - 360)
    win.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
