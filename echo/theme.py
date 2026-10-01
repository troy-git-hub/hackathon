"""
Echo - WinUI 风格主题
参考 Windows 11 Fluent Design / WinUI 3 配色与圆角规范。
"""
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtCore import Qt


# ---------- 调色板 (WinUI Light) ----------
class Colors:
    # 背景层
    MICA_LIGHT = "#F3F3F3"          # Mica 基色（浅）
    MICA_DARK = "#202020"           # Mica 基色（深）
    SURFACE = "#FFFFFF"             # 卡片/浮层表面
    SURFACE_HOVER = "#F9F9F9"
    SURFACE_PRESSED = "#F0F0F0"

    # 主色（Windows 强调色蓝）
    PRIMARY = "#0078D4"
    PRIMARY_HOVER = "#106EBE"
    PRESSED = "#005A9E"
    PRIMARY_LIGHT = "#DEECF9"

    # 文本
    TEXT_PRIMARY = "#1A1A1A"
    TEXT_SECONDARY = "#616161"
    TEXT_DISABLED = "#A0A0A0"
    TEXT_ON_ACCENT = "#FFFFFF"

    # 分割线 / 边框
    BORDER = "#E5E5E5"
    BORDER_STRONG = "#D1D1D1"

    # 语义色
    SUCCESS = "#107C10"
    SUCCESS_BG = "#DFF6DD"
    WARNING = "#CA5010"
    WARNING_BG = "#FDE7B0"
    DANGER = "#D13438"
    DANGER_BG = "#FDE7E9"
    INFO = "#0078D4"

    # 时间轴节点
    NODE_OK = "#107C10"
    NODE_WARN = "#FF8C00"
    NODE_LOST = "#D13438"
    NODE_NOW = "#0078D4"


# ---------- 圆角与间距 ----------
class Radius:
    SM = 4
    MD = 8
    LG = 12
    XL = 16
    PILL = 999


class Spacing:
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24
    XXL = 32


# ---------- 字体 ----------
def font(size=12, weight=QFont.Normal):
    # 用像素字号，与 QSS 的 px 保持一致（pt 会随 DPI 放大，高分屏下会比 QSS 文本大一圈）
    f = QFont("Segoe UI Variable")
    f.setPixelSize(size + 1)
    f.setWeight(weight)
    return f


# ---------- 全局 QSS ----------
GLOBAL_QSS = f"""
* {{
    font-family: "Segoe UI Variable", "Microsoft YaHei UI", "Segoe UI", sans-serif;
    color: {Colors.TEXT_PRIMARY};
    outline: none;
}}

QWidget#EchoRoot {{
    background-color: {Colors.MICA_LIGHT};
    border-radius: {Radius.LG}px;
}}

QWidget#SurfaceCard {{
    background-color: {Colors.SURFACE};
    border-radius: {Radius.MD}px;
    border: 1px solid {Colors.BORDER};
}}

QLabel#Title {{
    font-size: 15px;
    font-weight: 600;
    color: {Colors.TEXT_PRIMARY};
}}

QLabel#Topic {{
    font-size: 19px;
    font-weight: 700;
    color: {Colors.TEXT_PRIMARY};
}}

QLabel#Caption {{
    font-size: 11px;
    color: {Colors.TEXT_SECONDARY};
}}

QLabel#Body {{
    font-size: 12px;
    color: {Colors.TEXT_PRIMARY};
}}

QLabel#BodySecondary {{
    font-size: 12px;
    color: {Colors.TEXT_SECONDARY};
}}

QLabel#Timecode {{
    font-size: 12px;
    color: {Colors.TEXT_SECONDARY};
    font-family: "Consolas", "Cascadia Code", monospace;
}}

/* WinUI 按钮基类 */
QPushButton {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.MD}px;
    padding: 6px 14px;
    font-size: 12px;
    color: {Colors.TEXT_PRIMARY};
}}
QPushButton:hover {{
    background-color: {Colors.SURFACE_HOVER};
    border-color: {Colors.BORDER_STRONG};
}}
QPushButton:pressed {{
    background-color: {Colors.SURFACE_PRESSED};
}}

QPushButton#Primary {{
    background-color: {Colors.PRIMARY};
    color: {Colors.TEXT_ON_ACCENT};
    border: 1px solid {Colors.PRIMARY};
}}
QPushButton#Primary:hover {{
    background-color: {Colors.PRIMARY_HOVER};
    border-color: {Colors.PRIMARY_HOVER};
}}
QPushButton#Primary:pressed {{
    background-color: {Colors.PRESSED};
}}

QPushButton#Danger {{
    background-color: {Colors.DANGER};
    color: {Colors.TEXT_ON_ACCENT};
    border: 1px solid {Colors.DANGER};
}}
QPushButton#Danger:hover {{
    background-color: #B3262A;
}}

QPushButton#Ghost {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {Colors.TEXT_SECONDARY};
}}
QPushButton#Ghost:hover {{
    background-color: {Colors.SURFACE_HOVER};
    color: {Colors.TEXT_PRIMARY};
}}

QPushButton#Lost {{
    background-color: {Colors.DANGER};
    color: {Colors.TEXT_ON_ACCENT};
    border: 1px solid {Colors.DANGER};
    border-radius: {Radius.MD}px;
    font-size: 14px;
    font-weight: 600;
    padding: 8px 16px;
}}
QPushButton#Lost:hover {{
    background-color: #B3262A;
    border-color: #B3262A;
}}
QPushButton#Lost:pressed {{
    background-color: #8E1F22;
}}

QPushButton#Primary:disabled {{
    background-color: {Colors.BORDER};
    border-color: {Colors.BORDER};
    color: {Colors.TEXT_DISABLED};
}}

QPushButton#Small {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {Radius.SM}px;
    padding: 2px 8px;
    font-size: 12px;
    color: {Colors.TEXT_SECONDARY};
}}
QPushButton#Small:hover {{
    background-color: rgba(0, 0, 0, 0.05);
    color: {Colors.TEXT_PRIMARY};
}}

QToolTip {{
    background-color: {Colors.SURFACE};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER};
    padding: 4px 8px;
}}

QPushButton#Pill {{
    border-radius: {Radius.PILL}px;
    padding: 4px 12px;
}}

/* 进度条 */
QProgressBar {{
    background-color: {Colors.BORDER};
    border: none;
    border-radius: {Radius.SM}px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {Colors.PRIMARY};
    border-radius: {Radius.SM}px;
}}
QProgressBar#Ok::chunk {{ background-color: {Colors.SUCCESS}; }}
QProgressBar#Warn::chunk {{ background-color: {Colors.WARNING}; }}
QProgressBar#Lost::chunk {{ background-color: {Colors.DANGER}; }}
"""


def apply_theme(app):
    app.setStyleSheet(GLOBAL_QSS)
    app.setFont(font(12))
