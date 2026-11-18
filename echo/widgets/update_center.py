"""Non-blocking update state machine and the Echo update center."""
import subprocess
import threading
import time
import logging
from pathlib import Path

from PyQt5.QtCore import QObject, QSettings, QTimer, pyqtSignal, QUrl, Qt
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QApplication
from echo.backend import paths, updater
from echo.theme import Colors, dialog_qss, font
from echo.version import VERSION
from echo.i18n import tr

DEFAULT_URL = "https://update.echo.xhbtroy.cn"


class UpdateController(QObject):
    changed = pyqtSignal()
    available = pyqtSignal(str)
    completed = pyqtSignal(int, str, object, str)
    progressed = pyqtSignal(int, int, int)

    def __init__(self, owner=None):
        super().__init__(owner)
        self.owner = owner
        self.state, self.message = "idle", ""
        self.info, self.package = None, None
        self.done, self.total = 0, 0
        self.generation = 0
        self.cancel_event = threading.Event()
        self.next_auto = 0
        self.dialog = None
        self._startup_checked = False
        self._automatic = False
        self._exit_applied = False
        if QApplication.instance():QApplication.instance().aboutToQuit.connect(self._apply_on_exit)
        self.completed.connect(self._finished)
        self.progressed.connect(self._progress)
        self.poll = QTimer(self, interval=60000)
        self.poll.timeout.connect(self.auto_check)
        if owner and hasattr(owner, "echo"):
            owner.echo.status.connect(lambda _: self.changed.emit())

    def start(self):
        if not paths.is_frozen():
            return
        self.poll.start()
        QTimer.singleShot(3000, self.auto_check)

    def in_class(self):
        return bool(getattr(getattr(getattr(self.owner, "echo", None), "engine", None), "active", False))

    def url(self):
        settings=QSettings("Echo", "Echo")
        configured=settings.value("update_url", DEFAULT_URL, type=str)
        if configured in ("http://127.0.0.1:8787", "http://localhost:8787", "http://127.0.0.1:8787/", "http://localhost:8787/"):
            settings.setValue("update_url",DEFAULT_URL)
            settings.setValue("advanced_update_override",False)
            return DEFAULT_URL
        return configured

    def auto_check(self):
        if not paths.is_frozen():
            return
        settings = QSettings("Echo", "Echo")
        if self.state in ("checking", "downloading", "ready", "available"):
            self.changed.emit()
            return
        if not settings.value("auto_update_check", True, type=bool) or time.monotonic() < self.next_auto:
            return
        if not self._startup_checked or time.monotonic()>=self.next_auto:
            self._startup_checked=True
            self.check(automatic=True)

    def configure(self, url, automatic):
        url = updater.validate_base_url(url)
        self.cancel()
        settings = QSettings("Echo", "Echo")
        settings.setValue("update_url", url)
        settings.setValue("advanced_update_override", True)
        settings.setValue("auto_update_check", bool(automatic))
        settings.setValue("last_update_check", 0)
        self.info, self.package = None, None
        self.state, self.message = "idle", "更新地址已保存"
        self.changed.emit()

    def show(self, parent=None):
        if self.dialog is None:
            if self.dialog:self.dialog.close()
            self.dialog = UpdateCenter(self,parent)
        self.dialog.render()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def check(self, automatic=False):
        if not paths.is_frozen():
            self.state, self.message = 'disabled', '当前为源码开发版，不检查、下载或安装更新。请通过源码仓库更新。'
            self.changed.emit()
            return
        if self.state in ("checking", "downloading"):
            return
        self.generation += 1
        self._automatic=automatic
        generation, base = self.generation, self.url()
        self.state, self.message = "checking", "正在连接更新服务…"
        self.changed.emit()
        self.next_auto = time.monotonic() + 3600
        def run():
            try:
                self.completed.emit(generation, "check", updater.check_update(base), "")
            except Exception as exc:
                self.completed.emit(generation, "check", None, str(exc))
        threading.Thread(target=run, daemon=True, name="echo-update-check").start()

    def download(self):
        if not paths.is_frozen():
            self.state, self.message = 'disabled', '源码开发版不下载更新。'
            self.changed.emit()
            return
        if not self.info or not self.info["available"] or self.state == "downloading":
            return
        self.generation += 1
        generation, base, envelope = self.generation, self.url(), self.info["envelope"]
        self.cancel_event = threading.Event()
        cancel = self.cancel_event
        self.state, self.message, self.done = "downloading", "正在下载更新，完成后自动校验…", 0
        self.total = self.info["release"]["size"]
        self.changed.emit()
        def run():
            try:
                package = updater.download_update(base, envelope, Path(paths.config_dir()) / "updates",
                    lambda done, total: self.progressed.emit(generation, done, total) if generation == self.generation else None,
                    cancelled=cancel.is_set,max_bytes_per_second=1024*1024 if self._automatic else 0)
                self.completed.emit(generation, "download", str(package), "")
            except Exception as exc:
                self.completed.emit(generation, "download", None, str(exc))
        threading.Thread(target=run, daemon=True, name="echo-update-download").start()

    def cancel(self):
        self.generation += 1
        self.cancel_event.set()
        if self.state in ("checking", "downloading"):
            self.state, self.message = "cancelled", "已取消，可以稍后重试。"
            self.changed.emit()

    def _progress(self, generation, done, total):
        if self.state == "downloading" and generation == self.generation:
            self.done, self.total = done, total
            self.changed.emit()

    def _finished(self, generation, action, result, error):
        if generation != self.generation:
            return
        if error:
            logging.getLogger('echo.updater').warning('%s failed: %s', action, error)
            self.state = "error"
            self.message = "更新未完成：" + error
        elif action == "check":
            logging.getLogger('echo.updater').info('Release checked: %s', result['release']['version'])
            self.info, self.package = result, None
            self.state = "available" if result["available"] else "current"
            self.message = "新版本已就绪，选择下载即可。" if result["available"] else "你正在使用最新版本。"
            QSettings("Echo", "Echo").setValue("last_update_check", time.time())
            self.next_auto=time.monotonic()+86400
            if result["available"]:
                if self._automatic:
                    self.available.emit(result['release']['version'])
                    QTimer.singleShot(0,self.download)
                else:self.available.emit(result["release"]["version"])
        else:
            logging.getLogger('echo.updater').info('Update package verified: %s', result)
            self.package = Path(result)
            self.state, self.message = "ready", "更新已下载并验证。安装会保留个人资料与学习记录。"
        self.changed.emit()

    def _apply_on_exit(self):
        if self._automatic and self.state=='ready' and not self._exit_applied and paths.is_frozen():
            self._exit_applied=True;self.install(quitting=True)

    def install(self, quitting=False):
        if self.in_class() and not quitting:
            self.message = "请先下课，再安装更新；课堂不会被中断。"
            self.changed.emit()
            return
        if self.state != "ready" or not self.package or not self.info:
            return
        if not paths.is_frozen():
            self.message = "当前是源码运行，可在下载目录中查看安装包。"
            self.changed.emit()
            return
        try:
            release = updater.verify_for_client(self.info["envelope"])
            if updater.version_tuple(release["version"]) <= updater.version_tuple(VERSION):
                raise updater.UpdateError("不安装相同或更旧的版本")
            package = updater.verify_package(self.package, release)
            if release['format']=='echo.update/2':
                from echo.backend import fast_update
                staged=fast_update.stage(package,paths.app_dir())
                fast_update.launch(staged,paths.app_dir(),package.parent,restart=not quitting)
            else:
                subprocess.Popen([str(package), "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/UPDATE=1", f"/DIR={paths.app_dir()}"], close_fds=True)
        except Exception as exc:
            self.state, self.message = "error", str(exc)
            self.changed.emit()
            return
        self._exit_applied=True
        self.state='installing';self.changed.emit()
        if not quitting:
            if getattr(self.owner,'echo',None):self.owner.echo.shutdown()
            QApplication.instance().quit()


class UpdateCenter(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(None,Qt.Window|Qt.WindowStaysOnTopHint)
        self.setWindowModality(Qt.NonModal)
        self.controller = controller
        self.setWindowTitle("Echo · 更新中心")
        self.setMinimumWidth(520)
        self.resize(560, 540)
        self.setStyleSheet(dialog_qss())
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 24)
        root.setSpacing(14)
        eyebrow = QLabel(f"ECHO / KEEP GROWING     ·     {VERSION}")
        eyebrow.setStyleSheet(f"color:{Colors.ACCENT};font-size:11px;")
        root.addWidget(eyebrow)
        title = QLabel("让 Echo，越用越顺手。")
        title.setStyleSheet(f"font-size:25px;font-weight:600;color:{Colors.TEXT_PRIMARY};padding:4px 0;")
        root.addWidget(title)
        self.badge = QLabel()
        self.badge.setStyleSheet(f"color:{Colors.ACCENT};padding:8px 0;font-size:15px;font-weight:600;")
        root.addWidget(self.badge)
        self.description = QLabel()
        self.description.setTextFormat(Qt.PlainText)
        self.description.setWordWrap(True)
        root.addWidget(self.description)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setTextFormat(Qt.PlainText)
        self.notes.setStyleSheet(f"padding:18px;background:{Colors.SURFACE};border-radius:10px;color:{Colors.TEXT_PRIMARY};")
        root.addWidget(self.notes)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        root.addWidget(self.progress)
        self.download_size = QLabel()
        root.addWidget(self.download_size)
        root.addStretch()
        self.notice = QLabel("启动时后台检查并限速下载；退出后应用更新，不会中断课堂。")
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};font-size:12px;")
        root.addWidget(self.notice)
        row = QHBoxLayout()
        self.cancel_button = QPushButton("取消下载")
        self.cancel_button.clicked.connect(controller.cancel)
        row.addWidget(self.cancel_button)
        self.folder_button = QPushButton("打开下载目录")
        self.folder_button.clicked.connect(self.open_folder)
        row.addWidget(self.folder_button)
        row.addStretch()
        self.primary = QPushButton()
        self.primary.clicked.connect(self.primary_action)
        row.addWidget(self.primary)
        root.addLayout(row)
        from echo.widgets.window_chrome import install_chrome
        install_chrome(self,root)
        controller.changed.connect(self.render)
        self.render()

    def primary_action(self):
        state = self.controller.state
        if state == "ready":
            self.controller.install()
        elif state == "available" or state in ("error", "cancelled") and self.controller.info and self.controller.info["available"]:
            self.controller.download()
        else:
            self.controller.check()

    def open_folder(self):
        if self.controller.package:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.controller.package.parent)))

    def render(self):
        c = self.controller
        names = {"idle": "每一次更新，都更靠近听懂", "checking": "正在检查更新", "current": "已是最新版本",
                 "available": "发现新版本", "downloading": "正在下载", "ready": "更新准备好了", "error": "暂时未能完成", "cancelled": "已暂停", "disabled":"源码开发版 · 更新已禁用"}
        self.badge.setText(names.get(c.state,'更新中心'))
        self.description.setText(c.message or "检查更顺畅的字幕、板书与学习体验。")
        release = c.info["release"] if c.info else None
        self.notes.setText((f"Echo {release['version']}\n\n" + "\n".join("• " + n for n in release["notes"])) if release else "更新后保留你的资料、模型设置和学习记录。\n\n可以继续使用当前版本，等方便时再更新。")
        self.progress.setVisible(c.state in ("downloading", "ready"))
        self.progress.setValue(1000 if c.state == "ready" else int(1000 * c.done / c.total) if c.total else 0)
        self.download_size.setVisible(c.state == "downloading")
        self.download_size.setText(f"{c.done / 1048576:.1f} / {c.total / 1048576:.1f} MB")
        self.cancel_button.setVisible(c.state in ("checking", "downloading"))
        self.folder_button.setVisible(c.state == "ready")
        text = "下载更新" if c.state == "available" else "安装并重启 Echo" if c.state == "ready" else "检查更新"
        if c.state in ("error", "cancelled") and c.info and c.info["available"]:
            text = "重试下载"
        self.primary.setText(text)
        self.primary.setEnabled(paths.is_frozen() and c.state not in ("checking", "downloading", "disabled", "installing") and not (c.state == "ready" and c.in_class()))
        if c.state == "ready" and c.in_class():
            self.notice.setText("正在上课，更新已经保留。下课后再安装。")
        elif c.state == "ready" and not paths.is_frozen():
            self.notice.setText("当前为源码运行。可打开下载目录查看安装包；安装版可直接安装并重启。")
