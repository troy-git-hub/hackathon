"""AI 学习助手独立窗口：大窗、可置顶、任务栏独立图标（和清卷一样）。

左侧会话列表与网页 /assistant 同源（登录后同步）；右侧是对话。
"""
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QCursor, QIcon
from PyQt5.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

from echo.i18n import tr
from echo.theme import Colors
from echo.widgets.agent_panel import AgentPanel, _no_enter_default
from echo.widgets.window_chrome import install_chrome, set_taskbar_appid
from echo.backend import paths

_windows = []


def open_agent_window(engine=None, parent=None):
    """Raise the existing assistant window, or create one. parent 只用于定位屏幕，不当 Qt 父窗口。"""
    alive = []
    for window in _windows:
        try:
            window.windowTitle()
            alive.append(window)
        except RuntimeError:
            continue
    _windows[:] = alive
    for window in _windows:
        window.show(); window.raise_(); window.activateWindow()
        return window
    window = AgentWindow(engine=engine, parent=parent)
    _windows.append(window)
    window.finished.connect(lambda _: _windows.remove(window) if window in _windows else None)
    window.show()
    window.raise_()
    window.activateWindow()
    return window


class AgentWindow(QDialog):
    _remote = pyqtSignal(object)
    open_view_requested = pyqtSignal(str)
    start_lesson_requested = pyqtSignal(str)
    open_ai_class_requested = pyqtSignal(str)
    create_paper_requested = pyqtSignal(str, str)
    open_booklets_requested = pyqtSignal()
    open_plans_requested = pyqtSignal()

    def __init__(self, engine=None, parent=None):
        super().__init__(None, Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.engine = engine
        self._chat_index = []
        self._chat_cache = {}
        self._list_loaded = False
        self._refreshing = False
        self._steps_cache = {}
        self._cache_owner = ''
        self.setWindowTitle(tr('Echo · AI 助手', 'Echo · AI assistant'))
        self.setWindowIcon(QIcon(paths.asset('assets', 'echo.ico')))
        self.resize(920, 860)
        self.setMinimumSize(640, 560)
        screen = (parent.screen() if parent is not None else QApplication.primaryScreen())
        if screen:
            area = screen.availableGeometry()
            self.resize(min(920, max(640, area.width() - 80)),
                        min(860, max(560, area.height() - 60)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        self.panel = AgentPanel()
        self._remote.connect(self._apply_remote)
        self._load_cache()
        body.addWidget(self.panel, 1)
        wrap = QWidget()
        wrap.setLayout(body)
        layout.addWidget(wrap, 1)

        titlebar = install_chrome(self, layout, minimize=True)
        self.pin_button = titlebar.pin_control(tr('置顶窗口', 'Keep on top'), self._toggle_pin)
        titlebar.layout().insertWidget(titlebar.layout().count() - 2, self.pin_button)

        self.panel.open_view_requested.connect(self.open_view_requested.emit)
        self.panel.start_lesson_requested.connect(self.start_lesson_requested.emit)
        self.panel.open_ai_class_requested.connect(self.open_ai_class_requested.emit)
        self.panel.create_paper_requested.connect(self.create_paper_requested.emit)
        self.panel.open_booklets_requested.connect(self.open_booklets_requested.emit)
        self.panel.open_plans_requested.connect(self.open_plans_requested.emit)
        self.panel._done.connect(self._on_turn_done)
        for button in self.findChildren(QPushButton):
            _no_enter_default(button)
        QTimer.singleShot(0, lambda: self._refresh_chats(force=True))

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName('AgentSide')
        side.setFixedWidth(200)
        side.setStyleSheet(
            f"QFrame#AgentSide{{background:{Colors.SURFACE};border:0;"
            f"border-right:1px solid {Colors.BORDER};}}")
        lay = QVBoxLayout(side)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        new_btn = QPushButton(tr('+ 新对话', '+ New chat'))
        _no_enter_default(new_btn)
        new_btn.setCursor(QCursor(Qt.PointingHandCursor))
        new_btn.setStyleSheet(
            f"QPushButton{{padding:7px 10px;border:1px solid {Colors.BORDER};border-radius:8px;"
            f"background:transparent;color:{Colors.TEXT_PRIMARY};font-size:12px;}}"
            f"QPushButton:hover{{background:{Colors.SURFACE_HOVER};}}")
        new_btn.clicked.connect(self._new_chat)
        lay.addWidget(new_btn)
        note = QLabel(tr('登录后与网页同步', 'Syncs with the web when signed in'))
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{Colors.TEXT_DISABLED};font-size:10px;background:transparent;")
        lay.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:0;}")
        self._chat_list = QWidget()
        self._chat_list.setStyleSheet("background:transparent;")
        self._chat_lay = QVBoxLayout(self._chat_list)
        self._chat_lay.setContentsMargins(0, 0, 0, 0)
        self._chat_lay.setSpacing(2)
        self._chat_lay.addStretch(1)
        scroll.setWidget(self._chat_list)
        lay.addWidget(scroll, 1)
        return side

    def _new_chat(self):
        if self.panel._busy:
            return
        self._remember_current()
        self.panel.new_chat_id()
        self.panel.reset_conversation(greet=True)
        self._chat_cache[self.panel.chat_id()] = []
        title = tr('新对话', 'New chat')
        self._chat_index = [{'id': self.panel.chat_id(), 'title': title}] + [
            item for item in self._chat_index if item.get('id') != self.panel.chat_id()]
        self._paint_list()

    def _on_turn_done(self):
        cid = self.panel.chat_id()
        self._steps_cache[cid] = (self._steps_cache.get(cid,[]) + list(self.panel._turn_steps))[-6:]
        self._remember_current()
        self._paint_list()

    def _remember_current(self):
        cid = self.panel.chat_id()
        self._chat_cache[cid] = [dict(m) for m in self.panel.history]
        title = ''
        for msg in self.panel.history:
            if msg.get('role') == 'user':
                title = str(msg.get('content') or '')[:22]
                break
        if title:
            found = False
            for item in self._chat_index:
                if item.get('id') == cid:
                    item['title'] = title
                    found = True
                    break
            if not found:
                self._chat_index.insert(0, {'id': cid, 'title': title})
        self._save_cache()

    def _identity(self):
        from echo.backend import account
        return str((account.current_user() or {}).get('id') or '')

    def _load_cache(self):
        from echo.backend import credential_backup
        owner = self._identity()
        if owner == self._cache_owner: return
        if self._cache_owner:
            self.panel.reset_conversation(greet=True)
            self.panel.new_chat_id()
        self._cache_owner = owner
        self._chat_index = []; self._chat_cache = {}; self._steps_cache = {}
        if not owner: return
        try:
            value = credential_backup.load('Echo.Assistant.History.' + owner,max_bytes=2*1024*1024) or {}
            if isinstance(value,dict):
                self._chat_index = value.get('index',[])[:40]
                self._chat_cache = value.get('chats',{})
                self._steps_cache = value.get('steps',{})
                cached = self._chat_cache.get(self.panel.chat_id())
                if cached and not self.panel.history:
                    self.panel.load_transcript(cached,self._steps_cache.get(self.panel.chat_id()))
        except Exception: pass

    def _save_cache(self):
        if not self._cache_owner or self._identity() != self._cache_owner: return
        try:
            from echo.backend import credential_backup
            import json
            current = self.panel.chat_id()
            ids = [current] + [item['id'] for item in self._chat_index[:30] if item['id'] != current]
            snapshot = {
                'index':self._chat_index[:30],
                'chats':{cid:self._chat_cache[cid][-24:] for cid in ids if cid in self._chat_cache},
                'steps':{cid:self._steps_cache[cid][-6:] for cid in ids if cid in self._steps_cache}}
            while len(json.dumps(snapshot,ensure_ascii=False).encode()) > 1500000 and len(ids)>1:
                expired=ids.pop();snapshot['chats'].pop(expired,None);snapshot['steps'].pop(expired,None)
            credential_backup.save('Echo.Assistant.History.' + self._cache_owner,snapshot)
        except Exception: pass

    def _refresh_chats(self, force=False):
        self._load_cache()
        self._paint_list()
        if self._refreshing: return
        from echo.backend import account
        owner = self._identity(); session = account.token()
        if not owner or not session: return
        self._refreshing = True
        import threading
        def work():
            try:
                data = account.request('/v1/me/assistant/chats', timeout=12, max_bytes=65536,auth_token=session)
                self._remote.emit({'owner':owner,'items':data.get('items',[])})
            except Exception:
                self._remote.emit({'owner':owner,'error':True})
        threading.Thread(target=work,daemon=True).start()

    def _apply_remote(self, data):
        if 'cid' not in data: self._refreshing = False
        if data.get('owner') != self._identity() or data.get('error'): return
        if 'items' in data:
            remote = [item for item in data['items'] if isinstance(item,dict) and item.get('id')]
            ids = {item['id'] for item in remote}
            self._chat_index = remote + [item for item in self._chat_index if item.get('id') not in ids]
            self._save_cache(); self._paint_list()
            if not self.panel._busy: self._open_chat(self.panel.chat_id(), refresh=True)
        else:
            cid = data['cid']
            if self.panel._busy: return
            if cid == self.panel.chat_id() and self.panel.history != data.get('before'): return
            self._chat_cache[cid] = data['messages']; self._steps_cache[cid] = data.get('steps',[])
            if cid == self.panel.chat_id(): self.panel.load_transcript(data['messages'],data.get('steps'))
            self._save_cache()

    def _paint_list(self):
        while self._chat_lay.count() > 1:
            item = self._chat_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        current = self.panel.chat_id()
        for chat in self._chat_index[:40]:
            cid = str(chat.get('id') or '')
            title = str(chat.get('title') or tr('新对话', 'New chat'))[:22]
            btn = QPushButton(title)
            _no_enter_default(btn)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setCheckable(True)
            btn.setChecked(cid == current)
            btn.setStyleSheet(
                f"QPushButton{{padding:8px 10px;border:0;border-radius:8px;text-align:left;"
                f"background:{'transparent' if cid != current else Colors.ACCENT_SOFT};"
                f"color:{Colors.TEXT_PRIMARY if cid == current else Colors.TEXT_SECONDARY};font-size:12px;}}"
                f"QPushButton:hover{{background:{Colors.SURFACE_HOVER};}}")
            btn.clicked.connect(lambda checked=False, i=cid: self._open_chat(i))
            self._chat_lay.insertWidget(self._chat_lay.count() - 1, btn)

    def _open_chat(self, cid, refresh=False):
        if self.panel._busy:
            return
        if not cid or (cid == self.panel.chat_id() and not refresh):
            return
        if not refresh or self.panel.history:
            self._remember_current()
        self.panel._chat_id = cid
        from PyQt5.QtCore import QSettings
        QSettings("Echo", "Echo").setValue("assistant/chat_id", cid)
        cached = self._chat_cache.get(cid)
        if cached is not None:
            self.panel.load_transcript(cached,self._steps_cache.get(cid))
            self._paint_list()
        else:
            self.panel.reset_conversation(greet=True)
        self._paint_list()
        from echo.backend import account
        owner=self._identity(); session=account.token(); before=[dict(m) for m in self.panel.history]
        if not owner or not session: return
        import threading
        def work():
            try:
                data=account.request('/v1/me/assistant/chats/'+cid,timeout=12,max_bytes=262144,auth_token=session)
                self._remote.emit({'owner':owner,'cid':cid,'before':before,'messages':data.get('messages',[]),'steps':data.get('steps',[])})
            except Exception: pass
        threading.Thread(target=work,daemon=True).start()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._refresh_chats(force=True))
        if getattr(self, '_taskbar_set', False):
            return
        self._taskbar_set = True
        set_taskbar_appid(self, 'Echo.Agent')

    def _toggle_pin(self):
        pinned = not bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, pinned)
        self.pin_button.setChecked(pinned)
        self.pin_button.setToolTip(tr('取消置顶', 'Unpin') if pinned else tr('置顶窗口', 'Keep on top'))
        self.show()
