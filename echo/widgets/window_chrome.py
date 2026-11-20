"""Shared Echo window controls; Windows order, theme colours, no system frame."""
from PyQt5.QtCore import Qt,QEvent
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from PyQt5.QtGui import QPainterPath,QRegion
from echo.theme import Colors


class EchoTitleBar(QWidget):
    def __init__(self, dialog, title=None, minimize=False):
        super().__init__(dialog)
        self.dialog, self.offset = dialog, None
        self.setObjectName('EchoTitleBar')
        self.setFixedHeight(42)
        row=QHBoxLayout(self);row.setContentsMargins(4,4,0,4);row.setSpacing(4)
        self.title=QLabel(title or dialog.windowTitle());self.title.setTextFormat(Qt.PlainText)
        self.title.setStyleSheet(f'color:{Colors.TEXT_SECONDARY};font-size:12px;font-weight:600;background:transparent;')
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.title,1)
        self.minimize_button=None
        if minimize:
            self.minimize_button=self.control('–','最小化',dialog.showMinimized)
            row.addWidget(self.minimize_button)
        self.close_button=self.control('×','关闭',dialog.close,close=True)
        row.addWidget(self.close_button)

    def control(self,text,tip,slot,close=False):
        button=QPushButton(text);button.setFixedSize(26,26);button.setToolTip(tip)
        button.setAccessibleName(tip);button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(f'''QPushButton{{min-width:0;min-height:0;padding:0;border:0;
            border-radius:6px;background:transparent;color:{Colors.TEXT_SECONDARY};font-size:16px;}}
            QPushButton:hover{{background:{Colors.DANGER if close else Colors.SURFACE_HOVER};
                color:{'#ffffff' if close else Colors.TEXT_PRIMARY};}}''')
        button.clicked.connect(lambda checked=False:slot())
        return button

    def eventFilter(self,watched,event):
        if watched is self.dialog and event.type() in (QEvent.Resize,QEvent.Show):
            if watched.isFullScreen():watched.clearMask()
            else:
                path=QPainterPath();path.addRoundedRect(0,0,watched.width(),watched.height(),12,12);watched.setMask(QRegion(path.toFillPolygon().toPolygon()))
        return super().eventFilter(watched,event)

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and not self.dialog.isFullScreen():
            self.offset=event.globalPos()-self.dialog.frameGeometry().topLeft();event.accept()

    def mouseMoveEvent(self,event):
        if self.offset is not None and event.buttons()&Qt.LeftButton:
            self.dialog.move(event.globalPos()-self.offset);event.accept()

    def mouseReleaseEvent(self,event):self.offset=None


def install_chrome(dialog,layout,title=None,minimize=False):
    """Install after the window stylesheet; close uses the dialog's closeEvent."""
    # Owned dialogs can collapse into a tiny native caption instead of the taskbar.
    # Secondary Echo windows therefore expose close only; the main window retains
    # its own minimize controls and owns application-level minimization.
    flags=dialog.windowFlags()|Qt.FramelessWindowHint
    if not minimize:flags &= ~Qt.WindowMinimizeButtonHint
    dialog.setWindowFlags(flags)
    name=dialog.objectName() or 'EchoSurfaceWindow';dialog.setObjectName(name)
    dialog.setStyleSheet(dialog.styleSheet()+f'''
        QDialog#{name}{{background:{Colors.WINDOW_BG};color:{Colors.TEXT_PRIMARY};
            border:1px solid {Colors.BORDER_STRONG};border-radius:12px;}}
    ''')
    layout.setContentsMargins(16,0,16,14)
    titlebar=EchoTitleBar(dialog,title,minimize)
    layout.insertWidget(0,titlebar)
    dialog.installEventFilter(titlebar)
    dialog.title_bar=titlebar
    dialog.setSizeGripEnabled(True)
    return titlebar
