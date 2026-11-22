"""Visible, session-local replies and optional sandboxed diagrams."""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QScrollArea,QWidget,QVBoxLayout,QLabel,QPushButton,QFrame
from echo.theme import Colors


class BoardChat(QScrollArea):
    def __init__(self, jump, parent=None):
        super().__init__(parent)
        self.jump = jump
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName('BoardChatBody')
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(4,4,8,10)
        self.body.setSpacing(10)
        self.body.addStretch()
        self.setWidget(body)
        self.setStyleSheet(f'QWidget#BoardChatBody{{background:{Colors.WINDOW_BG};}}')
        self.history = []
        self.visuals = []
        self.add('assistant','哪里还没看懂？可以问我，也可以让我在这里画一个图。修改板书时，我会告诉你改了哪一节。',record=False)

    def add(self, role, text, changes=None, visual=None, record=True):
        card = QFrame()
        card.setObjectName('ChatBubble')
        color = Colors.ACCENT_SOFT if role=='user' else Colors.SURFACE
        card.setStyleSheet(f'QFrame#ChatBubble{{background:{color};border:1px solid {Colors.BORDER};border-radius:12px;}}')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14,12,14,12)
        who = QLabel('你' if role=='user' else 'Echo')
        who.setStyleSheet(f'color:{Colors.ACCENT};font-weight:600;font-size:11px;background:transparent;')
        layout.addWidget(who)
        content = QLabel(text)
        content.setTextFormat(Qt.PlainText)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.setStyleSheet(f'color:{Colors.TEXT_PRIMARY};font-size:14px;background:transparent;')
        layout.addWidget(content)
        for change in changes or []:
            link = QPushButton('↗ '+change['label'])
            link.clicked.connect(lambda checked=False,index=change.get('index'):self.jump(index))
            layout.addWidget(link)
        if visual:
            host = QWidget()
            host_layout = QVBoxLayout(host)
            host_layout.setContentsMargins(0,4,0,0)
            layout.addWidget(host)
            entry = {'layout':host_layout,'visual':visual,'view':None}
            self.visuals.append(entry)
            expand = QPushButton('查看这个图解')
            expand.clicked.connect(lambda checked=False,item=entry:self.open_visual(item))
            host_layout.addWidget(expand)
        self.body.insertWidget(self.body.count()-1,card)
        if record:
            self.history.append({'role':role,'text':text[:1600]})
            self.history = self.history[-8:]
        self.load_visuals()
        QTimer.singleShot(0,lambda:self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))

    def load_visuals(self):
        if not self.isVisible():return
        if self.visuals:self.open_visual(self.visuals[-1])

    def open_visual(self,item):
        from echo.widgets.web_lesson import HtmlLesson
        for other in self.visuals:
            if other is not item and other['view']:
                other['view'].stop()
                other['view'].deleteLater()
                other['view'] = None
        if item['view'] is None:
            view = item['view'] = HtmlLesson(self)
            view.setFixedHeight(260)
            view.content_height.connect(lambda height,w=view:w.setFixedHeight(height))
            item['layout'].addWidget(view)
            view.display(item['visual'])

    def showEvent(self,event):
        super().showEvent(event)
        self.load_visuals()

    def stop(self):
        for item in self.visuals:
            if item['view']:
                item['view'].stop()
                item['view'].deleteLater()
                item['view'] = None
