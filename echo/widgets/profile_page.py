"""
Echo - 资料页

点右上角头像进来的那一页：看自己的头像和名字，以及学习统计。
头像点一下（或按「换一张」）就能换，不换就是默认的喵喵。

这一页只负责显示和「换头像」这件事；怎么进、怎么退，由主窗口接线
（back_requested / avatar_changed 两个信号）。
"""
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QPushButton, QVBoxLayout, QWidget)

from echo.backend import persona, profile, store
from echo.components.avatar import AvatarView, load_normalized
from echo.i18n import tr
from echo.theme import Colors, Radius, Spacing
from echo.widgets import dialogs

TITLE = f"color: {Colors.TEXT_PRIMARY}; font-size: 17px; font-weight: 700;"
CAPTION = f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;"


def _label(text="", style="", wrap=False):
    l = QLabel(text)
    l.setWordWrap(wrap)
    if style:
        l.setStyleSheet(style + "background: transparent;")
    return l


def _btn(text, obj, slot, tip=""):
    b = QPushButton(text)
    b.setObjectName(obj)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(lambda *_: slot())      # clicked 带一个 checked，槽一律无参
    if tip:
        b.setToolTip(tip)
    return b


class ProfilePage(QWidget):
    """资料页。主窗口切到这一页时调 refresh() 重新读一遍。"""

    back_requested = pyqtSignal()
    avatar_changed = pyqtSignal(str)          # 换过头像（参数是新路径，空=默认喵喵）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self.refresh()

    # ================= 构建 =================
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.MD)

        # 头像 + 名字
        head = QHBoxLayout()
        head.setSpacing(Spacing.LG)
        self.avatar = AvatarView(84)
        self.avatar.setToolTip(tr("点一下换头像", "Click to change your photo"))
        self.avatar.clicked.connect(self._pick_avatar)
        head.addWidget(self.avatar, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(3)
        self.name_lbl = _label("", TITLE, wrap=True)
        col.addWidget(self.name_lbl)
        self.sub_lbl = _label("", CAPTION, wrap=True)
        col.addWidget(self.sub_lbl)
        col.addSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)
        self.btn_pick = _btn(tr("换一张", "Change photo"), "Quiet", self._pick_avatar)
        row.addWidget(self.btn_pick)
        # 没设过自定义头像时，这个按钮没意义，自己藏起来
        self.btn_default = _btn(tr("用默认喵喵", "Use the default cat"), "Quiet",
                                self._use_default)
        row.addWidget(self.btn_default)
        row.addStretch()
        col.addLayout(row)
        col.addStretch()
        head.addLayout(col, 1)
        root.addLayout(head)

        # 学习统计
        root.addWidget(_label(tr("学习情况", CAPTION)))
        self.stats_card = QFrame()
        self.stats_card.setObjectName("ProfileStats")
        self.stats_card.setStyleSheet(
            f"QFrame#ProfileStats {{ background: {Colors.SURFACE};"
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        grid = QGridLayout(self.stats_card)
        grid.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        grid.setHorizontalSpacing(Spacing.XL)
        grid.setVerticalSpacing(Spacing.MD)
        self._cells = {}
        specs = [("lessons", tr("听过的课", "Lessons")),
                 ("pending", tr("待复习", "To review")),
                 ("mastered", tr("已补上", "Fixed")),
                 ("due", tr("今天该回响", "Due today"))]
        for i, (key, label) in enumerate(specs):
            cell = QVBoxLayout()
            cell.setSpacing(1)
            num = _label("–", f"color: {Colors.TEXT_PRIMARY}; font-size: 22px; font-weight: 700;")
            cell.addWidget(num)
            cell.addWidget(_label(label, CAPTION))
            grid.addLayout(cell, i // 2, i % 2)
            self._cells[key] = num
        root.addWidget(self.stats_card)

        self.hint_lbl = _label("", CAPTION, wrap=True)
        root.addWidget(self.hint_lbl)

        # 学习画像：根据复习表现算出来的，不是 AI 猜的——喂给 AI 调整说话口气用
        persona_head = QHBoxLayout()
        persona_head.addWidget(_label(tr("学习画像", "Learning profile"), CAPTION))
        persona_head.addStretch()
        self.btn_persona_reset = _btn(tr("重置", "Reset"), "Quiet", self._reset_persona,
                                      tr("清空画像，下次会按最新的复习记录重新算",
                                         "Clear it — next time it's recomputed from your latest record"))
        persona_head.addWidget(self.btn_persona_reset)
        root.addLayout(persona_head)
        self.persona_card = QFrame()
        self.persona_card.setObjectName("ProfilePersona")
        self.persona_card.setStyleSheet(
            f"QFrame#ProfilePersona {{ background: {Colors.SURFACE};"
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        pl = QVBoxLayout(self.persona_card)
        pl.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        self.persona_lbl = _label("", CAPTION, wrap=True)
        pl.addWidget(self.persona_lbl)
        root.addWidget(self.persona_card)

        row2 = QHBoxLayout()
        row2.addStretch()
        row2.addWidget(_btn(tr("回到主页", "Back to home"), "Link", self.back_requested.emit))
        root.addLayout(row2)

    # ================= 数据 =================
    def refresh(self):
        """重新读资料和统计。切到本页时调，换完头像也调。"""
        data = {}
        try:
            data = profile.load()
        except Exception:
            pass
        who = ""
        for k in ("username", "nickname", "name"):
            v = str(data.get(k) or "").strip()
            if v:
                who = v
                break
        self.name_lbl.setText(who or tr("同学", "there"))
        # 副标题只说标题里没有的：名字已经在上面了，再写一遍是重复
        bits = []
        age = data.get("age")
        if age:
            bits.append(tr(f"{age} 岁", f"age {age}"))
        hob = str(data.get("hobbies") or "").strip()
        if hob:
            bits.append(hob)
        self.sub_lbl.setText(" · ".join(bits))
        self.sub_lbl.setVisible(bool(bits))

        try:
            st = store.stats()
        except Exception:
            st = {}
        for key, lbl in self._cells.items():
            v = st.get(key)
            lbl.setText("–" if v is None else str(v))

        due = st.get("due") or 0
        pending = st.get("pending") or 0
        if due:
            self.hint_lbl.setText(tr(f"今天有 {due} 个知识点该回响了，去「讲给 Echo 听」过一遍吧。",
                                     f"{due} concept{'s' if due > 1 else ''} due today — "
                                     f"run through them in Talk it through."))
        elif pending:
            self.hint_lbl.setText(tr(f"今天到期的都过了，还有 {pending} 个在清单里排着队。",
                                     f"Nothing due today — {pending} more waiting in your list."))
        else:
            self.hint_lbl.setText(tr("还没有要复习的知识点，安心听课就好。",
                                     "Nothing to review yet — just enjoy the lesson."))

        # 有自定义头像才给「用默认喵喵」
        try:
            has_custom = bool(profile.avatar_path())
        except Exception:
            has_custom = False
        self.btn_default.setVisible(has_custom)
        self.avatar.refresh()

        try:
            self.persona_lbl.setText(persona.describe())
        except Exception:
            self.persona_lbl.setText(tr("画像暂时算不出来。", "Couldn't compute this right now."))

    def _reset_persona(self):
        try:
            persona.reset()
        except Exception:
            pass
        self.refresh()

    # ================= 换头像 =================
    def _pick_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("换一张头像", "Change your photo"), "",
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
        self._store(pm)

    def _use_default(self):
        try:
            profile.clear_avatar()
        except OSError:
            pass
        self.refresh()
        self.avatar_changed.emit("")

    def _store(self, pm):
        """把处理器好的图写进配置目录。

        走临时文件是因为 backend 的 profile 只负责拷文件（它不能引 PyQt5）。
        存进去的是**规范化后的图**（EXIF 旋转已应用、长边缩到 512），不是原图路径 ——
        用户把原图删了、挪了都不影响头像。
        """
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), f"echo-avatar-{os.getpid()}.png")
        try:
            if not pm.save(tmp, "PNG"):
                dialogs.warn(self, tr("头像没能保存", "Couldn't save your photo"),
                             tr("换一张试试。", "Try another one."))
                return
            profile.set_avatar(tmp)
        except OSError as e:
            dialogs.warn(self, tr("头像没能保存", "Couldn't save your photo"), str(e))
            return
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        self.refresh()
        self.avatar_changed.emit(profile.avatar_path())
