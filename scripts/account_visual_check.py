"""Render the actual login widgets in isolation; verify viewport colours and scrolling."""
import os,sys,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
THEMES=('dark','light','forest','ocean','sakura','parchment')
def child(theme,native=False):
 os.environ['QT_QPA_PLATFORM']='windows' if native else 'offscreen';os.environ['ECHO_THEME']=theme
 from echo.backend import paths
 from PyQt5.QtWidgets import QApplication
 from PyQt5.QtGui import QColor,QPalette
 from PyQt5.QtCore import Qt
 from echo.theme import apply_theme,Colors
 from echo.widgets.account_login import AccountLogin
 with tempfile.TemporaryDirectory(prefix='echo-login-visual-') as folder:
  paths.config_dir=lambda:folder
  app=QApplication([]);apply_theme(app)
  dialog=AccountLogin(allow_skip=True)
  if native:dialog.setAttribute(Qt.WA_DontShowOnScreen,True)
  dialog.show();app.processEvents()
  expected=QColor(Colors.WINDOW_BG).rgb()
  image=dialog.content.grab().toImage()
  assert image.pixelColor(5,5).rgb()==expected,('content background',theme,image.pixelColor(5,5).name(),Colors.WINDOW_BG)
  assert dialog.scroll.viewport().grab().toImage().pixelColor(5,5).rgb()==expected,('viewport background',theme)
  assert dialog.form.labelForField(dialog.email).palette().color(QPalette.WindowText).rgb()==QColor(Colors.TEXT_PRIMARY).rgb()
  assert dialog.register.palette().color(QPalette.WindowText).rgb()==QColor(Colors.TEXT_PRIMARY).rgb()
  if theme=='dark':
   output=ROOT/('artifacts/login-fixed-native.png' if native else 'artifacts/login-fixed.png');output.parent.mkdir(exist_ok=True)
   assert dialog.grab().save(str(output))
  dialog.register.setChecked(True);dialog.resize(490,420);app.processEvents()
  assert dialog.scroll.verticalScrollBar().maximum()>0,'Registration must scroll on short displays'
  dialog.scroll.ensureWidgetVisible(dialog.skip);app.processEvents()
  pos=dialog.skip.mapTo(dialog.scroll.viewport(),dialog.skip.rect().bottomLeft())
  assert pos.y()<=dialog.scroll.viewport().height(),'Bottom action must remain reachable'
  dialog.close()
 print('PASS '+theme+' login background, text colour and small-screen registration')
if __name__=='__main__':
 if len(sys.argv)>1:child(sys.argv[1],'--native-shot' in sys.argv)
 else:
  for theme in THEMES:
   result=subprocess.run([sys.executable,__file__,theme],cwd=ROOT,env={**os.environ,'PYTHONIOENCODING':'utf-8'},capture_output=True,text=True,encoding='utf-8')
   if result.returncode:print(result.stdout,result.stderr);raise SystemExit(result.returncode)
   print(result.stdout.strip())
