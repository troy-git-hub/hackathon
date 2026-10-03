"""
Echo - 设置

一个简单的设置窗口：填 API key（DeepSeek / 百炼 Qwen-VL 视觉）、音频来源、Whisper 模型、
界面语言、桌宠皮肤。保存后写回项目根目录的 .env（保留原有注释和其它配置项）。
「用户：」一栏写到用户资料 profile.json（见 echo.backend.profile），下次开机问候就用新名字。
改完需要重启 Echo 生效（语言和皮肤除外，皮肤即时生效）。
"""
import os

from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from echo.backend import cache, paths, profile
from echo.theme import Colors, font, dialog_qss, apply_native_titlebar
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


# dialog_qss 现在是从 echo.theme 导入进来的（上面那行 import）：设置窗 / 首次登录窗 /
# 确认提示框都要共用同一份弹窗样式，放主题模块里更合适。这个名字留在本模块命名空间里，
# profile_setup.py 原来 `from echo.widgets.settings import dialog_qss` 的写法不用跟着改。


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Echo 设置", "Echo Settings"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        apply_native_titlebar(self)
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

        # 用户名：开机问候「你好 + 用户名」用的就是它，存在 profile.json
        self._profile = profile.load()
        self.user_edit = QLineEdit(profile.display_name(self._profile))
        self.user_edit.setPlaceholderText(tr("开机问候时怎么称呼你", "What Echo calls you when it starts"))
        self.user_edit.setFont(font(12))
        form.addRow(tr("用户：", "User:"), self.user_edit)

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

        # 存储：攒了多少东西 + 一键清空
        root.addSpacing(4)
        self.storage_lbl = QLabel("")
        self.storage_lbl.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; font-size:12px;")
        self.storage_lbl.setWordWrap(True)
        root.addWidget(self.storage_lbl)
        srow = QHBoxLayout()
        self.btn_clear = QPushButton(tr("清除所有缓存", "Clear all data"))
        self.btn_clear.clicked.connect(self._clear_cache)
        srow.addWidget(self.btn_clear)
        srow.addStretch()
        root.addLayout(srow)
        self._refresh_storage()

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText(tr("保存", "Save"))
        btns.button(QDialogButtonBox.Cancel).setText(tr("取消", "Cancel"))
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self.setStyleSheet(dialog_qss())
        self.resize(480, 440)        # 比原来高：「清除缓存」那一段占了一行

    # ================= 存储 =================
    def _refresh_storage(self):
        """刷新「本机存了多少」那一行。读不到就显示 0，不让设置窗口打不开。"""
        try:
            st = cache.stats()
            empty = cache.is_empty(st)
        except Exception:
            st, empty = {"lessons": 0, "mistakes": 0, "bytes": 0}, True
        if empty:
            self.storage_lbl.setText(tr("本机还没有攒下任何记录。",
                                        "Nothing stored on this computer yet."))
        else:
            self.storage_lbl.setText(tr(
                f"本机存了 {st['lessons']} 节课的历史、{st['mistakes']} 个错题，"
                f"共 {cache.size_text(st['bytes'])}。",
                f"{st['lessons']} lessons and {st['mistakes']} mistakes on this computer, "
                f"{cache.size_text(st['bytes'])} in total."))
        self.btn_clear.setEnabled(not empty)

    def _clear_cache(self):
        """清空本机的记录。删之前把「删什么、留什么」摊开说清楚 —— 这步不可逆。"""
        from echo.widgets import dialogs
        try:
            st = cache.stats()
        except Exception:
            st = {"lessons": 0, "mistakes": 0, "bytes": 0}
        if not dialogs.confirm(
                self, tr("清除所有缓存", "Clear all data"),
                tr(f"会删掉：\n"
                   f"　· {st['lessons']} 节课的历史记录\n"
                   f"　· {st['mistakes']} 个错题（连同复习进度）\n"
                   f"　· 知识地图上记住的位置\n\n"
                   f"名字、头像、API key 和这里的设置都会保留。\n"
                   f"删掉之后没法恢复。",
                   f"This will delete:\n"
                   f"　· {st['lessons']} lesson records\n"
                   f"　· {st['mistakes']} mistakes (and their review progress)\n"
                   f"　· saved positions on the knowledge map\n\n"
                   f"Your name, photo, API keys and settings are kept.\n"
                   f"This can't be undone."),
                ok_text=tr("删除", "Delete")):
            return
        try:
            cache.clear()
        except Exception:
            pass
        self._refresh_storage()

    def _save(self):
        updates = {k: ed.text().strip() for k, ed in self.inputs.items()}
        for key, cb in self.combos.items():
            updates[key] = cb.currentData()
        try:
            _write_env(updates)
        except OSError as e:
            from echo.widgets import dialogs
            dialogs.warn(self, tr("保存失败", "Save failed"),
                         f"{tr('写 .env 失败：', 'Failed to write .env: ')}{e}")
            return
        username = self.user_edit.text().strip()
        if username != str(self._profile.get("username") or ""):
            try:
                profile.save({"username": username})
            except OSError as e:
                from echo.widgets import dialogs
                dialogs.warn(self, tr("保存失败", "Save failed"),
                             f"{tr('写用户资料失败：', 'Failed to save profile: ')}{e}")
                return
        set_lang(self.lang_combo.currentData())
        # 界面文案要重启才换，但 AI 用哪种语言回答可以立刻生效
        from echo.backend import config as backend_config
        backend_config.set_ui_lang(self.lang_combo.currentData())
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
