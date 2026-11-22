"""Theme, popup geometry/selection and dismissible notification regressions."""
import os,sys,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def child(theme,native=False):
    os.environ.update(ECHO_OFFLINE='1',ECHO_THEME=theme,QT_QPA_PLATFORM='windows' if native else 'offscreen')
    from echo.backend import paths
    with tempfile.TemporaryDirectory(prefix='echo-compact-controls-') as folder:
        paths.config_dir=lambda:folder;paths.app_dir=lambda:folder
        from PyQt5.QtCore import Qt,QSettings,QPoint
        from PyQt5.QtGui import QColor
        from PyQt5.QtWidgets import QApplication,QDialog,QVBoxLayout,QDoubleSpinBox,QTableWidget,QTableWidgetItem,QAbstractButton
        from PyQt5.QtTest import QTest
        QSettings.setDefaultFormat(QSettings.IniFormat);QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,folder)
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        app=QApplication([])
        from echo.theme import apply_theme,Colors,dialog_qss
        from echo.widgets.echo_combo import EchoCombo
        from echo.widgets.echo_line_edit import EchoLineEdit
        apply_theme(app)
        dialog=QDialog();dialog.setAttribute(Qt.WA_DontShowOnScreen,native);dialog.setStyleSheet(dialog_qss());dialog.resize(440,320)
        layout=QVBoxLayout(dialog);combo=EchoCombo();combo.setFixedWidth(125);combo.addItems(['标准命题','极速','精细']);layout.addWidget(combo)
        combo.view().window().setAttribute(Qt.WA_DontShowOnScreen,native)
        score=QDoubleSpinBox();score.setRange(0,1000);score.setValue(97);layout.addWidget(score)
        table=QTableWidget(2,2);table.setHorizontalHeaderLabels(['大题','题量']);table.setItem(0,0,QTableWidgetItem('选择题'));layout.addWidget(table)
        dialog.show();app.processEvents()
        # Sample base/viewport/header rather than text or antialiased borders.
        assert score.grab().toImage().pixelColor(7,score.height()//2).rgb()==QColor(Colors.SURFACE).rgb()
        # Verify that themed step controls remain visible and clickable.
        spin_image=score.grab().toImage()
        ink=QColor('#ECEDEF' if QColor(Colors.SURFACE_HOVER).lightness()<128 else '#30343B')
        assert any(spin_image.pixelColor(x,y).rgb()==ink.rgb() for x in range(spin_image.width()-15,spin_image.width()-4) for y in range(3,spin_image.height()-3)), 'missing step arrows'
        QTest.mouseClick(score,Qt.LeftButton,pos=QPoint(score.width()-9,score.height()//4));assert score.value()==98
        QTest.mouseClick(score,Qt.LeftButton,pos=QPoint(score.width()-9,score.height()*3//4));assert score.value()==97
        image=table.viewport().grab().toImage();assert image.pixelColor(image.width()-8,image.height()-8).rgb()==QColor(Colors.SURFACE).rgb()
        header=table.horizontalHeader().viewport().grab().toImage();assert header.pixelColor(header.width()-8,header.height()//2).rgb()==QColor(Colors.WINDOW_BG).rgb()
        corner=next(b for b in table.findChildren(QAbstractButton) if b.inherits('QTableCornerButton'))
        assert corner.grab().toImage().pixelColor(corner.width()//2,corner.height()//2).rgb()==QColor(Colors.WINDOW_BG).rgb()
        combo.showPopup();app.processEvents();view=combo.view();popup=view.window()
        assert popup.width()<220,('unnecessary wide menu',popup.width())
        assert popup.height()<=sum(view.sizeHintForRow(i) for i in range(combo.count()))+16
        last=view.visualRect(view.model().index(2,0));assert view.viewport().height()-last.bottom()<=10,(popup.size(),view.size(),view.viewport().size(),last)
        QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=last.center());app.processEvents();assert combo.currentIndex()==2
        combo.setCurrentIndex(0);combo.showPopup();app.processEvents();QTest.keyClick(combo.view(),Qt.Key_Down);QTest.keyClick(combo.view(),Qt.Key_Return);app.processEvents();assert combo.currentIndex()==1
        combo.setEditable(True);assert isinstance(combo.lineEdit(),EchoLineEdit);combo.setEditText('数学 · 自定范围');assert combo.currentText()=='数学 · 自定范围'
        menu=combo.lineEdit().editing_menu();assert any('全选' in a.text() for a in menu.actions());menu.deleteLater()
        if native:
            combo.setEditable(False);combo.setCurrentIndex(0);combo.showPopup();app.processEvents();popup.grab().save(str(ROOT/'artifacts/compact-dropdown-native.png'));combo.hidePopup();dialog.grab().save(str(ROOT/'artifacts/compact-inputs-native.png'))
        dialog.close()
        from echo.widgets.floating_window import FloatingWindow
        window=FloatingWindow();window.setAttribute(Qt.WA_DontShowOnScreen,native);window._show_home();window.show();app.processEvents()
        base=window.height();window._toast('本节课笔记已导出，包含回响、板书与图解。',5000);app.processEvents()
        assert window.toast_close.isVisible() and window.toast_lbl.isVisible() and window.height()>base
        if native:window.grab().save(str(ROOT/'artifacts/echo-toast-close.png'))
        QTest.mouseClick(window.toast_close,Qt.LeftButton);app.processEvents()
        assert window.toast_strip.isHidden() and not window._toast_timer.isActive() and window.height()==base
        window._toast('稍后自动收起',30);window.hide();QTest.qWait(65);assert window.toast_strip.isHidden()
        window.close()
        print('PASS',theme,'double-spin/table corners, compact popup mouse+keyboard, editable Chinese menu, toast close/expiry')


if __name__=='__main__':
    if '--theme' in sys.argv:child(sys.argv[sys.argv.index('--theme')+1],'--native' in sys.argv)
    else:
        for name in ('dark','light','forest','ocean','sakura','parchment'):
            subprocess.run([sys.executable,__file__,'--theme',name],check=True)
