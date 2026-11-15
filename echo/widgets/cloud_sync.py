"""Non-blocking sync scheduling; keeps Echo's existing desktop skin."""
import threading
import time
from PyQt5.QtCore import QObject,QTimer,pyqtSignal
from echo.backend import cloud_sync,account

class CloudSyncController(QObject):
    changed=pyqtSignal(object)
    def __init__(self,parent):
        super().__init__(parent);self.window=parent;self.busy=False;self.last_attempt=0;self.signature=None
        self.timer=QTimer(self);self.timer.setInterval(15000);self.timer.timeout.connect(self.tick)
        self.changed.connect(self.finished)
    def start(self):
        self.timer.start();QTimer.singleShot(3000,self.tick)
    def stop(self):self.timer.stop()
    def tick(self):
        if self.busy:return
        signature=cloud_sync.file_signature();elapsed=time.monotonic()-self.last_attempt
        if elapsed<20 or (signature==self.signature and elapsed<120):return
        self.sync_now()
    def sync_now(self):
        if self.busy:return
        self.busy=True;self.last_attempt=time.monotonic()
        def run():
            result=cloud_sync.sync_once()
            try:self.changed.emit(result)
            except RuntimeError:pass
        threading.Thread(target=run,daemon=True,name='echo-cloud-sync').start()
    def finished(self,result):
        self.busy=False;self.signature=cloud_sync.file_signature()
        card=getattr(self.window,'home_account_card',None)
        if card:
            user=account.current_user()
            card.sub_lbl.setText((user['name']+' · ' if user else '')+result['message'])
            card.setToolTip(result['message'])
