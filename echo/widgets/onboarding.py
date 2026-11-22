"""首次启动的新手引导窗：四步讲清楚 Echo 是什么、怎么上课，可随时跳过。

- 首次启动自动弹一次（QSettings "onboarding_done"，跳过/完成都记，不再弹）；
- 设置页可以「重看新手引导」随时再来一遍。
"""
from PyQt5.QtCore import Qt, QSettings, QTimer
from PyQt5.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget, QApplication)

from echo.theme import Colors, Radius
from echo.i18n import tr
from echo.widgets.window_chrome import install_chrome

STEPS = [
    {
        "title": tr("你好，我是 Echo", "Hi, I'm Echo"),
        "body": tr(
            "Echo 是网课里的学习副驾驶：它在后台听你的网课，实时转写、整理出一条课堂时间轴。",
            "Echo is your study copilot for online courses: it listens in the background, "
            "transcribes live and builds a timeline of the lesson."),
        "points": [
            tr("✓ 跟上了 —— 继续听", "✓ Keeping up — keep going"),
            tr("? 有点懵 —— 回看刚才几分钟", "? A bit lost — look back a few minutes"),
            tr("! 我掉队了 —— 定位断点，30 秒补上", "! Lost — find the gap and patch it in 30s"),
        ],
    },
    {
        "title": tr("怎么开始上课", "Starting a lesson"),
        "body": tr(
            "主页给这节课起个名字，点「开始听课」，然后正常播放你的网课就行——腾讯会议、Zoom、B 站、录播课都可以，戴耳机也能听。",
            "Name the lesson on the home page and press Start, then just play your course — "
            "Tencent Meeting, Zoom, Bilibili, recordings; headphones are fine."),
        "points": [
            tr("声音走系统内部，不打扰别人", "Audio stays inside your PC"),
            tr("随时点「我掉队了」，Echo 补完送你回课堂", "Tap Lost anytime; Echo patches you back in"),
            tr("下课自动生成「回响」：讲了什么、哪里薄弱", "Ending class generates the review: topics and weak spots"),
        ],
    },
    {
        "title": tr("账户与模型", "Account and models"),
        "body": tr(
            "AI 讲解走 Echo 账户服务，登录即用；语音识别在本机完成。第一次上课会问你要不要下载语音模型（约 480MB，只下一次）。",
            "AI explanations use your Echo account — just sign in. Speech recognition runs locally; "
            "the first lesson asks to download the voice model (~480MB, one time)."),
        "points": [
            tr("右上角头像可设置昵称和头像", "Set your name and avatar from the top-right avatar"),
            tr("密钥、课程记录都留在你自己的电脑里", "Keys and lesson records stay on your PC"),
        ],
    },
    {
        "title": tr("下课后", "After class"),
        "body": tr(
            "错题本自动收下你的掉队点，错题练习照着出题；「我的小本」按章节整理知识，学习计划帮你安排每天该做什么。",
            "Missed points go into the review book automatically; practice questions follow your mistakes; "
            "the notebook organizes topics, and the study plan schedules your day."),
        "points": [
            tr("错题复习 → 错题练习 → 掌握", "Review → practice → mastered"),
            tr("随时在「设置 → 重看新手引导」回来", "Revisit this guide in Settings anytime"),
        ],
    },
]


class OnboardingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(tr("Echo · 新手引导", "Echo · Getting started"))
        self.resize(560, 430)
        self.setMinimumSize(480, 380)
        self.setStyleSheet(f'''
            QDialog{{background:{Colors.WINDOW_BG};color:{Colors.TEXT_PRIMARY};}}
            QFrame#OnboardCard{{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:12px;}}
            QLabel#OnboardPoint{{color:{Colors.TEXT_SECONDARY};font-size:13px;background:transparent;}}
            QLabel#OnboardBody{{color:{Colors.TEXT_PRIMARY};font-size:13px;background:transparent;}}
            QLabel#OnboardTitle{{color:{Colors.TEXT_PRIMARY};font-size:20px;font-weight:700;background:transparent;}}
        ''')
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.card = QFrame()
        self.card.setObjectName('OnboardCard')
        page = QVBoxLayout(self.card)
        page.setContentsMargins(28, 24, 28, 18)
        page.setSpacing(14)
        root.addWidget(self.card, 1)

        self.dots = QLabel('')
        self.dots.setAlignment(Qt.AlignCenter)
        self.dots.setStyleSheet(f'color:{Colors.TEXT_SECONDARY};font-size:12px;letter-spacing:2px;')
        root.addWidget(self.dots)

        self.title_lbl = QLabel('')
        self.title_lbl.setObjectName('OnboardTitle')
        self.title_lbl.setWordWrap(True)
        page.addWidget(self.title_lbl)
        self.body_lbl = QLabel('')
        self.body_lbl.setObjectName('OnboardBody')
        self.body_lbl.setWordWrap(True)
        page.addWidget(self.body_lbl)
        self.points_box = QVBoxLayout()
        self.points_box.setSpacing(8)
        page.addLayout(self.points_box)
        page.addStretch()

        buttons = QHBoxLayout()
        self.skip_btn = QPushButton(tr('跳过', 'Skip'))
        self.skip_btn.setObjectName('Quiet')
        self.skip_btn.clicked.connect(self._finish)
        buttons.addWidget(self.skip_btn)
        buttons.addStretch()
        self.back_btn = QPushButton(tr('上一步', 'Back'))
        self.back_btn.setObjectName('Quiet')
        self.back_btn.clicked.connect(self._back)
        buttons.addWidget(self.back_btn)
        self.next_btn = QPushButton(tr('下一步', 'Next'))
        self.next_btn.clicked.connect(self._next)
        buttons.addWidget(self.next_btn)
        root.addLayout(buttons)

        install_chrome(self, root, minimize=False)
        self._step = 0
        self._render()

    def _render(self):
        step = STEPS[self._step]
        last = self._step == len(STEPS) - 1
        self.title_lbl.setText(step['title'])
        self.body_lbl.setText(step['body'])
        while self.points_box.count():
            item = self.points_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for text in step['points']:
            lbl = QLabel(text)
            lbl.setObjectName('OnboardPoint')
            lbl.setWordWrap(True)
            self.points_box.addWidget(lbl)
        self.dots.setText(' · '.join('●' if i == self._step else '○' for i in range(len(STEPS))))
        self.back_btn.setVisible(self._step > 0)
        self.next_btn.setText(tr('开始使用', 'Get started') if last else tr('下一步', 'Next'))
        self.skip_btn.setVisible(not last)

    def _back(self):
        if self._step > 0:
            self._step -= 1
            self._render()

    def _next(self):
        if self._step < len(STEPS) - 1:
            self._step += 1
            self._render()
        else:
            self._finish()

    def _finish(self):
        QSettings('Echo', 'Echo').setValue('onboarding_done', True)
        self.accept()


def open_onboarding(parent=None):
    """无条件打开引导窗（设置里的「重看新手引导」）。"""
    dlg = OnboardingDialog(parent)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


def maybe_show_onboarding(parent=None, delay=600):
    """首次启动自动弹一次；跳过或完成都记进 QSettings，不再弹。"""
    try:
        if QSettings('Echo', 'Echo').value('onboarding_done', False, type=bool):
            return None
        QTimer.singleShot(delay, lambda: _show_once(parent))
    except Exception:
        pass
    return None


def _show_once(parent):
    try:
        dlg = open_onboarding(parent)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
    except Exception:
        pass
