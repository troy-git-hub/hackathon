"""
Echo - 设置

一个简单的设置窗口：选模型厂商并填 API key（文本 / 视觉分开）、音频来源、Whisper 模型、
界面语言、桌宠皮肤。保存后写回 .env（保留原有注释和其它配置项），并写进当前进程的环境变量，
下一次提问就换厂商。已经开着的这节课是启动时接上的，要重新开一节或重启才换。
「用户：」一栏写到用户资料 profile.json（见 echo.backend.profile），下次开机问候就用新名字。
语言和皮肤不用重启。
"""
import os
import datetime

from PyQt5.QtCore import Qt, QSettings, QStandardPaths
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout, QWidget, QFileDialog, QScrollArea,QListWidget,QListWidgetItem)

from echo.backend import cache, paths, profile, providers
from echo.theme import Colors, font, dialog_qss, apply_native_titlebar
from echo.i18n import tr, lang, set_lang

# 打包后写到 %APPDATA%\Echo\.env（安装目录在 C:\Program Files 下不可写），开发时写到项目根目录
ROOT = paths.app_dir()
ENV_PATH = paths.ensure_env()
ENV_EXAMPLE = paths.example_env()

COMBOS = [
    ("ECHO_AI_ACTIVITY", tr("课堂 AI 频率", "Lesson AI frequency"), ["active", "balanced", "economy"],
     [tr("积极 · 20秒起，更多调用", "Active · from 20s, more calls"),
      tr("均衡 · 35秒起", "Balanced · from 35s"), tr("节省 · 50秒起", "Economy · from 50s")]),
    ("ECHO_CAPTION_MODE", tr("字幕速度", "Caption latency"), ["fast", "balanced", "accurate"],
     [tr("快速 · 约2.4秒切片", "Fast · ~2.4s slices"), tr("均衡 · 约3.6秒切片", "Balanced · ~3.6s slices"),
      tr("准确优先 · 约6秒切片", "Accuracy · ~6s slices")]),
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
        self.setWindowFlags((self.windowFlags() & ~Qt.WindowContextHelpButtonHint)|Qt.Window|Qt.WindowStaysOnTopHint)
        self.setWindowModality(Qt.NonModal)
        apply_native_titlebar(self)
        self._kv = _read_env()
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(10)
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content.setObjectName("SettingsContent")
        content.setAttribute(Qt.WA_StyledBackground, True)
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 8, 0)
        body.setSpacing(10)
        scroll.setWidget(content)
        root.addWidget(scroll)

        title = QLabel(tr("Echo 设置", "Echo Settings"))
        title.setFont(font(16, 600))
        body.addWidget(title)
        # 默认隐藏「用自己的 AI」：普通用户都走 Echo 账户服务，不该看到这排开关。
        # 配置文件（.env）写 ECHO_SHOW_CUSTOM_API=1 可重新显示；
        # 已经在用自定义 API（ECHO_ACCOUNT_CUSTOM_API=1）或访客模式的保留开关。
        show_custom_api = (self._kv.get("ECHO_SHOW_CUSTOM_API", "0") == "1"
                           or self._kv.get("ECHO_ACCOUNT_CUSTOM_API", "0") == "1"
                           or os.getenv("ECHO_ACCOUNT_GUEST") == "1")
        if show_custom_api:
            sub = QLabel(tr("默认使用 Echo 账户服务。自己的模型 API 与更新地址可在高级设置中调整。",
                            "Echo account services are the default. Custom model APIs and the update URL are in Advanced settings."))
        else:
            sub = QLabel(tr("模型由 Echo 账户服务提供，登录即用；更新地址在高级设置。",
                            "Models come with your Echo account. The update URL is in Advanced settings."))
        sub.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; font-size:12px;")
        sub.setWordWrap(True)
        body.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        def _section(title):
            """分节小标题：把一长条设置分成几段，不用大改布局。"""
            lbl = QLabel(title)
            lbl.setStyleSheet(f'color:{Colors.TEXT_SECONDARY};font-size:11px;font-weight:600;'
                              'letter-spacing:1px;padding-top:6px;')
            return lbl

        form.addRow("", _section(tr("通用", "General")))
        # 用户名：开机问候「你好 + 用户名」用的就是它，存在 profile.json
        self._profile = profile.load()
        self.user_edit = QLineEdit(profile.display_name(self._profile))
        self.user_edit.setPlaceholderText(tr("开机问候时怎么称呼你", "What Echo calls you when it starts"))
        self.user_edit.setFont(font(12))
        form.addRow(tr("用户：", "User:"), self.user_edit)

        self.reasoning_combo = _Combo()
        for title, value in [("关闭 · 直接回答", "none"), ("低 · 默认", "low"), ("高", "high"), ("最高", "max")]:
            self.reasoning_combo.addItem(title, value)
        self.reasoning_combo.setCurrentIndex(max(0, self.reasoning_combo.findData(self._kv.get("ECHO_REASONING_EFFORT", "low"))))
        self.reasoning_combo.setToolTip("用于支持思考的 DS 模型；思考会增加等待和学习点消耗。")
        form.addRow("DS 思考强度：", self.reasoning_combo)

        self.advanced_widget = QWidget()
        advanced_form = QFormLayout(self.advanced_widget)
        self.custom_api = QCheckBox(tr("使用自己的模型 API（高级）", "Use my own model API (advanced)"))
        self.custom_api.setChecked(os.getenv('ECHO_ACCOUNT_GUEST')=='1' or self._kv.get('ECHO_ACCOUNT_CUSTOM_API','0') == '1')
        if show_custom_api:
            advanced_form.addRow('', self.custom_api)
        self._build_providers(advanced_form)

        form.addRow("", _section(tr("课堂与语音", "Lesson and voice")))
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
        # 界面动画：默认跟随系统（Windows 的「在 Windows 中显示动画」）。改完立即生效。
        from echo.widgets import motion
        self.motion_combo = _Combo()
        for _motion_label, _motion_value in ((tr("跟随系统", "Follow system"), "system"),
                                             (tr("开启", "On"), "on"),
                                             (tr("关闭", "Off"), "off")):
            self.motion_combo.addItem(_motion_label, _motion_value)
        self._select(self.motion_combo, motion.mode())
        form.addRow(tr("界面动画：", "UI animation:"), self.motion_combo)
        # 新手引导：跳过/完成后想再看，随时从这里重来一遍
        self.btn_onboarding = QPushButton(tr("重看新手引导", "Show getting-started guide"))
        def _show_guide():
            from echo.widgets.onboarding import open_onboarding
            open_onboarding(self)
        self.btn_onboarding.clicked.connect(_show_guide)
        form.addRow("", self.btn_onboarding)
        from echo.widgets.update_center import DEFAULT_URL
        update_settings = QSettings("Echo", "Echo")
        configured_url = update_settings.value("update_url", DEFAULT_URL, type=str)
        if configured_url.rstrip('/') in ('http://127.0.0.1:8787','http://localhost:8787'):
            configured_url=DEFAULT_URL
        self.update_url = QLineEdit(configured_url)
        self.update_url.setPlaceholderText("https://update.echo.xhbtroy.cn")
        advanced_form.addRow(tr("更新服务地址：", "Update service:"), self.update_url)
        self.auto_update = QCheckBox(tr("每次启动检查并后台下载更新", "Check and download on startup"))
        self.auto_update.setChecked(QSettings("Echo", "Echo").value("auto_update_check", True, type=bool))
        form.addRow("", _section(tr("更新", "Updates")))
        form.addRow("", self.auto_update)
        from echo.version import VERSION
        self.btn_updates = QPushButton(tr(f"更新中心 · 当前 {VERSION}", f"Update center · {VERSION}"))
        self.btn_updates.clicked.connect(self._open_update_center)
        form.addRow("", self.btn_updates)
        self.update_progress=QLabel('');self.update_progress.setWordWrap(True)
        self.update_progress.setStyleSheet(f'color:{Colors.TEXT_SECONDARY};font-size:12px;')
        form.addRow('',self.update_progress)
        controller=self._update_controller()
        def render_update_progress():
            c=controller
            text=c.message
            if c.state=='downloading':text+=f'  {c.done/1048576:.1f} / {c.total/1048576:.1f} MB'
            self.update_progress.setText(text or '自动更新开启时，每次启动检查；发现新版后台下载，可在更新中心取消。')
        controller.changed.connect(render_update_progress);render_update_progress()
        def detach_update_progress(_):
            try:controller.changed.disconnect(render_update_progress)
            except (TypeError,RuntimeError):pass
        self.finished.connect(detach_update_progress)

        self.btn_library = QPushButton(tr("知识库 · 教材、讲义与笔记", "Knowledge library · course references"))
        self.btn_library.clicked.connect(self._open_library)
        form.addRow("", _section(tr("工具", "Tools")))
        form.addRow("", self.btn_library)

        body.addLayout(form)
        body.addWidget(_section(tr("账户与同步", "Account and sync")))
        self.account_button = QPushButton(tr("用户中心 · 账户与学习点", "Account center · learning credits"))
        self.account_button.clicked.connect(self._open_account_center)
        body.addWidget(self.account_button)
        self.learning_goal_button = QPushButton(tr('学习目标 · 兴趣与每日安排','Learning goal · interests and daily plan'))
        self.learning_goal_button.clicked.connect(self._open_learning_goal)
        body.addWidget(self.learning_goal_button)
        self.ai_usage_button=QPushButton('AI 调用与用量 · 清卷 / 课堂 / 批改')
        self.ai_usage_button.clicked.connect(self._open_ai_usage)
        body.addWidget(self.ai_usage_button)
        from echo.backend import account
        self.admin_button=QPushButton(tr('管理员后台 ↗','Administrator ↗'))
        self.admin_button.setObjectName('Link')
        self.admin_button.setToolTip(tr('仅管理员账户可用，在浏览器中打开','Available to administrators; opens in your browser'))
        self.admin_button.clicked.connect(self._open_admin)
        self.admin_button.setVisible((account.current_user() or {}).get('role')=='admin')
        body.addWidget(self.admin_button)
        self.security_button=QPushButton(tr('安全设置 · 验证器与通行密钥 ↗','Security · authenticators and passkeys ↗'))
        def open_security():
            from PyQt5.QtCore import QUrl
            from PyQt5.QtGui import QDesktopServices
            role=(account.current_user() or {}).get('role')
            QDesktopServices.openUrl(QUrl('https://echo.xhbtroy.cn/admin#security' if role=='admin' else 'https://echo.xhbtroy.cn/user#security'))
        self.security_button.clicked.connect(open_security)
        body.addWidget(self.security_button)

        from echo.backend import cloud_sync
        self.cloud_auto=QCheckBox(tr('这台设备自动同步学习档案（登录后生效）','Automatically sync learning data when signed in'))
        self.cloud_auto.setChecked(cloud_sync.status()['enabled'])
        body.addWidget(self.cloud_auto)
        cloud_state=cloud_sync.status()
        self.cloud_device_name=QLineEdit(cloud_state.get('device_name','Echo Desktop'))
        self.cloud_device_name.setMaxLength(60);self.cloud_device_name.setPlaceholderText('例如：我的 Windows 笔记本')
        body.addWidget(QLabel('本机终端名称'));body.addWidget(self.cloud_device_name)
        self.cloud_mode=_Combo();self.cloud_mode.addItem('默认合并 · 同步所有终端','merge');self.cloud_mode.addItem('指定来源 · 仅同步勾选终端','selected')
        self._select(self.cloud_mode,cloud_state.get('mode','merge'));body.addWidget(self.cloud_mode)
        self.cloud_sources=QListWidget();self.cloud_sources.setStyleSheet(f'QListWidget{{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};border-radius:8px;padding:6px;}} QListWidget::item{{color:{Colors.TEXT_PRIMARY};padding:5px;}} QListWidget::item:selected{{background:{Colors.SURFACE_HOVER};}} QListWidget:disabled{{color:{Colors.TEXT_SECONDARY};background:{Colors.SURFACE};}}');self.cloud_sources.setMaximumHeight(130);body.addWidget(self.cloud_sources)
        self.cloud_mode.currentIndexChanged.connect(lambda _:self.cloud_sources.setEnabled(self.cloud_mode.currentData()=='selected'))
        self.cloud_sources.setEnabled(self.cloud_mode.currentData()=='selected')
        self.cloud_refresh_sources=QPushButton('刷新终端列表（不调用 AI）');self.cloud_refresh_sources.clicked.connect(self._refresh_cloud_sources);body.addWidget(self.cloud_refresh_sources)
        self._populate_cloud_sources(cloud_state.get('devices',[]))
        self.cloud_sync_now=QPushButton(tr('立即同步到云端','Sync to cloud now'))
        self.cloud_sync_now.clicked.connect(self._sync_cloud_now);body.addWidget(self.cloud_sync_now)
        self.cloud_sync_status=QLabel('');self.cloud_sync_status.setWordWrap(True);body.addWidget(self.cloud_sync_status)
        cloud_note=QLabel(tr('默认合并其他终端的课堂回顾与复习进度；可指定来源或暂停。本机课程保留，不上传密钥、录音、截图和原始课件。','Syncs learning indicators and review progress, excluding keys, recordings, screenshots and source materials.'))
        cloud_note.setWordWrap(True);cloud_note.setStyleSheet(f'color:{Colors.TEXT_SECONDARY};font-size:11px;');body.addWidget(cloud_note)
        self.advanced_toggle = QPushButton(tr("高级设置 · 模型 API 与更新地址", "Advanced · model APIs and update URL"))
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self.advanced_widget.setVisible)
        body.addWidget(self.advanced_toggle)
        body.addWidget(self.advanced_widget)
        self.advanced_widget.hide()

        # 存储：攒了多少东西 + 一键清空
        body.addSpacing(4)
        self.storage_lbl = QLabel("")
        self.storage_lbl.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; font-size:12px;")
        self.storage_lbl.setWordWrap(True)
        body.addWidget(self.storage_lbl)
        srow = QHBoxLayout()
        self.btn_export_data = QPushButton(tr("导出学习档案（JSON）", "Export learning profile (JSON)"))
        self.btn_export_data.clicked.connect(self._export_learning_data)
        self.btn_export_data.setToolTip(tr("包含个人资料、掌握情况、薄弱知识和复习记录；不导出模型密钥、音频或截图。",
                                          "Includes your profile and learning indicators; excludes model keys, audio and screenshots."))
        srow.addWidget(self.btn_export_data)
        self.btn_clear = QPushButton(tr("清除所有缓存", "Clear all data"))
        self.btn_clear.clicked.connect(self._clear_cache)
        srow.addWidget(self.btn_clear)
        srow.addStretch()
        body.addLayout(srow)
        self.btn_export_help = QPushButton(tr("JSON 格式与其他项目接入说明", "JSON format and integration guide"))
        self.btn_export_help.setObjectName("Link")
        self.btn_export_help.clicked.connect(self._export_format_help)
        body.addWidget(self.btn_export_help)
        self.btn_logs = QPushButton(tr("日志与诊断 · 查看 / 导出", "Diagnostics · view / export"))
        self.btn_logs.clicked.connect(self._open_logs)
        body.addWidget(self.btn_logs)
        self._refresh_storage()

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText(tr("保存", "Save"))
        btns.button(QDialogButtonBox.Cancel).setText(tr("取消", "Cancel"))
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self.setStyleSheet(dialog_qss() + f"QScrollArea#SettingsScroll, QWidget#SettingsContent {{ background:{Colors.WINDOW_BG}; border:none; }}")
        from echo.widgets.window_chrome import install_chrome
        install_chrome(self,root,minimize=False)
        self.setMinimumWidth(420)
        self.adjustSize()
        screen = QApplication.primaryScreen()
        height = screen.availableGeometry().height() if screen else 900
        self.resize(max(540, self.sizeHint().width()), min(760, int(height * .85)))

    def _export_learning_data(self):
        from echo.backend import learning_export
        from echo.widgets import dialogs
        from echo.widgets.export_options import ExportOptionsDialog
        options = ExportOptionsDialog(self)
        if options.exec_() != QDialog.Accepted:
            return
        directory = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
        default = os.path.join(directory, f"Echo-learning-profile-{datetime.date.today().isoformat()}.json")
        filename, _ = QFileDialog.getSaveFileName(self, tr("导出个人学习档案", "Export personal learning profile"), default, "JSON (*.json)")
        if not filename:
            return
        if not filename.lower().endswith(".json"):
            filename += ".json"
        try:
            data = learning_export.export_json(filename, sections=options.selected_sections())
        except (OSError, ValueError) as exc:
            dialogs.warn(self, tr("导出失败", "Export failed"), str(exc))
            return
        dialogs.info(self, tr("学习档案已导出", "Learning profile exported"),
                     tr(f"已保存到：\n{filename}\n\n已导出 {len(data['selected_sections'])} 项个人数据，不含逐课明细。\n格式：echo.learning-profile / 2.0.0。",
                        f"Saved to:\n{filename}\n\n{len(data['selected_sections'])} personal categories. No per-lesson details.\nFormat: echo.learning-profile / 2.0.0."))

    def _update_controller(self):
        from echo.widgets.update_center import UpdateController
        owner = self.parentWidget() or self
        if not hasattr(owner, "_updates"):
            owner._updates = UpdateController(owner)
        return owner._updates

    def _open_logs(self):
        from echo.widgets.log_viewer import LogViewer
        LogViewer(self).exec_()

    def _open_library(self):
        from echo.widgets.learning_studio import KnowledgeLibrary
        KnowledgeLibrary(self).exec_()

    def _open_account_center(self):
        from echo.widgets.account_login import show_account_center
        show_account_center(self)

    def _open_learning_goal(self):
        from echo.widgets.learning_path import open_learning_path
        open_learning_path(self)

    def _open_ai_usage(self):
        from echo.widgets.ai_usage import AIUsageDialog
        self._ai_usage=AIUsageDialog(self);self._ai_usage.exec_()

    def _open_admin(self):
        from echo.backend import account
        if (account.current_user() or {}).get('role')!='admin':return
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(account.USER_CENTER.rsplit('/user',1)[0]+'/admin'))

    def _cloud_scope_options(self):
        return {'mode':self.cloud_mode.currentData(),'source_ids':[self.cloud_sources.item(i).data(Qt.UserRole) for i in range(self.cloud_sources.count()) if self.cloud_sources.item(i).checkState()==Qt.Checked],
                'device_name':self.cloud_device_name.text().strip()}

    def _populate_cloud_sources(self,devices):
        from echo.backend import cloud_sync
        selected=set(cloud_sync.status().get('source_ids',[]))
        self.cloud_sources.clear()
        for device in devices:
            item=QListWidgetItem(str(device.get('name','Echo 终端'))+' · '+str(device['id'])[:8]);item.setData(Qt.UserRole,device['id']);item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if device['id'] in selected else Qt.Unchecked);self.cloud_sources.addItem(item)
        self.cloud_sources.setToolTip('未列出终端时先刷新。选择来源不会删除云端原件；本机原有课程保留。')

    def _refresh_cloud_sources(self):
        import threading
        from echo.backend import cloud_sync
        from echo.widgets.account_login import _Result
        self.cloud_refresh_sources.setEnabled(False);self.cloud_sync_status.setText('正在获取当前账户的终端列表…')
        self._source_bus=_Result(self);bus=self._source_bus
        def finished(kind,value,error):
            self.cloud_refresh_sources.setEnabled(True)
            if error:self.cloud_sync_status.setText(error)
            else:self._populate_cloud_sources(value);self.cloud_sync_status.setText('选择来源后保存，或立即同步。不会调用模型。')
        bus.done.connect(finished)
        def run():
            try:value=cloud_sync.available_sources(refresh=True);error=''
            except Exception as exc:value=[];error=str(exc)
            try:bus.done.emit('sources',value,error)
            except RuntimeError:pass
        threading.Thread(target=run,daemon=True,name='echo-cloud-sources').start()

    def _sync_cloud_now(self):
        import threading
        from echo.backend import cloud_sync
        from echo.widgets.account_login import _Result
        try:cloud_sync.configure(enabled=self.cloud_auto.isChecked(),**self._cloud_scope_options())
        except Exception as exc:self.cloud_sync_status.setText(str(exc));return
        self.cloud_sync_now.setEnabled(False);self.cloud_sync_status.setText(tr('正在同步…','Syncing…'))
        self._cloud_bus=_Result(self)
        def finished(kind,value,error):
            self.cloud_sync_now.setEnabled(True);self.cloud_sync_status.setText(error or value.get('message',''))
            if not error:self._populate_cloud_sources(value.get('devices',[]))
        self._cloud_bus.done.connect(finished);bus=self._cloud_bus
        def run():
            try:value=cloud_sync.sync_once();error=''
            except Exception as exc:value={};error=str(exc)
            try:bus.done.emit('sync',value,error)
            except RuntimeError:pass
        threading.Thread(target=run,daemon=True,name='echo-settings-sync').start()

    def _save_update_settings(self):
        from echo.backend.updater import validate_base_url
        from echo.widgets.update_center import DEFAULT_URL
        url = validate_base_url(self.update_url.text())
        settings = QSettings("Echo", "Echo")
        if (url != settings.value("update_url", DEFAULT_URL, type=str)
                or self.auto_update.isChecked() != settings.value("auto_update_check", True, type=bool)):
            self._update_controller().configure(url, self.auto_update.isChecked())

    def _open_update_center(self):
        try:
            self._save_update_settings()
        except ValueError as exc:
            from echo.widgets import dialogs
            dialogs.warn(self, "更新地址不可用", str(exc))
            return
        self._update_controller().show(parent=self)

    def _export_format_help(self):
        from echo.widgets import dialogs
        dialogs.info(self, tr("学习档案 JSON 格式", "Learning profile JSON format"), tr(
            "UTF-8 JSON，format=echo.learning-profile，schema_version=2.0.0。\n\n"
            "learner：个人资料与本地档案ID；selected_sections：本次勾选的数据项；\n"
            "knowledge_points：掌握状态、课程证据及最近复习情况；\n"
            "difficulties：薄弱与反复困难；reviews：复习进度。只包含你勾选的个人数据项，不包含每课摘要、原文或笔记。\n\n"
            "其他项目可用 JSON.parse 或 json.load 读取，通过 knowledge_points[].id 关联。"
            "state=weakness 表示薄弱，strength 表示相对掌握。时间为UTC ISO 8601，未知值为null。\n\n"
            "这是学习指标，不是标准化考试成绩。当前只导出已保存记录，不包含正在上课的临时内容。"
            "跨项目账号需由接入方绑定，本地ID不是登录凭证。完整字段说明见项目 docs/learning-profile-export.md。",
            "UTF-8 JSON. format=echo.learning-profile, schema_version=2.0.0.\n\n"
            "learner: profile; summary: strength/weakness IDs; knowledge_points: topic evidence and review state; "
            "difficulties: weak topics and repeated difficulty; reviews: review progress. Only selected categories; no per-lesson details.\n\n"
            "Read with JSON.parse or json.load and join knowledge_points[].id. Dates are UTC ISO 8601; unknown values are null. "
            "These are learning indicators, not exam scores. Only saved history is exported. Map the local ID to your own account; it is not an authentication token."))

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
        try:
            self._save_update_settings()
        except ValueError as exc:
            from echo.widgets import dialogs
            dialogs.warn(self, "更新地址不可用", str(exc))
            return
        pid = self.prov.currentData()
        vid = self.vprov.currentData()
        updates = {k: cb.currentData() for k, cb in self.combos.items()}
        updates.update({
            "ECHO_REASONING_EFFORT": self.reasoning_combo.currentData(),
            "ECHO_ACCOUNT_CUSTOM_API": "1" if self.custom_api.isChecked() else "0",
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
        from echo.widgets import motion
        motion.set_mode(self.motion_combo.currentData())
        QSettings("Echo", "Echo").setValue("desktop_pet_skin", skin)
        from echo.widgets.desk_pet import DeskPet
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, DeskPet):
                widget.set_skin(skin)
        from echo.backend import cloud_sync
        try:cloud_sync.configure(enabled=self.cloud_auto.isChecked(),**self._cloud_scope_options())
        except (OSError,ValueError,RuntimeError) as exc:
            from echo.widgets import dialogs
            dialogs.warn(self,tr('同步设置未保存','Sync settings not saved'),str(exc));return
        self.accept()


_settings_window=None
def open_settings_dialog(parent=None):
    global _settings_window
    if _settings_window is not None:
        _settings_window.showNormal();_settings_window.raise_();_settings_window.activateWindow();return _settings_window
    dlg=SettingsDialog(parent);_settings_window=dlg
    def closed(_):
        global _settings_window
        if _settings_window is dlg:_settings_window=None
        dlg.deleteLater()
    dlg.finished.connect(closed)
    dlg.show();dlg.raise_();dlg.activateWindow();return dlg
