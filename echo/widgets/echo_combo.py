"""A rounded, themed Qt popup instead of the platform's compact native menu."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainterPath, QRegion
from PyQt5.QtWidgets import QComboBox, QListView, QProxyStyle, QStyle
from echo.theme import Colors


class _PopupStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)


class EchoCombo(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._echo_style = _PopupStyle('Fusion')
        self._echo_style.setParent(self)
        self.setStyle(self._echo_style)
        view = QListView()
        view.setStyle(self._echo_style)
        view.setTextElideMode(Qt.ElideRight)
        view.setSpacing(3)
        self.setView(view)
        self.setMaxVisibleItems(8)
        self.setStyleSheet(f'''
            QComboBox {{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};border-radius:9px;padding:7px 23px 7px 10px;}}
            QComboBox::drop-down {{border:0;width:20px;}}
            QComboBox QAbstractItemView {{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER_STRONG};border-radius:10px;padding:7px;outline:0;}}
            QComboBox QAbstractItemView::item {{min-height:30px;padding:4px 10px;border-radius:6px;}}
            QComboBox QAbstractItemView::item:selected {{background:{Colors.ACCENT_SOFT};color:{Colors.ACCENT};}}
        ''')

    def showPopup(self):
        self.view().setMinimumWidth(max(self.width(), 300))
        super().showPopup()
        popup = self.view().window()
        path = QPainterPath()
        from PyQt5.QtCore import QRectF
        path.addRoundedRect(QRectF(popup.rect()), 10, 10)
        popup.setMask(QRegion(path.toFillPolygon().toPolygon()))
