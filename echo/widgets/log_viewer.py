from pathlib import Path
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit, QFileDialog
from echo.backend import diagnostics
from echo.theme import dialog_qss, Colors


class LogViewer(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Echo · 日志与诊断')
        self.resize(720, 500)
        self.setStyleSheet(dialog_qss())
        root = QVBoxLayout(self)
        label = QLabel('下载失败和运行异常会记录在本机。导出前可预览；密钥和下载链接中的凭据会遮盖。')
        label.setWordWrap(True)
        root.addWidget(label)
        self.content = QPlainTextEdit()
        self.content.setStyleSheet(f'background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};padding:10px;font-family:Consolas,"Microsoft YaHei UI";')
        self.content.setReadOnly(True)
        self.content.setPlainText(diagnostics.report())
        root.addWidget(self.content)
        row = QHBoxLayout()
        for text, callback in [('刷新', lambda: self.content.setPlainText(diagnostics.report())),
                               ('打开日志目录', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(diagnostics.log_dir())))),
                               ('导出日志…', self.export)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        root.addLayout(row)

    def export(self):
        file, _ = QFileDialog.getSaveFileName(self, '导出诊断日志', 'Echo-diagnostics.log', 'Log (*.log)')
        if file:
            try:
                Path(file).write_text(diagnostics.report(), encoding='utf-8')
            except OSError as exc:
                from echo.widgets import dialogs
                dialogs.warn(self, '导出失败', str(exc))
