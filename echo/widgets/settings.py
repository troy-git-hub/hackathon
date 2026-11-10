"""
Echo - 设置

一个简单的设置窗口：选模型厂商并填 API key（文本 / 视觉分开）、音频来源、Whisper 模型、
界面语言、桌宠皮肤。保存后写回 .env（保留原有注释和其它配置项），并写进当前进程的环境变量，
下一次提问就换厂商。已经开着的这节课是启动时接上的，要重新开一节或重启才换。
「用户：」一栏写到用户资料 profile.json（见 echo.backend.profile），下次开机问候就用新名字。
语言和皮肤不用重启。
"""
import os

from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout, QWidget)

from echo.backend import cache, paths, profile, providers
from echo.theme import Colors, font, dialog_qss, apply_native_titlebar
from echo.i18n import tr, lang, set_lang

# 打包后写到 %APPDATA%\Echo\.env（安装目录在 C:\Program Files 下不可写），开发时写到项目根目录
ROOT = paths.app_dir()
ENV_PATH = paths.ensure_env()
ENV_EXAMPLE = paths.example_env()

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


class _Combo(QComboBox):
    """下拉列表给实底、按文字撑开。不然深色界面里弹层是透明的，字会叠成两行。"""

    def __init__(self):
        super().__init__()
        self.setFont(font(12))
        self.setMaxVisibleItems(14)
        self.view().setAutoFillBackground(True)
        self.setStyleSheet(f"""
            QComboBox QAbstractItemView {{
                background: {Colors.SURFACE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_STRONG};
                outline: 0;
                padding: 0px;
                selection-background-color: {Colors.ACCENT};
                selection-color: {Colors.ON_ACCENT};
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 28px;
                padding: 4px 10px;
                background: {Colors.SURFACE};
                color: {Colors.TEXT_PRIMARY};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background: {Colors.ACCENT};
                color: {Colors.ON_ACCENT};
            }}
        """)

    def showPopup(self):
        w = self.width()
        fm = self.fontMetrics()
        for i in range(self.count()):
            w = max(w, fm.horizontalAdvance(self.itemText(i)) + 36)
        self.view().setMinimumWidth(w)
        super().showPopup()
        popup = self.view().window()
        if popup is not None and popup is not self:
            popup.setMinimumWidth(w)
            if popup.width() < w:
                popup.resize(w, popup.height())


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
        sub = QLabel(tr("选一家，贴上 Key 就能用。模型名不用改，除非你想换。Key 只存在本机。",
                        "Pick a provider and paste the key. Leave the model name unless you "
                        "want a different one. The key stays on this computer."))
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

        self._build_providers(form)

        self.combos = {}
        for key, label, values, labels in COMBOS:
            cb = _Combo()
            for v, t in zip(values, labels):
                cb.addItem(t, v)
            cur = self._kv.get(key, values[0])
            if cur in values:
                cb.setCurrentIndex(values.index(cur))
            cb.setToolTip(" / ".join(labels))
            form.addRow(f"{label}：", cb)
            self.combos[key] = cb

        # 界面语言：改完重启 Echo 生效
        self.lang_combo = _Combo()
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setCurrentIndex(1 if lang() == "en" else 0)
        form.addRow(tr("语言：", "Language:"), self.lang_combo)

        self.pet_skin = _Combo()
        from echo.pet_skins import PET_SKINS
        for ident, (zh, en, _fill, _line) in PET_SKINS.items():
            self.pet_skin.addItem(tr(zh, en), ident)
        current_skin = QSettings("Echo", "Echo").value("desktop_pet_skin", "cartoon")
        self._select(self.pet_skin, current_skin)
        form.addRow(tr("桌宠皮肤：", "Pet skin:"), self.pet_skin)

        from echo.theme import THEMES, THEME_MODE
        self.theme_combo = _Combo()
        for ident, title in THEMES.items():
            self.theme_combo.addItem(title, ident)
        self._select(self.theme_combo, THEME_MODE)
        form.addRow(tr("界面主题（重启生效）：", "Theme (restart required):"), self.theme_combo)

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
        self.setMinimumWidth(420)
        self.adjustSize()

    def _build_providers(self, form):
        """平时只露「哪家 + Key」。模型名和接口折起来，选自定义或豆包这种没有默认名的才展开。"""
        en = lang() == "en"
        kv = self._kv

        self.prov = _Combo()
        for p in providers.PRESETS:
            self.prov.addItem(p[2] if en else p[1], p[0])
        pid = kv.get("ECHO_LLM_PROVIDER") or "deepseek"
        if pid not in {p[0] for p in providers.PRESETS}:
            pid = "deepseek"
        self._select(self.prov, pid)
        form.addRow(tr("用哪家：", "Provider:"), self.prov)

        preset = providers.preset(pid)
        legacy_key = ""
        if pid == "deepseek":
            legacy_key = kv.get("DEEPSEEK_API_KEY", "")
        elif pid == "qwen":
            legacy_key = kv.get("DASHSCOPE_API_KEY", "")
        self.key_edit = QLineEdit(kv.get("ECHO_LLM_API_KEY") or legacy_key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setFont(font(12))
        form.addRow(tr("API Key：", "API key:"), self.key_edit)

        saved_model = kv.get("ECHO_LLM_MODEL") or preset[4]
        saved_base = kv.get("ECHO_LLM_BASE_URL") or preset[3]
        saved_model = providers.current_model(pid, saved_base, saved_model)
        self.adv = QCheckBox(tr("自己填模型名和接口", "Set the model name and URL myself"))
        self.adv.setChecked(
            pid == "custom" or not preset[4]
            or saved_model != preset[4] or (saved_base != preset[3] and bool(saved_base)))
        form.addRow(self.adv)

        self.adv_box = QWidget()
        adv = QFormLayout(self.adv_box)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(8)
        self.model_edit = QLineEdit(saved_model)
        self.model_edit.setFont(font(12))
        self.base_edit = QLineEdit(saved_base)
        self.base_edit.setFont(font(12))
        self.base_edit.setPlaceholderText("https://…/v1")
        adv.addRow(tr("模型名：", "Model:"), self.model_edit)
        adv.addRow(tr("接口：", "URL:"), self.base_edit)
        form.addRow(self.adv_box)
        self.prov.currentIndexChanged.connect(self._on_text_provider)
        self.adv.toggled.connect(self._on_adv)
        self._sync_provider_fields()

        self.vprov = _Combo()
        self.vprov.addItem(tr("跟上面同一家", "Same provider"), "same")
        for p in providers.PRESETS:
            if p[5] or p[0] == "custom":
                self.vprov.addItem(p[2] if en else p[1], p[0])
        vid = kv.get("ECHO_VISION_PROVIDER") or ""
        if not vid:
            vid = "qwen" if kv.get("DASHSCOPE_API_KEY") and not kv.get("ECHO_LLM_PROVIDER") else "same"
        self._select(self.vprov, vid)
        form.addRow(tr("视觉模型：", "Vision provider:"), self.vprov)

        self.vision_box = QWidget()
        vf = QFormLayout(self.vision_box)
        vf.setContentsMargins(0, 0, 0, 0)
        vf.setSpacing(8)
        vkey = kv.get("ECHO_VISION_API_KEY", "")
        if not vkey and vid == "qwen":
            vkey = kv.get("DASHSCOPE_API_KEY", "")
        self.vkey_edit = QLineEdit(vkey)
        self.vkey_edit.setEchoMode(QLineEdit.Password)
        self.vkey_edit.setFont(font(12))
        self.vkey_edit.setPlaceholderText(tr("留空就用上面的 Key", "Blank = use the key above"))
        vf.addRow(tr("Key：", "Key:"), self.vkey_edit)
        vmodel = kv.get("ECHO_VISION_MODEL") or (providers.preset(vid)[5] if vid != "same" else "")
        if vid != "same":
            vmodel = providers.current_model(vid, kv.get("ECHO_VISION_BASE_URL") or providers.preset(vid)[3], vmodel)
        self.vmodel_edit = QLineEdit(vmodel)
        self.vmodel_edit.setFont(font(12))
        vf.addRow(tr("模型名：", "Model:"), self.vmodel_edit)
        self.vbase_lbl = QLabel(tr("接口：", "URL:"))
        self.vbase_edit = QLineEdit(kv.get("ECHO_VISION_BASE_URL", ""))
        self.vbase_edit.setFont(font(12))
        self.vbase_edit.setPlaceholderText("https://…/v1")
        vf.addRow(self.vbase_lbl, self.vbase_edit)
        form.addRow(self.vision_box)
        self.vprov.currentIndexChanged.connect(self._on_vision_provider)
        self._sync_vision_fields()

    @staticmethod
    def _select(combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _sync_provider_fields(self):
        pid = self.prov.currentData()
        custom = pid == "custom"
        self.adv.setVisible(not custom)
        self.adv_box.setVisible(custom or self.adv.isChecked())
        if pid == "ollama":
            self.key_edit.setPlaceholderText(tr("本地不用填", "Not needed for local Ollama"))
        elif pid == "doubao":
            self.key_edit.setPlaceholderText(tr("火山方舟的 API Key", "Volcengine API key"))
            self.model_edit.setPlaceholderText(tr("接入点，例如 ep-xxxx", "Endpoint id, e.g. ep-xxxx"))
        else:
            self.key_edit.setPlaceholderText("sk-…")
            self.model_edit.setPlaceholderText("")
        if self.isVisible():
            self.adjustSize()

    def _on_adv(self, on):
        if not on and self.prov.currentData() != "custom":
            p = providers.preset(self.prov.currentData())
            self.model_edit.setText(p[4])
            self.base_edit.setText(p[3])
        self._sync_provider_fields()

    def _on_text_provider(self):
        """换一家就换成那家的默认模型。展开着的输入框跟着变，省得还留着上一家的名字。"""
        p = providers.preset(self.prov.currentData())
        self.model_edit.setText(p[4])
        self.base_edit.setText(p[3])
        self.adv.setChecked(not p[4])
        self._sync_provider_fields()

    def _sync_vision_fields(self):
        vid = self.vprov.currentData()
        self.vision_box.setVisible(vid != "same")
        custom = vid == "custom"
        self.vbase_lbl.setVisible(custom)
        self.vbase_edit.setVisible(custom)
        if self.isVisible():
            self.adjustSize()

    def _on_vision_provider(self):
        vid = self.vprov.currentData()
        if vid != "same":
            p = providers.preset(vid)
            self.vmodel_edit.setText(p[5])
            if vid != "custom":
                self.vbase_edit.clear()
        self._sync_vision_fields()

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
        pid = self.prov.currentData()
        vid = self.vprov.currentData()
        updates = {k: cb.currentData() for k, cb in self.combos.items()}
        updates.update({
            "ECHO_LLM_PROVIDER": pid,
            "ECHO_LLM_API_KEY": self.key_edit.text().strip(),
            "ECHO_LLM_MODEL": self.model_edit.text().strip(),
            "ECHO_LLM_BASE_URL": self.base_edit.text().strip(),
            "ECHO_VISION_PROVIDER": vid,
            "ECHO_VISION_API_KEY": self.vkey_edit.text().strip(),
            "ECHO_VISION_MODEL": self.vmodel_edit.text().strip() if vid != "same" else "",
            "ECHO_VISION_BASE_URL": self.vbase_edit.text().strip() if vid == "custom" else "",
        })
        # 老字段继续写一份：没升级过的代码、以及「没填新字段就用 DEEPSEEK_*」的回退还认它们
        if pid == "deepseek":
            updates["DEEPSEEK_API_KEY"] = updates["ECHO_LLM_API_KEY"]
            updates["DEEPSEEK_MODEL"] = updates["ECHO_LLM_MODEL"] or providers.preset("deepseek")[4]
            updates["DEEPSEEK_BASE_URL"] = updates["ECHO_LLM_BASE_URL"] or "https://api.deepseek.com"
        if vid == "qwen" and updates["ECHO_VISION_API_KEY"]:
            updates["DASHSCOPE_API_KEY"] = updates["ECHO_VISION_API_KEY"]
            if updates["ECHO_VISION_MODEL"]:
                updates["ECHO_QWEN_VL_MODEL"] = updates["ECHO_VISION_MODEL"]
        try:
            _write_env(updates)
        except OSError as e:
            from echo.widgets import dialogs
            dialogs.warn(self, tr("保存失败", "Save failed"),
                         f"{tr('写 .env 失败：', 'Failed to write .env: ')}{e}")
            return
        for k, v in updates.items():
            os.environ[k] = v
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
        QSettings("Echo", "Echo").setValue("interface_theme", self.theme_combo.currentData())
        QSettings("Echo", "Echo").setValue("desktop_pet_skin", skin)
        from echo.widgets.desk_pet import DeskPet
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, DeskPet):
                widget.set_skin(skin)
        self.accept()


def open_settings_dialog(parent=None):
    dlg = SettingsDialog(parent)
    dlg.exec_()
