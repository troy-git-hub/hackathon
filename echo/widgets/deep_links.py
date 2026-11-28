"""Single desktop receiver for validated classroom links, with explicit consent."""
import getpass, hashlib
from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from echo.backend.deep_links import classroom_intent


class ClassroomLinkReceiver(QObject):
    def __init__(self, app, uri=''):
        super().__init__(app)
        self.pending = [uri] if uri else []
        self.window = None
        name = 'Echo.Classroom.' + hashlib.sha256(getpass.getuser().encode()).hexdigest()[:20]
        client = QLocalSocket(self)
        client.connectToServer(name)
        if client.waitForConnected(200):
            self.forwarded = True
            if uri:
                client.write(uri.encode('utf-8') + b'\n'); client.waitForBytesWritten(500)
            client.disconnectFromServer()
            return
        self.forwarded = False
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        if not self.server.listen(name):
            raise RuntimeError('无法建立 Echo 本机唤起通道。')
        self.server.newConnection.connect(self._accept)

    def _accept(self):
        socket = self.server.nextPendingConnection()
        socket._echo_data = bytearray()
        def read():
            socket._echo_data.extend(bytes(socket.readAll()))
            if len(socket._echo_data) > 4096:
                socket.abort(); return
            if b'\n' in socket._echo_data:
                uri = bytes(socket._echo_data).split(b'\n', 1)[0].decode('utf-8', 'replace')
                try: classroom_intent(uri)
                except ValueError: socket.disconnectFromServer(); return
                self.pending.append(uri); self.drain(); socket.disconnectFromServer()
        socket.readyRead.connect(read)
        socket.disconnected.connect(socket.deleteLater)
        read()

    def attach(self, window):
        self.window = window
        QTimer.singleShot(0, self.drain)

    def drain(self):
        if not self.window: return
        while self.pending:
            try: title = classroom_intent(self.pending.pop(0))
            except ValueError: continue
            self.window.showNormal(); self.window.raise_(); self.window.activateWindow()
            from PyQt5.QtWidgets import QMessageBox
            answer = QMessageBox.question(self.window, '和 Echo 一起听课',
                '开始听《' + title + '》吗？\nEcho 将使用当前听课音源，请确认系统声音已选好，然后在浏览器播放课堂。',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                self.window._begin_lesson(title)
