"""
Echo - 界面语言（国际化）

语言存 QSettings("Echo", "Echo")/language，取值 "zh" / "en"。
tr(中文, English) 按当前语言返回对应文本；英文留空时兜底返回中文。
改语言后重启 Echo 生效。
"""
from PyQt5.QtCore import QSettings

_ORG, _APP = "Echo", "Echo"
_LANG_KEY = "language"


def lang() -> str:
    """当前语言："zh" / "en"。"""
    try:
        v = QSettings(_ORG, _APP).value(_LANG_KEY, "zh")
    except Exception:
        return "zh"
    return "en" if str(v) == "en" else "zh"


def set_lang(l: str):
    """保存语言选择（"en" 或 "zh"）。"""
    QSettings(_ORG, _APP).setValue(_LANG_KEY, "en" if str(l) == "en" else "zh")


def tr(zh: str, en: str = "") -> str:
    """按当前语言返回文本。en 为空时返回 zh（未翻译项兜底）。"""
    if lang() == "en" and en:
        return en
    return zh
