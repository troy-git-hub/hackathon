"""Shared Echo window controls; Windows order, theme colours, no system frame."""
from PyQt5.QtCore import Qt,QEvent
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from PyQt5.QtGui import QColor,QIcon,QPainter,QPainterPath,QPen,QPixmap,QRegion,QBrush
from echo.theme import Colors,Radius

# 按钮样式与主页右上角的 IconBtn 完全一致：26×26、透明底、悬停浅色蒙层。
# 以前这里关窗悬停会变红、字号也不同，和主页（以及互相之间）不一致，已统一。
_CONTROL_QSS=f'''QPushButton{{min-width:0;min-height:0;padding:0;border:0;
    border-radius:{Radius.SM}px;background:transparent;color:{Colors.TEXT_SECONDARY};font-size:15px;}}
    QPushButton:hover{{background:{Colors.HOVER_OVERLAY};color:{Colors.TEXT_PRIMARY};}}'''

# 微信「置顶」那种钉子图标的位图缓存，按 (颜色, 是否按下) 取。
_pin_cache={}

def icon_button(text,tip,slot,size=26):
    """和 EchoTitleBar / 主页右上角完全一致的窗口按钮。别的窗口的折叠、
    关闭都要从这里拿样式，别再各写一套 QSS。"""
    button=QPushButton(text);button.setFixedSize(size,size);button.setToolTip(tip)
    button.setAccessibleName(tip);button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(_CONTROL_QSS)
    button.clicked.connect(lambda checked=False:slot())
    return button

def _pin_pixmap(color,filled=False):
    key=(str(color),bool(filled))
    if key in _pin_cache:return _pin_cache[key]
    pm=QPixmap(48,48);pm.fill(Qt.transparent)
    p=QPainter(pm);p.setRenderHint(QPainter.Antialiasing)
    p.translate(24,24);p.rotate(-35)
    p.setPen(QPen(color,3.4,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
    if filled:p.setBrush(QBrush(color))
    p.drawRoundedRect(-8,-16,16,7,3.2,3.2)          # 钉帽
    path=QPainterPath();path.moveTo(-8,-9);path.lineTo(8,-9);path.lineTo(0,2);path.closeSubpath()
    p.drawPath(path)                                 # 钉身
    p.drawLine(0,2,0,14)                             # 针
    p.end()
    pm.setDevicePixelRatio(3.0)                      # 48px 位图按 16×16 逻辑尺寸用
    _pin_cache[key]=pm
    return pm


class EchoTitleBar(QWidget):
    def __init__(self, dialog, title=None, minimize=False):
        super().__init__(dialog)
        self.dialog, self.offset = dialog, None
        self.setObjectName('EchoTitleBar')
        self.setFixedHeight(42)
        # 右边距必须留出圆角蒙版的宽度：蒙版在右上角切 12px 圆角，按钮贴死右缘
        # 时 × 的悬停底色会被削掉一条，看起来比主页的窄（用户对比过）。
        row=QHBoxLayout(self);row.setContentsMargins(4,4,8,4);row.setSpacing(4)
        self.title=QLabel(title or dialog.windowTitle());self.title.setTextFormat(Qt.PlainText)
        self.title.setStyleSheet(f'color:{Colors.TEXT_SECONDARY};font-size:12px;font-weight:600;background:transparent;')
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.title,1)
        self.minimize_button=None
        if minimize:
            self.minimize_button=self.control('–','最小化',dialog.showMinimized)
            row.addWidget(self.minimize_button)
        self.close_button=self.control('×','关闭',dialog.close)
        row.addWidget(self.close_button)

    def control(self,text,tip,slot):
        button=icon_button(text,tip,slot)
        button.setParent(self)
        return button

    def pin_control(self,tip,slot):
        """微信钉子样式的「置顶」按钮：未按下是描边钉子，按下变主题色实心钉。"""
        button=QPushButton();button.setFixedSize(26,26);button.setToolTip(tip)
        button.setAccessibleName(tip);button.setCursor(Qt.PointingHandCursor)
        button.setCheckable(True)
        button.setStyleSheet(_CONTROL_QSS)
        button.setIcon(QIcon(_pin_pixmap(QColor(Colors.TEXT_SECONDARY),False)))
        def _sync(checked):
            button.setIcon(QIcon(_pin_pixmap(
                QColor(Colors.ACCENT if checked else Colors.TEXT_SECONDARY),bool(checked))))
        button.toggled.connect(_sync)
        button.clicked.connect(lambda checked=False:slot())
        return button

    def eventFilter(self,watched,event):
        if watched is self.dialog and event.type() in (QEvent.Resize,QEvent.Show):
            if watched.isFullScreen():watched.clearMask()
            else:
                path=QPainterPath();path.addRoundedRect(0,0,watched.width(),watched.height(),12,12);watched.setMask(QRegion(path.toFillPolygon().toPolygon()))
            if event.type()==QEvent.Show:
                # 每次显示淡入。必须在这里**同步**把透明度压到 0：Show 事件先于
                # 第一帧绘制，等 singleShot 再压的话窗口会先完整闪一帧再淡入。
                self._fade_show()
        return super().eventFilter(watched,event)

    def _fade_show(self):
        try:
            from echo.widgets import motion
            motion.fade_window(self.dialog)
        except Exception:
            pass

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and not self.dialog.isFullScreen():
            self.offset=event.globalPos()-self.dialog.frameGeometry().topLeft();event.accept()

    def mouseMoveEvent(self,event):
        if self.offset is not None and event.buttons()&Qt.LeftButton:
            self.dialog.move(event.globalPos()-self.offset);event.accept()

    def mouseReleaseEvent(self,event):self.offset=None


def set_taskbar_appid(widget, appid):
    """Give a top-level window its own Windows taskbar identity (not grouped with Echo).

    Must run after the window has a native HWND (showEvent is the right place).
    Qingjuan uses 'Echo.Qingjuan'; the AI assistant uses 'Echo.Agent'.
    """
    import os
    if os.name != 'nt':
        return
    try:
        import ctypes, uuid
        from ctypes import wintypes
        class GUID(ctypes.Structure):
            _fields_ = [('data', ctypes.c_ubyte * 16)]
        def guid(value):
            return GUID((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))
        class Key(ctypes.Structure):
            _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]
        class Value(ctypes.Structure):
            _fields_ = [('vt', ctypes.c_ushort), ('r1', ctypes.c_ushort),
                        ('r2', ctypes.c_ushort), ('r3', ctypes.c_ushort),
                        ('value', ctypes.c_void_p), ('padding', ctypes.c_void_p)]
        shell = ctypes.WinDLL('shell32')
        fn = shell.SHGetPropertyStoreForWindow
        fn.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        fn.restype = ctypes.c_long
        iid = guid('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
        store = ctypes.c_void_p()
        if fn(int(widget.winId()), ctypes.byref(iid), ctypes.byref(store)) < 0:
            return
        table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        key = Key(guid('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'), 5)
        text = ctypes.create_unicode_buffer(appid)
        value = Value(); value.vt = 31; value.value = ctypes.cast(text, ctypes.c_void_p)
        try:
            ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(Key), ctypes.POINTER(Value))(table[6])(
                store, ctypes.byref(key), ctypes.byref(value))
            ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(table[7])(store)
        finally:
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])(store)
    except Exception:
        pass


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
