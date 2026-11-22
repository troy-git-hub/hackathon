"""Isolated native entry routing and truthful Qingjuan generation stages."""
import copy,os,sys,tempfile,threading,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(ECHO_OFFLINE='1',ECHO_THEME=os.getenv('ECHO_THEME','dark'),QT_QPA_PLATFORM='windows',QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu --no-sandbox')
from PyQt5.QtCore import Qt,QSettings
from PyQt5.QtWidgets import QApplication,QMessageBox
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
from echo.backend import paths,account

def main():
 with tempfile.TemporaryDirectory(prefix='echo-home-paper-followup-') as folder:
  paths.config_dir=lambda:folder;paths.app_dir=lambda:folder
  QSettings.setDefaultFormat(QSettings.IniFormat);QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,folder)
  app=QApplication([]);app.setQuitOnLastWindowClosed(False)
  from echo.theme import apply_theme
  apply_theme(app)
  user={'id':'followup-user','name':'调试同学'}
  account.current_user=lambda:dict(user);account.token=lambda:'fixture-session'
  def wait(test,seconds=6):
   end=time.monotonic()+seconds
   while not test() and time.monotonic()<end:app.processEvents();time.sleep(.015)
   app.processEvents();assert test()
  with patch.object(account,'request',side_effect=AssertionError('unexpected API')):
   from echo.widgets.floating_window import FloatingWindow
   window=FloatingWindow();window._show_home();window.show();app.processEvents();window._fit();wait(lambda:window.btn_today.isVisible())
   assert window.home_start_panel.width()<window.home_booklet_card.width()
   assert window.home_cloud_paper_card.isVisible()
   with patch.object(window,'_begin_lesson') as begin,patch('echo.widgets.studio_launch.open_studio') as studio:
    window.title_edit.setText('网课测试');window.btn_today.click();begin.assert_called_once_with('网课测试')
    window.home_ai_mode.setChecked(True);window.title_edit.setText('函数的斜率');window.btn_today.click();studio.assert_called_once_with(window,'函数的斜率');assert begin.call_count==1
   with patch('echo.widgets.qingjuan_workbench.open_qingjuan_workbench') as compose:
    window.home_cloud_paper_card.btn.click();compose.assert_called_once_with(parent=window)
   from echo.widgets import learning_path as lp
   snapshot={'goal':None,'today':[],'recent':[],'sources':[],'recommendations':[],'progress':{},'day':'2026-11-22'}
   with patch('echo.widgets.account_login.ensure_account',return_value=True):
    first=lp.open_learning_path(window,snapshot);first.target.setText('保留未保存目标')
    second=lp.open_learning_planner(window);assert first is second and second.tabs.currentIndex()==2
    again=lp.open_learning_path(window);assert again is first and again.tabs.currentIndex()==0
    assert again.target.text()=='保留未保存目标';assert '学习目标' in again.windowTitle()
    first.closed=True;first.owner_timer.stop();first.hide()
   window.home_online_mode.setChecked(True);app.processEvents();assert '听课' in window.btn_today.text();window.grab().save(str(ROOT/'artifacts/echo-home-class-choices.png'))
   from echo.widgets.qingjuan_workbench import QingjuanWorkbench
   from echo.backend import qingjuan_local as local
   from qingjuan_workbench_check import fixture
   work=QingjuanWorkbench();work.doc['paper']=local.normalize(fixture());work.populate();work.show();app.processEvents()
   release=threading.Event()
   def fake(document,operation,payload,fresh=False,on_progress=None):
    on_progress({'step':1,'text':'检查服务'});on_progress({'step':2,'text':'等待模型返回（模拟）'})
    release.wait(6);on_progress({'step':3,'text':'收到结果'})
    return {'approved':True,'summary':'本机专项：校验通过','issues':[]}
   with patch.object(local,'ai',side_effect=fake),patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
    work.launch('review',{'paper':work.doc['paper']});wait(lambda:work.generation_bar.value()==2)
    assert work.busy and work.generation_panel.isVisible() and work.generation_clock.isActive()
    assert work.generation_bar.maximum()==5 and '秒' in work.generation_label.text()
    work.grab().save(str(ROOT/'artifacts/qingjuan-native-generating.png'));release.set();wait(lambda:not work.busy)
    assert work.generation_bar.value()==5 and not work.generation_clock.isActive()
    assert '已完成并保存' in work.generation_label.text()
   before=copy.deepcopy(work.doc['paper'])
   def fail(*args,**kwargs):
    kwargs['on_progress']({'step':2,'text':'等待模型'});raise ValueError('模拟连接中断')
   with patch.object(local,'ai',side_effect=fail),patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
    work.launch('review',{});wait(lambda:not work.busy)
    assert work.generation_bar.value()<5 and '未完成' in work.generation_label.text()
    assert work.doc['paper']==before
   work.close();window.hide();app.processEvents()
 print('PASS home online-vs-Studio routing/compact layout/visible Qingjuan, reused goal-vs-plan tabs/draft preservation, truthful generation stages/success/failure; no live model')

if __name__=='__main__':main()
