"""
Echo - 设置

一个简单的设置窗口：填 API key（DeepSeek / 百炼 Qwen-VL 视觉）、音频来源、Whisper 模型、
界面语言、桌宠皮肤。保存后写回项目根目录的 .env（保留原有注释和其它配置项）。
改完需要重启 Echo 生效（语言和皮肤除外，皮肤即时生效）。
"""
import os

from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                             QLineEdit, QVBoxLayout, QWidget, QApplication)

from echo.backend import paths
from echo.theme import Colors, font
from echo.i18n import tr, lang, set_lang

# 打包后写到 %APPDATA%\Echo\.env（安装目录在 C:\Program Files 下不可写），开发时写到项目根目录
ROOT = paths.app_dir()
ENV_PATH = paths.ensure_env()
ENV_EXAMPLE = paths.example_env()

FIELDS = [
    ("DEEPSEEK_API_KEY", "DeepSeek API Key",
     tr("课堂理解 / 掉队分析（deepseek-chat）", "Lesson understanding / breakpoint analysis (deepseek-chat)")),
    ("DASHSCOPE_API_KEY", tr("百炼 API Key", "DashScope API Key"),
     tr("圈一下问 AI 的视觉模型（Qwen-VL，选填）", "Vision model for circle-to-ask AI (Qwen-VL, optional)")),
]
COMBOS = [
    ("ECHO_SOURCE", tr("音频来源", "Audio source"), ["system", "mic"],
     [tr("系统声音（网课/会议）", "System audio (courses / meetings)"), tr("麦克风", "Microphone")]),
    ("ECHO_WHISPER_MODEL", tr("语音识别模型", "Speech recognition model"), ["small", "medium"],
     [tr("small（快，CPU 实时）", "small (fast, real-time on CPU)"),
      tr("medium（更准，更慢）", "medium (more accurate, slower)")]),
]


def _read_env() -> dict:
    """读 .env 成 {key: value}，没有则用 .env.example 兜底。"""
    path = ENV_PATH if os.path.exists(ENV_PATH) else ENV_EXAMPLE
    kv = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                kv[k.strip()] = v.strip()
    except OSError:
        pass
    return kv


def _write_env(updates: dict):
    """更新 .env：已有的 key 原地改值，没有的 key 追加到末尾，注释保留。"""
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
    written = set()
    for i, line in enumerate(lines):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in updates:
                lines[i] = f"{k}={updates[k]}"
                written.add(k)
    for k, v in updates.items():
        if k not in written:
            lines.append(f"{k}={v}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Echo 设置", "Echo Settings"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._kv = _read_env()
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(10)

        title = QLabel(tr("Echo 设置", "Echo Settings"))
        title.setFont(font(16, 600))
        root.addWidget(title)
        sub = QLabel(tr("API key 保存在本地 .env 文件，不会上传。改完重启 Echo 生效。",
                        "API keys are stored in a local .env file and never uploaded. "
                        "Changes take effect after restarting Echo."))
        sub.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; font-size:12px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.inputs = {}
        for key, label, tip in FIELDS:
            ed = QLineEdit(self._kv.get(key, ""))
            ed.setEchoMode(QLineEdit.Password)
            ed.setPlaceholderText(tr("sk-…（留空则离线/退回另一家）", "sk-… (leave blank for offline / fallback)"))
            ed.setToolTip(tip)
            ed.setFont(font(12))
            form.addRow(f"{label}：", ed)
            self.inputs[key] = ed

        self.combos = {}
        for key, label, values, labels in COMBOS:
            cb = QComboBox()
            cb.setFont(font(12))
            for v, t in zip(values, labels):
                cb.addItem(t, v)
            cur = self._kv.get(key, values[0])
            if cur in values:
                cb.setCurrentIndex(values.index(cur))
            cb.setToolTip(" / ".join(labels))
            form.addRow(f"{label}：", cb)
            self.combos[key] = cb

        # 界面语言：改完重启 Echo 生效
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setCurrentIndex(1 if lang() == "en" else 0)
        form.addRow(tr("语言：", "Language:"), self.lang_combo)

        self.pet_skin = QComboBox()
        self.pet_skin.addItem(tr("原版圆脸卡通猫（桌面＋磁吸）", "Original cartoon cat (desktop + docked)"), "cartoon")
        self.pet_skin.addItem(tr("线稿猫（桌面＋磁吸）", "Line-art cat (desktop + docked)"), "line")
        current_skin = QSettings("Echo", "Echo").value("desktop_pet_skin", "cartoon")
        self.pet_skin.setCurrentIndex(1 if current_skin == "line" else 0)
        form.addRow(tr("桌宠皮肤：", "Pet skin:"), self.pet_skin)

        root.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText(tr("保存", "Save"))
        btns.button(QDialogButtonBox.Cancel).setText(tr("取消", "Cancel"))
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self.setStyleSheet(f"""
            QDialog {{ background:{Colors.WINDOW_BG}; }}
            QLabel {{ color:{Colors.TEXT_PRIMARY}; }}
            QLineEdit, QComboBox {{
                background:{Colors.SURFACE}; color:{Colors.TEXT_PRIMARY};
                border:1px solid {Colors.BORDER}; border-radius:6px; padding:6px 8px;
            }}
            QLineEdit:focus, QComboBox:focus {{ border-color:{Colors.ACCENT}; }}
            QComboBox::drop-down {{ border:none; width:22px; }}
            QPushButton {{
                background:{Colors.SURFACE}; color:{Colors.TEXT_PRIMARY};
                border:1px solid {Colors.BORDER}; border-radius:6px; padding:6px 18px;
            }}
            QPushButton:hover {{ border-color:{Colors.BORDER_STRONG}; }}
            QDialogButtonBox QPushButton:first-child {{
                background:{Colors.ACCENT}; color:{Colors.ON_ACCENT}; border:none; font-weight:600;
            }}
            QDialogButtonBox QPushButton:first-child:hover {{ background:{Colors.ACCENT_HOVER}; }}
        """)
        self.resize(480, 360)

    def _save(self):
        updates = {k: ed.text().strip() for k, ed in self.inputs.items()}
        for key, cb in self.combos.items():
            updates[key] = cb.currentData()
        try:
            _write_env(updates)
        except OSError as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("保存失败", "Save failed"), f"{tr('写 .env 失败：', 'Failed to write .env: ')}{e}")
            return
        set_lang(self.lang_combo.currentData())
        skin = self.pet_skin.currentData()
        QSettings("Echo", "Echo").setValue("desktop_pet_skin", skin)
        from echo.widgets.desk_pet import DeskPet
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, DeskPet):
                widget.set_skin(skin)
        self.accept()


def open_settings_dialog(parent=None):
    dlg = SettingsDialog(parent)
    dlg.exec_()
