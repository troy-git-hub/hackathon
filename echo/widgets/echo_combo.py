"""A rounded, themed Qt popup instead of the platform's compact native menu."""
from PyQt5.QtCore import Qt,QPoint,QRectF
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
        view.setSpacing(0)
        # Uniform-item caching can keep the pre-QSS row height (13px), leaving
        # an apparently empty popup beneath the correctly sized container.
        view.setUniformItemSizes(False)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setView(view)
        self.setMaxVisibleItems(8)
        self.setStyleSheet(f'''
            QComboBox {{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};border-radius:9px;padding:7px 23px 7px 10px;}}
            QComboBox::drop-down {{border:0;width:20px;}}
            QComboBox QLineEdit {{background:transparent;color:{Colors.TEXT_PRIMARY};border:0;padding:0;}}
            QComboBox QAbstractItemView {{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER_STRONG};border-radius:8px;padding:4px;outline:0;}}
            QComboBox QAbstractItemView::item {{min-height:24px;padding:4px 10px;border-radius:5px;}}
            QComboBox QAbstractItemView::item:selected {{background:{Colors.ACCENT_SOFT};color:{Colors.ACCENT};}}
            QComboBox QAbstractItemView QScrollBar:vertical {{background:transparent;width:6px;margin:2px;}}
            QComboBox QAbstractItemView QScrollBar::handle:vertical {{background:{Colors.BORDER_STRONG};border-radius:3px;min-height:24px;}}
            QComboBox QAbstractItemView QScrollBar::add-line:vertical,QComboBox QAbstractItemView QScrollBar::sub-line:vertical,
            QComboBox QAbstractItemView QScrollBar::add-page:vertical,QComboBox QAbstractItemView QScrollBar::sub-page:vertical {{background:transparent;height:0;border:none;}}
        ''')

    def setEditable(self,editable):
        super().setEditable(editable)
        if editable:
            from echo.widgets.echo_line_edit import EchoLineEdit
            if not isinstance(self.lineEdit(),EchoLineEdit):
                value=self.currentText();edit=EchoLineEdit(self);self.setLineEdit(edit);edit.setText(value)

    def showPopup(self):
        if not self.count():return
        screen=self.screen()
        area=screen.availableGeometry() if screen else None
        natural=max(self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(min(self.count(),200)))+42
        width=max(self.width(),min(natural,420))
        if area:width=min(width,max(100,area.width()-16))
        self.view().setMinimumWidth(width)
        super().showPopup()
        view=self.view();popup=view.window()
        if not popup.isVisible():return
        # 弹层容器（QComboBoxPrivateContainer）不吃全局主题，深色主题下圆角外
        # 会露出系统默认的白底/白滚动条槽——把它也按主题压成 SURFACE。
        try:
            popup.setStyleSheet(f'QComboBoxPrivateContainer{{background:{Colors.SURFACE};border:1px solid {Colors.BORDER_STRONG};border-radius:8px;}}')
        except Exception:
            pass
        view.ensurePolished();view.doItemsLayout()
        rows=min(self.count(),self.maxVisibleItems());margins=view.contentsMargins()
        height=sum(max(1,view.sizeHintForRow(i)) for i in range(rows))+margins.top()+margins.bottom()
        if area:height=min(height,max(48,area.height()-16))
        popup.resize(width,height)
        view.doItemsLayout()
        below=self.mapToGlobal(QPoint(0,self.height()+3));x,y=below.x(),below.y()
        if area:
            x=max(area.left()+4,min(x,area.right()-width-3))
            if y+height>area.bottom()-3:y=max(area.top()+4,self.mapToGlobal(QPoint(0,0)).y()-height-3)
        popup.move(x,y)
        path = QPainterPath()
        path.addRoundedRect(QRectF(popup.rect()), 8, 8)
        popup.setMask(QRegion(path.toFillPolygon().toPolygon()))
