"""Isolated desktop hierarchy/chrome/account checks across all six Echo skins."""
import os,sys,tempfile,time,subprocess
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def child(theme):
    native='--shots' in sys.argv
    os.environ.update(ECHO_OFFLINE='1',ECHO_THEME=theme,QT_QPA_PLATFORM='windows' if native else 'offscreen')
    from echo.backend import paths
    with tempfile.TemporaryDirectory(prefix='echo-desktop-polish-') as folder:
        paths.config_dir=lambda:folder
        paths.app_dir=lambda:folder
        from PyQt5.QtCore import Qt,QSettings
        from PyQt5.QtWidgets import QApplication,QPushButton,QLabel,QMessageBox
        from PyQt5.QtGui import QColor
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,folder)
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        app=QApplication([])
        from echo.theme import apply_theme,Colors
        apply_theme(app)
        from echo.backend import account,cloud_sync,store,booklets,exam
        user={'id':'u1','name':'测试同学','email':'test@example.com','balance':1200,'role':'admin'}
        account.current_user=lambda:dict(user)
        account.token=lambda:'test-session'
        cloud_sync.status=lambda:{'enabled':False,'message':'自动同步已暂停','bound_account':'u1'}
        calls=[]
        def request(path,**kwargs):
            calls.append(path)
            if path=='/v1/me':return {'user':dict(user)}
            if path=='/v1/me/workspace':return {'stats':{'knowledge':28,'due':4,'weakness':3},'lessons':[{'title':'函数与图像','ended_at':time.time()}]}
            if path=='/v1/me/summary':return {'user_id':user['id'],'server_time':time.time(),'study':{'answered':86,'average_score':87.5,'materials':4,'papers':3,'submitted':6,'in_progress':1,'wrong':12,'pending':2},'usage_7d':{'points':18.4,'completed':12,'input_tokens':6400,'output_tokens':6000},'storage':{'used_bytes':7*1048576},'daily':[{'day':day,'answered':count} for day,count in [('11-10',5),('11-11',12),('11-12',8),('11-13',18),('11-14',10),('11-15',20),('11-16',13)]],'recent_attempts':[{'title':'一次函数 · 清卷专项','status':'submitted','score':92},{'title':'每日小题 · 数学','status':'submitted','score':80},{'title':'函数图像综合检测','status':'active','deadline':time.time()+1000}]}
            if path=='/v1/me/requests':return {'items':[{'purpose_label':'课堂梳理','state':'succeeded','cost':3},{'purpose_label':'练习生成','state':'failed','cost':0}]}
            raise AssertionError('unexpected API '+path)
        account.request=request
        store.save_lesson('函数入门',[{'name':'正比例函数','mastery':.7,'status':'review'}],[],summary='图像经过原点。')
        booklets.save(booklets.generate('函数复习','数学',booklets.catalog(),use_ai=False))
        from echo.widgets.floating_window import FloatingWindow,HOME
        window=FloatingWindow();window.setAttribute(Qt.WA_DontShowOnScreen,native);window._show_home();window.show()
        for _ in range(4):app.processEvents()
        assert window.btn_today.height()<=34
        assert '工具' not in window.home_tools_toggle.text()
        compact=window.height();assert compact<480,(theme,compact)
        with patch.object(store,'due_summary',return_value={'count':128,'topics':['正比例函数','反比例函数'],'minutes':10}):
            window._render_recall_card();window._fit()
            for _ in range(4):app.processEvents()
            assert window.btn_recall.height()<=30
            assert window.height()<590,(theme,window.height())
        assert window.recall_title.fontMetrics().height()<24
        window.home_tools_toggle.click()
        for _ in range(4):app.processEvents()
        assert window.home_tools_panel.isVisible()
        window.home_tools_toggle.click()
        for _ in range(4):app.processEvents()
        from echo.widgets.booklet_window import BookletWindow,BookletComposer
        from echo.widgets.exam_window import ExamWindow
        from echo.widgets.settings import SettingsDialog
        from echo.widgets.account_center import AccountCenter
        from echo.widgets.paper_book import PaperBook
        from echo.widgets.update_center import UpdateCenter,UpdateController
        shelf=BookletWindow(parent=window)
        composer=BookletComposer(booklets.catalog(),shelf)
        test=ExamWindow(parent=window)
        settings=SettingsDialog(window)
        center=AccountCenter(window,autoload=False)
        papers=PaperBook(window,autoload=False)
        updates=UpdateCenter(UpdateController())
        for widget in (shelf,composer,test,settings,center,papers,updates):
            widget.setAttribute(Qt.WA_DontShowOnScreen,native)
            assert widget.windowFlags()&Qt.FramelessWindowHint
            assert widget.title_bar.close_button.toolTip()=='关闭'
            widget.show();app.processEvents()
            assert widget.grab().toImage().pixelColor(10,50).rgb()==QColor(Colors.WINDOW_BG).rgb(),(theme,type(widget).__name__)
            assert widget.title_bar.minimize_button is None
            assert not widget.windowFlags()&Qt.WindowMinimizeButtonHint
        assert not settings.admin_button.isHidden()
        assert not any('管理员' in b.text() for b in center.findChildren(QPushButton))
        assert not center.sync_panel.isVisible()
        center.refresh()
        deadline=time.monotonic()+3
        while center._busy and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
        assert not center._busy and set(calls)=={'/v1/me','/v1/me/workspace','/v1/me/requests','/v1/me/summary'}
        assert center.metrics.text()=='云端 28 个知识点 · 4 项待复习 · 3 项待巩固'
        assert any('函数与图像'==n.text() for n in center.findChildren(QLabel))
        assert any('额度已返还' in n.text() for n in center.findChildren(QLabel))
        center.sync_toggle.click();assert center.sync_panel.isVisible()
        center.sync_toggle.click();assert not center.sync_panel.isVisible()
        user['id']='u2';center.update_sync()
        assert not center.email.text() and not center.balance.text()
        assert center.summary_values['answered'].text()=='—' and not center.trend.items
        assert not center.refresh_button.isEnabled()
        user['id']='u1';user['role']='user'
        regular=SettingsDialog(window);assert regular.admin_button.isHidden();regular.close()
        paper=dict(id='p1',schema='echo.exam/1',owner='u1',title='函数检测',chapters=[],questions=[dict(id='1',type='single_choice',question='函数图像经过哪里？',options=['原点','其他点'],answer='A',explain='正比例函数图像经过原点。',points=100)],answers={},results={},events=[],status='active',started_at=time.time(),duration_seconds=300,anti_cheat=False)
        test.start(paper);test.timer.stop()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.No) as ask:
            test.title_bar.close_button.click();assert test.isVisible() and ask.call_count==1
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes) as ask:
            test.title_bar.close_button.click();assert not test.isVisible() and ask.call_count==1
        if theme=='dark':
            output=ROOT/'artifacts';output.mkdir(exist_ok=True)
            window.grab().save(str(output/'echo-desktop-home-compact.png'))
            shelf.grab().save(str(output/'echo-desktop-notebook.png'))
            # Re-open a fresh account view for the sample, without real APIs.
            preview=AccountCenter(window,autoload=False);preview.setAttribute(Qt.WA_DontShowOnScreen,native);preview.finished_request('summary',{'user':{'user':dict(user)},'workspace':request('/v1/me/workspace'),'requests':request('/v1/me/requests'),'summary':request('/v1/me/summary')},'')
            preview.show();app.processEvents();preview.grab().save(str(output/'echo-desktop-account.png'));preview.close()
        for widget in (center,settings,composer,shelf,papers,updates):widget.close()
        window.close()
        print('PASS',theme,'home',compact,'px; frameless/dialog close/account privacy/settings roles')


if __name__=='__main__':
    if '--theme' in sys.argv:child(sys.argv[sys.argv.index('--theme')+1])
    else:
        for theme in ('dark','light','forest','ocean','sakura','parchment'):
            subprocess.run([sys.executable,__file__,'--theme',theme],check=True)
