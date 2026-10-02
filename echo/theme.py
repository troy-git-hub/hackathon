"""
Echo - WinUI 风格主题
参考 Windows 11 Fluent Design / WinUI 3 配色与圆角规范。
"""
import os

from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtCore import Qt


# ---------- 调色板：跟随 Windows 深浅色（ECHO_THEME=dark/light 可强制） ----------
def _system_dark() -> bool:
    mode = os.getenv("ECHO_THEME", "auto").lower()
    if mode in ("dark", "light"):
        return mode == "dark"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


IS_DARK = _system_dark()

_LIGHT = dict(
    WINDOW_BG="#F9F9F9", WINDOW_BORDER="#DADADA", SHADOW_ALPHA=22,
    MICA_LIGHT="#F3F3F3", MICA_DARK="#202020",
    SURFACE="#FFFFFF", SURFACE_HOVER="#F5F5F5", SURFACE_PRESSED="#EDEDED",
    CODE_BG="#F0F0F0", HOVER_OVERLAY="rgba(0, 0, 0, 0.05)",
    PRIMARY="#0078D4", PRIMARY_HOVER="#106EBE", PRESSED="#005A9E", PRIMARY_LIGHT="#DEECF9",
    INFO_BORDER="#C7E0F4",
    TEXT_PRIMARY="#1A1A1A", TEXT_SECONDARY="#616161", TEXT_DISABLED="#A0A0A0", TEXT_ON_ACCENT="#FFFFFF",
    BORDER="#E5E5E5", BORDER_STRONG="#D1D1D1",
    SUCCESS="#107C10", SUCCESS_BG="#DFF6DD", SUCCESS_SOFT="#E9F7E8", SUCCESS_BORDER="#A6E0A6",
    WARNING="#CA5010", WARNING_BG="#FDE7B0", WARNING_SOFT="#FFF4CE", WARNING_BORDER="#F5D28A",
    WARNING_CARD="#FFF8E6", WARNING_CARD_BORDER="#F7D58A",
    DANGER="#D13438", DANGER_BG="#FDE7E9", DANGER_BORDER="#F3A8AD",
    DANGER_HOVER="#B3262A", DANGER_PRESSED="#8E1F22",
    NODE_OK="#107C10", NODE_WARN="#FF8C00", NODE_LOST="#D13438", NODE_NOW="#0078D4",
    NODE_GLYPH="#FFFFFF",
    BUBBLE_BG="#FFFFFF", BUBBLE_BORDER="#E0E0E0",
)

_DARK = dict(
    WINDOW_BG="#2B2B2B", WINDOW_BORDER="#3F3F3F", SHADOW_ALPHA=60,
    MICA_LIGHT="#202020", MICA_DARK="#202020",
    SURFACE="#363636", SURFACE_HOVER="#3E3E3E", SURFACE_PRESSED="#2F2F2F",
    CODE_BG="#1F1F1F", HOVER_OVERLAY="rgba(255, 255, 255, 0.08)",
    PRIMARY="#4CC2FF", PRIMARY_HOVER="#47B1E8", PRESSED="#42A1D2", PRIMARY_LIGHT="#14374D",
    INFO_BORDER="#1F5A7A",
    TEXT_PRIMARY="#FFFFFF", TEXT_SECONDARY="#C8C8C8", TEXT_DISABLED="#7A7A7A", TEXT_ON_ACCENT="#000000",
    BORDER="#454545", BORDER_STRONG="#5A5A5A",
    SUCCESS="#6CCB5F", SUCCESS_BG="#253A22", SUCCESS_SOFT="#22331F", SUCCESS_BORDER="#3E6B37",
    WARNING="#FFB547", WARNING_BG="#4A3A17", WARNING_SOFT="#3D3218", WARNING_BORDER="#7A5E22",
    WARNING_CARD="#3A3020", WARNING_CARD_BORDER="#7A5E22",
    DANGER="#FF6B6B", DANGER_BG="#4A2426", DANGER_BORDER="#7D3A3E",
    DANGER_HOVER="#E65A5A", DANGER_PRESSED="#C94A4A",
    NODE_OK="#6CCB5F", NODE_WARN="#FFB547", NODE_LOST="#FF6B6B", NODE_NOW="#4CC2FF",
    NODE_GLYPH="#1A1A1A",
    BUBBLE_BG="#2B2B2B", BUBBLE_BORDER="#454545",
)


# 学习工具风格：中性灰底 + 唯一强调色（琥珀）只给「掉队/断点」，绿色只做弱提示
_STUDY_LIGHT = dict(
    WINDOW_BG="#FBFBFA", WINDOW_BORDER="#E3E3E0", SHADOW_ALPHA=26,
    SURFACE="#FFFFFF", SURFACE_HOVER="#F4F4F2", SURFACE_PRESSED="#ECECEA",
    BORDER="#E6E6E3", BORDER_STRONG="#D4D4D0", CODE_BG="#F2F2EF",
    TEXT_PRIMARY="#1D1E20", TEXT_SECONDARY="#6B6D72", TEXT_DISABLED="#A8AAAE",
    ACCENT="#D9861A", ACCENT_HOVER="#C77812", ACCENT_PRESSED="#B06A0F",
    ACCENT_SOFT="#FCF1E0", ACCENT_BORDER="#EFCB92", ON_ACCENT="#1D1E20",
    OK_FG="#3E8E50", OK_SOFT="#EAF5EC", NOW_FG="#1D1E20",
)
_STUDY_DARK = dict(
    WINDOW_BG="#1C1D21", WINDOW_BORDER="#2E3036", SHADOW_ALPHA=70,
    SURFACE="#24262B", SURFACE_HOVER="#2B2D33", SURFACE_PRESSED="#202226",
    BORDER="#32343A", BORDER_STRONG="#3E4047", CODE_BG="#16171A",
    TEXT_PRIMARY="#ECEDEF", TEXT_SECONDARY="#9EA1A8", TEXT_DISABLED="#63666D",
    ACCENT="#F2A93B", ACCENT_HOVER="#F5B755", ACCENT_PRESSED="#D9922A",
    ACCENT_SOFT="#2F2619", ACCENT_BORDER="#6B4F22", ON_ACCENT="#1B1406",
    OK_FG="#8CC79A", OK_SOFT="#1F2B23", NOW_FG="#ECEDEF",
)


class Colors:
    INFO = "#0078D4"


for _k, _v in {**(_DARK if IS_DARK else _LIGHT), **(_STUDY_DARK if IS_DARK else _STUDY_LIGHT)}.items():
    setattr(Colors, _k, _v)
Colors.INFO = Colors.PRIMARY


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
    font-family: "Segoe UI Variable Text", "Microsoft YaHei UI", "Segoe UI", sans-serif;
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
    color: {"#1A1A1A" if IS_DARK else "#FFFFFF"};
    border: 1px solid {Colors.DANGER};
}}
QPushButton#Danger:hover {{
    background-color: {Colors.DANGER_HOVER};
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
    color: {"#1A1A1A" if IS_DARK else "#FFFFFF"};
    border: 1px solid {Colors.DANGER};
    border-radius: {Radius.MD}px;
    font-size: 14px;
    font-weight: 600;
    padding: 8px 16px;
}}
QPushButton#Lost:hover {{
    background-color: {Colors.DANGER_HOVER};
    border-color: {Colors.DANGER_HOVER};
}}
QPushButton#Lost:pressed {{
    background-color: {Colors.DANGER_PRESSED};
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
    background-color: {Colors.HOVER_OVERLAY};
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

/* ---------- 学习工具风格按钮 ---------- */
QPushButton#Accent {{
    background-color: {Colors.ACCENT};
    border: 1px solid {Colors.ACCENT};
    border-radius: {Radius.MD}px;
    color: {Colors.ON_ACCENT};
    font-size: 15px;
    font-weight: 700;
    padding: 10px 16px;
}}
QPushButton#Accent:hover {{ background-color: {Colors.ACCENT_HOVER}; border-color: {Colors.ACCENT_HOVER}; }}
QPushButton#Accent:pressed {{ background-color: {Colors.ACCENT_PRESSED}; }}
QPushButton#Accent:disabled {{
    background-color: {Colors.SURFACE_HOVER};
    border-color: {Colors.BORDER};
    color: {Colors.TEXT_DISABLED};
}}
QPushButton#Solid {{
    background-color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.TEXT_PRIMARY};
    border-radius: {Radius.MD}px;
    color: {Colors.WINDOW_BG};
    font-size: 14px;
    font-weight: 700;
    padding: 9px 16px;
}}
QPushButton#Solid:hover {{ background-color: {Colors.TEXT_SECONDARY}; border-color: {Colors.TEXT_SECONDARY}; }}
QPushButton#Quiet {{
    background-color: transparent;
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.MD}px;
    color: {Colors.TEXT_SECONDARY};
    font-size: 13px;
    padding: 6px 10px;
}}
QPushButton#Quiet:hover {{ background-color: {Colors.SURFACE_HOVER}; color: {Colors.TEXT_PRIMARY}; }}
QPushButton#Quiet:disabled {{ color: {Colors.OK_FG}; border-color: {Colors.BORDER}; }}
QPushButton#Link {{
    background: transparent;
    border: none;
    color: {Colors.TEXT_SECONDARY};
    font-size: 13px;
    padding: 4px 6px;
}}
QPushButton#Link:hover {{ color: {Colors.TEXT_PRIMARY}; }}
QPushButton#IconBtn {{
    background: transparent;
    border: none;
    border-radius: {Radius.SM}px;
    color: {Colors.TEXT_SECONDARY};
    font-size: 15px;
    padding: 0px;
}}
QPushButton#IconBtn:hover {{ background: {Colors.HOVER_OVERLAY}; color: {Colors.TEXT_PRIMARY}; }}
"""


def apply_theme(app):
    app.setStyleSheet(GLOBAL_QSS)
    app.setFont(font(12))


def menu_qss() -> str:
    """右键菜单样式。

    必须显式给菜单设颜色：全局 QSS 里的 `* { color: TEXT_PRIMARY }` 会渗进菜单，
    深色主题下文字被染成白色，而菜单背景仍是系统浅色 —— 变成白字白底看不见。
    """
    return f"""
    QMenu {{
        background-color: {Colors.SURFACE};
        border: 1px solid {Colors.BORDER_STRONG};
        border-radius: {Radius.MD}px;
        padding: 5px;
    }}
    QMenu::item {{
        padding: 7px 30px 7px 14px;
        border-radius: 5px;
        color: {Colors.TEXT_PRIMARY};
        background: transparent;
    }}
    QMenu::item:selected {{
        background-color: {Colors.SURFACE_HOVER};
    }}
    QMenu::item:disabled {{
        color: {Colors.TEXT_DISABLED};
    }}
    QMenu::separator {{
        height: 1px;
        background: {Colors.BORDER};
        margin: 4px 8px;
    }}
    QMenu::indicator {{
        width: 14px; height: 14px; margin-left: 6px;
    }}
    QMenu::indicator:checked {{
        background-color: {Colors.ACCENT};
        border-radius: 3px;
        border: 1px solid {Colors.ACCENT};
    }}
    """


def style_menu(menu):
    """把右键菜单调成和托盘菜单一样的风格（跟随深浅色、圆角、悬浮高亮）。"""
    menu.setStyleSheet(menu_qss())
    # 圆角要生效得去掉系统边框和阴影，用 QSS 的圆角代替
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground, True)
    return menu
