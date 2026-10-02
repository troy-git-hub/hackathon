"""
Echo - 首次登录

第一次打开 Echo 时弹出来，让学生填姓名、昵称、年龄、爱好。
点「开始使用」后写进 profile.json（echo.backend.profile），以后启动不再弹。
资料没存下来就不放行：写文件失败会提示并留在这个窗口；直接关掉窗口则退出 Echo，下次启动再问。
"""
import os
import tempfile

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout)

from echo.backend import profile
from echo.components.avatar import AvatarView, load_normalized
from echo.i18n import tr
from echo.theme import Colors, font
from echo.widgets import dialogs
from echo.widgets.settings import dialog_qss


class ProfileSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("欢迎使用 Echo", "Welcome to Echo"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._avatar_pm = None        # 预览中的头像（还没落盘；None = 用默认喵喵）
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 14)
        root.setSpacing(10)

        title = QLabel(tr("先认识一下你吧", "Let's get to know you"))
        title.setFont(font(16, 600))
        root.addWidget(title)
        sub = QLabel(tr("资料只保存在本机，不会上传。以后可以在设置里改用户名。",
                        "Your profile stays on this computer and is never uploaded. "
                        "You can change your user name later in Settings."))
        sub.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; font-size:12px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # 头像（可选）：不选就用默认喵喵。选中后只是预览，点「开始使用」才真正存。
        avatar_row = QHBoxLayout()
        avatar_row.setSpacing(14)
        self.avatar_view = AvatarView(72)
        avatar_row.addWidget(self.avatar_view, 0, Qt.AlignTop)
        a_col = QVBoxLayout()
        a_col.setSpacing(6)
        self.avatar_hint = QLabel(tr("挑一张头像吧，不想挑就用默认的喵喵。",
                                     "Pick a photo — or just keep the default cat."))
        self.avatar_hint.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; font-size:12px;")
        self.avatar_hint.setWordWrap(True)
        a_col.addWidget(self.avatar_hint)
        a_btns = QHBoxLayout()
        a_btns.setSpacing(6)
        self.btn_pick_avatar = QPushButton(tr("选一张图", "Choose a photo"))
        self.btn_pick_avatar.clicked.connect(self._pick_avatar)
        a_btns.addWidget(self.btn_pick_avatar)
        self.btn_default_avatar = QPushButton(tr("用默认喵喵", "Use the default cat"))
        self.btn_default_avatar.clicked.connect(self._use_default_avatar)
        a_btns.addWidget(self.btn_default_avatar)
        a_btns.addStretch()
        a_col.addLayout(a_btns)
        a_col.addStretch()
        avatar_row.addLayout(a_col, 1)
        root.addLayout(avatar_row)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.name = self._line(tr("必填", "Required"))
        form.addRow(tr("姓名：", "Name:"), self.name)
        self.nickname = self._line(tr("必填，Echo 会这样叫你", "Required — what Echo will call you"))
        form.addRow(tr("昵称：", "Nickname:"), self.nickname)

        self.age = QSpinBox()
        self.age.setRange(0, 120)
        self.age.setSpecialValueText(tr("不填", "Skip"))   # 0 = 没填
        self.age.setFont(font(12))
        form.addRow(tr("年龄：", "Age:"), self.age)

        self.hobbies = self._line(tr("比如：篮球、画画、编程（选填）",
                                     "e.g. basketball, drawing, coding (optional)"))
        form.addRow(tr("爱好：", "Hobbies:"), self.hobbies)
        root.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.button(QDialogButtonBox.Ok).setText(tr("开始使用", "Get started"))
        btns.accepted.connect(self._save)
        root.addWidget(btns)

        self.setStyleSheet(dialog_qss())
        self.resize(460, 450)        # 比原来高：加了头像那一段

    def _line(self, placeholder):
        ed = QLineEdit()
        ed.setPlaceholderText(placeholder)
        ed.setFont(font(12))
        return ed

    def _save(self):
        name = self.name.text().strip()
        nickname = self.nickname.text().strip()
        if not name or not nickname:
            dialogs.warn(self, tr("还差一点", "Almost there"),
                         tr("姓名和昵称都要填哦。", "Please fill in both your name and nickname."))
            (self.name if not name else self.nickname).setFocus()
            return
        try:
            profile.save({
                "name": name,
                "nickname": nickname,
                "age": self.age.value() or None,
                "hobbies": self.hobbies.text().strip(),
                "username": nickname,       # 设置里的「用户：」默认就是昵称
            })
        except OSError as e:
            dialogs.warn(self, tr("保存失败", "Save failed"),
                         f"{tr('资料没能保存：', 'Could not save your profile: ')}{e}")
            return
        if self._avatar_pm is not None:
            self._save_avatar()
        self.accept()

    # ================= 头像 =================
    def _pick_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("选一张头像", "Choose a photo"), "",
            tr("图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
               "Images (*.png *.jpg *.jpeg *.webp *.bmp)"))
        if not path:
            return
        pm = load_normalized(path)
        if pm.isNull():
            dialogs.warn(self, tr("这张图读不了", "Can't read that image"),
                         tr("换一张试试（支持 PNG / JPG / WebP / BMP）。",
                            "Try another one (PNG / JPG / WebP / BMP)."))
            return
        self._avatar_pm = pm
        self.avatar_view.set_pixmap(pm)
        self.avatar_hint.setText(tr("就用这张。不满意可以再选，或者换回喵喵。",
                                    "Looks good. Pick again anytime, or switch back to the cat."))

    def _use_default_avatar(self):
        self._avatar_pm = None
        self.avatar_view.set_pixmap(None)          # None → 退回默认喵喵
        self.avatar_hint.setText(tr("挑一张头像吧，不想挑就用默认的喵喵。",
                                    "Pick a photo — or just keep the default cat."))

    def _save_avatar(self):
        """把预览的图写进配置目录。

        存的是**规范化后的图**（EXIF 旋转已应用、长边已缩到 512），不是用户原图的
        路径：原图被删掉、挪走、换台机器都不影响头像。中间过一道临时文件，是因为
        backend 的 profile 只负责拷文件（它不能引 PyQt5，没法直接存 QPixmap）。
        头像没存上不算致命 —— 资料已经存好了，退回默认喵喵就是了。
        """
        tmp = os.path.join(tempfile.gettempdir(), f"echo-avatar-{os.getpid()}.png")
        try:
            if not self._avatar_pm.save(tmp, "PNG"):
                return
            profile.set_avatar(tmp)
        except OSError:
            pass
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass


def ensure_profile() -> bool:
    """没填过资料就弹首次登录。返回 False 表示学生关掉了窗口，调用方应退出。"""
    if profile.exists():
        return True
    return ProfileSetupDialog().exec_() == QDialog.Accepted
