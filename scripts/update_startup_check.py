"""No real downloads: check startup policy and a settings-owned update dialog."""
import os,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PyQt5.QtCore import Qt,QSettings
from PyQt5.QtWidgets import QApplication,QDialog
from echo.widgets.update_center import UpdateController
from echo.backend import paths,updater

def main():
    app=QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        QSettings.setDefaultFormat(QSettings.IniFormat);QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,folder)
        settings=QSettings('Echo','Echo');settings.setValue('auto_update_check',True);settings.setValue('last_update_check',time.time())
        parent=QDialog();parent.setWindowModality(Qt.NonModal);parent.show()
        info={'available':True,'release':{'version':'99.0.0','size':2,'notes':[]},'envelope':{}}
        with patch.object(paths,'is_frozen',return_value=True),patch.object(paths,'config_dir',return_value=folder),patch.object(updater,'check_update',return_value=info) as checks,patch.object(updater,'download_update',return_value=Path(folder)/'fixture.exe') as downloads:
            controller=UpdateController();controller.show(parent=parent)
            assert controller.dialog.parentWidget() is None
            assert parent.windowModality()==Qt.NonModal
            assert app.activeModalWidget() is None
            assert controller.dialog.windowFlags()&Qt.WindowStaysOnTopHint
            assert controller.dialog.windowModality()==Qt.NonModal
            controller.auto_check();deadline=time.monotonic()+3
            while controller.state!='ready' and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
            assert controller.state=='ready' and checks.call_count==1 and downloads.call_count==1
            assert downloads.call_args.kwargs['max_bytes_per_second']==1024*1024
            controller.auto_check();assert checks.call_count==1
            with patch.object(controller,'install',Mock()) as install:
                controller._apply_on_exit();controller._apply_on_exit();install.assert_called_once_with(quitting=True)
            controller.dialog.close();parent.close()
    print('PASS every-launch check despite recent timestamp, automatic limited download, settings modal ownership, always-on-top and one exit apply')

if __name__=='__main__':main()
