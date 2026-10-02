"""
Echo - 确认 / 提示弹窗

QMessageBox 的静态方法（information / question / getText）有三个毛病：
  1. 按钮文案跟着系统语言走，中文界面下弹出来是 OK / Yes / No
  2. 没法在弹之前调样式（深色主题下会白字贴白底，见 theme.py 里那段注释）
  3. 系统标题栏不跟着深浅色主题走，深色界面里顶着一条白条，内容和标题栏一半黑一半白

这里统一包一层，宿主只管调 echo.widgets.dialogs 里的函数。
"""
from PyQt5.QtWidgets import QInputDialog, QMessageBox

from echo.i18n import tr
from echo.theme import dialog_qss, apply_native_titlebar


def info(parent, title: str, text: str):
    """只有「知道了」的提示框。"""
    return _notice(parent, title, text, QMessageBox.Information)


def warn(parent, title: str, text: str):
    """出错了的提示框，图标用警告。"""
    return _notice(parent, title, text, QMessageBox.Warning)


def _notice(parent, title: str, text: str, icon):
    box = QMessageBox(parent)
    apply_native_titlebar(box)
    box.setStyleSheet(dialog_qss())
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.addButton(tr("知道了", "OK"), QMessageBox.AcceptRole)
    box.exec_()
    return box


def confirm(parent, title: str, text: str, ok_text: str = "") -> bool:
    """确认框。学生点「确定」返回 True，点「取消」或直接关掉返回 False。"""
    box = QMessageBox(parent)
    apply_native_titlebar(box)
    box.setStyleSheet(dialog_qss())
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(text)
    ok = box.addButton(ok_text or tr("确定", "Yes"), QMessageBox.YesRole)
    box.addButton(tr("取消", "Cancel"), QMessageBox.NoRole)
    box.setDefaultButton(ok)
    box.exec_()
    return box.clickedButton() is ok


def ask_text(parent, title: str, label: str, default: str = ""):
    """单行输入框。返回 (文本, 是否确认)。"""
    dlg = QInputDialog(parent)
    apply_native_titlebar(dlg)
    dlg.setStyleSheet(dialog_qss())
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(default or "")
    dlg.setOkButtonText(tr("确定", "OK"))
    dlg.setCancelButtonText(tr("取消", "Cancel"))
    dlg.resize(max(dlg.width(), 380), dlg.height())
    accepted = dlg.exec_() == QInputDialog.Accepted
    return dlg.textValue(), accepted
