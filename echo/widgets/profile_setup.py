"""
Echo - 首次登录

第一次打开 Echo 时弹出来，让学生填姓名、昵称、年龄、爱好。
点「开始使用」后写进 profile.json（echo.backend.profile），以后启动不再弹。
资料没存下来就不放行：写文件失败会提示并留在这个窗口；直接关掉窗口则退出 Echo，下次启动再问。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                             QSpinBox, QVBoxLayout)

from echo.backend import profile
from echo.i18n import tr
from echo.theme import Colors, font
from echo.widgets import dialogs
from echo.widgets.settings import dialog_qss


class ProfileSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("欢迎使用 Echo", "Welcome to Echo"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
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
        self.resize(440, 320)

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
        self.accept()


def ensure_profile() -> bool:
    """没填过资料就弹首次登录。返回 False 表示学生关掉了窗口，调用方应退出。"""
    if profile.exists():
        return True
    return ProfileSetupDialog().exec_() == QDialog.Accepted
