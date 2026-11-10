"""Course preparation library, separate from the in-class blackboard."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPlainTextEdit,
                             QListWidget, QListWidgetItem, QPushButton, QFileDialog,
                             QLabel, QSplitter, QWidget, QMessageBox)

from echo.backend import knowledge
from echo.theme import Colors, dialog_qss, apply_native_titlebar


class KnowledgeLibrary(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self._selected = None
        self._docs = []
        self.setWindowTitle("Echo · 课前资料库")
        self.resize(900, 650)
        self.setMinimumSize(720, 540)
        self.setStyleSheet(dialog_qss() + f"""
            QListWidget, QPlainTextEdit {{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};
                border:1px solid {Colors.BORDER};border-radius:10px;padding:12px;font-size:14px;}}
            QListWidget::item {{padding:12px 8px;border-bottom:1px solid {Colors.BORDER};}}
            QListWidget::item:selected {{background:{Colors.ACCENT_SOFT};color:{Colors.TEXT_PRIMARY};}}
        """)
        apply_native_titlebar(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)
        title = QLabel("课前，准备好你的参考资料")
        title.setStyleSheet("font-size:23px;font-weight:600;")
        root.addWidget(title)
        subtitle = QLabel("教材摘录、讲义、自己的笔记。上课答疑和黑板会检索相关片段，标明来源。")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)
        side = QWidget()
        left = QVBoxLayout(side)
        left.setContentsMargins(0, 0, 12, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索资料名称或内容")
        self.search.textChanged.connect(self.filter)
        left.addWidget(self.search)
        self.sources = QListWidget()
        self.sources.currentRowChanged.connect(self.preview)
        left.addWidget(self.sources, 1)
        self.count = QLabel()
        left.addWidget(self.count)
        actions = QHBoxLayout()
        for title, slot in (("＋ 新笔记", self.new_note), ("导入文件", self.import_note)):
            b = QPushButton(title)
            b.clicked.connect(slot)
            actions.addWidget(b)
        left.addLayout(actions)
        split.addWidget(side)
        editor = QWidget()
        right = QVBoxLayout(editor)
        right.setContentsMargins(6, 0, 0, 0)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("资料名称，例如：中国近代史 · 第三章")
        right.addWidget(self.title_edit)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setPlaceholderText("粘贴教材摘录或写下你的笔记。\n\n支持 UTF-8 的 TXT、Markdown 文件，单份最多 20 万字。")
        right.addWidget(self.note_edit, 1)
        controls = QHBoxLayout()
        self.status = QLabel("新建笔记")
        controls.addWidget(self.status, 1)
        self.delete_btn = QPushButton("删除资料")
        self.delete_btn.clicked.connect(self.delete_note)
        controls.addWidget(self.delete_btn)
        self.save_btn = QPushButton("保存笔记")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self.save_note)
        controls.addWidget(self.save_btn)
        right.addLayout(controls)
        split.addWidget(editor)
        split.setSizes([280, 550])
        note = QLabel("资料保存在本机。在线答疑或生成黑板时，仅相关片段会发送给你配置的模型服务。")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};font-size:11px;")
        root.addWidget(note)
        self.refresh()
        self.new_note()

    def refresh(self):
        try:
            self._docs = knowledge.documents()
            self.sources.blockSignals(True)
            self.sources.clear()
            for doc in self._docs:
                item = QListWidgetItem(f"{doc['title']}\n{len(doc['text']):,} 字 · 本机资料")
                item.setToolTip(doc["title"])
                self.sources.addItem(item)
            if self._selected:
                index = next((i for i, d in enumerate(self._docs) if d["id"] == self._selected), -1)
                self.sources.setCurrentRow(index)
            self.sources.blockSignals(False)
            self.count.setText(f"{len(self._docs)} 份资料 · 按问题自动匹配")
            self.filter(self.search.text())
        except Exception as exc:
            self.sources.blockSignals(False)
            self.status.setText("读取失败：" + str(exc))

    def filter(self, text):
        text = text.strip().lower()
        for i, doc in enumerate(self._docs):
            self.sources.item(i).setHidden(bool(text and text not in (doc["title"] + doc["text"]).lower()))

    def dirty(self):
        if self._selected:
            original = next((d for d in self._docs if d["id"] == self._selected), {})
            return self.title_edit.text() != original.get("title", "") or self.note_edit.toPlainText() != original.get("text", "")
        return bool(self.title_edit.text().strip() or self.note_edit.toPlainText().strip())

    def may_leave(self):
        if not self.dirty():
            return True
        reply = QMessageBox.question(self, "笔记尚未保存", "保存当前修改后再继续？",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if reply == QMessageBox.Cancel:
            return False
        return self.save_note() if reply == QMessageBox.Save else True

    def preview(self, row):
        if not 0 <= row < len(self._docs):
            return
        doc = self._docs[row]
        if doc["id"] == self._selected:
            return
        if not self.may_leave():
            self.sources.blockSignals(True)
            old = next((i for i, d in enumerate(self._docs) if d["id"] == self._selected), -1)
            self.sources.setCurrentRow(old)
            self.sources.blockSignals(False)
            return
        self._selected = doc["id"]
        self.title_edit.setText(doc["title"])
        self.note_edit.setPlainText(doc["text"])
        self.delete_btn.setEnabled(True)
        self.status.setText("编辑资料 · 保存后用于后续提问")

    def new_note(self):
        if hasattr(self, "title_edit") and not self.may_leave():
            return
        self._selected = None
        self.sources.blockSignals(True)
        self.sources.setCurrentRow(-1)
        self.sources.blockSignals(False)
        self.title_edit.clear()
        self.note_edit.clear()
        self.delete_btn.setEnabled(False)
        self.status.setText("新建笔记")
        self.title_edit.setFocus()

    def save_note(self):
        try:
            if self._selected:
                ident = knowledge.update(self._selected, self.title_edit.text(), self.note_edit.toPlainText())
            else:
                ident = knowledge.add(self.title_edit.text(), self.note_edit.toPlainText())
            self._selected = ident
            self.refresh()
            self.status.setText("已保存 ✓")
            self.delete_btn.setEnabled(True)
            return True
        except Exception as exc:
            self.status.setText("未保存：" + str(exc))
            return False

    def import_note(self):
        filename, _ = QFileDialog.getOpenFileName(self, "导入参考资料", "", "学习资料 (*.txt *.md)")
        if filename:
            try:
                knowledge.import_file(filename)
                self.refresh()
                self.status.setText("资料已导入 ✓")
            except Exception as exc:
                self.status.setText("导入失败：" + str(exc))

    def delete_note(self):
        if not self._selected:
            return
        if QMessageBox.question(self, "删除资料", "删除这份资料？已保存的课堂黑板会保留当时引用的来源快照。") != QMessageBox.Yes:
            return
        try:
            knowledge.remove(self._selected)
            self._selected = None
            self.title_edit.clear()
            self.note_edit.clear()
            self.refresh()
            self.new_note()
        except Exception as exc:
            self.status.setText("删除失败：" + str(exc))

    def closeEvent(self, event):
        event.accept() if self.may_leave() else event.ignore()

    def reject(self):
        if self.may_leave():
            super().reject()
