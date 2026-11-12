"""Choose personal-data categories; per-course detail is deliberately excluded."""
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QCheckBox, QDialogButtonBox
from echo.theme import dialog_qss
from echo.i18n import tr


class ExportOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("选择个人数据项", "Choose personal data"))
        self.setMinimumWidth(420)
        self.setStyleSheet(dialog_qss())
        root = QVBoxLayout(self)
        title = QLabel(tr("导出你的学习画像", "Export your learning profile"))
        root.addWidget(title)
        tip = QLabel(tr("勾选需要接入其他项目的数据。不导出每一节课的明细、原文或笔记。",
                        "Select categories to share. Individual lessons, transcripts and notes are excluded."))
        tip.setWordWrap(True)
        root.addWidget(tip)
        self.choices = {}
        for key, zh, en in (
            ("profile", "个人资料：姓名、昵称、年龄、爱好", "Profile: name, nickname, age, interests"),
            ("mastery", "知识掌握：相对掌握、学习中、待加强", "Knowledge and mastery indicators"),
            ("difficulties", "薄弱与反复困难：不太会什么、常卡在哪里", "Weaknesses and recurring difficulties"),
            ("reviews", "复习进度：疑点、自评、复习次数与下次时间", "Review progress and self-reports"),
            ("preferences", "学习偏好：近期是否需要更多解释", "Learning support preferences")):
            choice = QCheckBox(tr(zh, en))
            choice.setChecked(True)
            root.addWidget(choice)
            self.choices[key] = choice
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText(tr("选择保存位置…", "Choose destination…"))
        self.buttons.button(QDialogButtonBox.Cancel).setText(tr("取消", "Cancel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        for choice in self.choices.values():
            choice.toggled.connect(lambda: self.buttons.button(QDialogButtonBox.Save).setEnabled(bool(self.selected_sections())))

    def selected_sections(self):
        return [key for key, choice in self.choices.items() if choice.isChecked()]
