"""Isolated screenshot regressions: themed menus, compact checks, figures/review."""
import copy,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(ECHO_OFFLINE='1',ECHO_THEME='dark',QT_QPA_PLATFORM='windows' if os.name=='nt' else 'offscreen',QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu --no-sandbox')
from PyQt5.QtCore import Qt,QSettings,QBuffer,QIODevice,QEventLoop,QTimer
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QColor,QPixmap
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)


def main():
    from echo.backend import paths
    with tempfile.TemporaryDirectory(prefix='echo-ui-followup-') as folder:
        paths.config_dir=lambda:folder
        QSettings.setDefaultFormat(QSettings.IniFormat);QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,folder)
        app=QApplication([])
        from echo.theme import apply_theme,Colors
        apply_theme(app)
        from echo.widgets.account_login import AccountLogin
        login=AccountLogin(allow_skip=True);login.setAttribute(Qt.WA_DontShowOnScreen,True);login.show();app.processEvents()
        assert login.form.rowCount()==4 and login.totp.isHidden()
        assert login.password.y()-login.password_login.y()<60
        login.two_factor.setChecked(True);app.processEvents();assert not login.totp.isHidden() and login.form.rowCount()==6
        login.two_factor.setChecked(False)
        menu=login.email.editing_menu();menu.setAttribute(Qt.WA_DontShowOnScreen,True);menu.popup(login.email.mapToGlobal(login.email.rect().bottomLeft()));app.processEvents()
        assert Colors.SURFACE in menu.styleSheet() and menu.windowFlags()&Qt.FramelessWindowHint
        assert any('粘贴' in a.text() for a in menu.actions()) and any('全选' in a.text() for a in menu.actions())
        assert menu.grab().toImage().pixelColor(10,10).rgb()==QColor(Colors.SURFACE).rgb()
        out=ROOT/'artifacts';out.mkdir(exist_ok=True);menu.grab().save(str(out/'echo-login-edit-menu.png'));menu.close()
        login.grab().save(str(out/'echo-login-compact.png'));login.close()
        from echo.widgets.checkin import CheckinCard
        card=CheckinCard();card.setAttribute(Qt.WA_DontShowOnScreen,True);card.resize(340,600)
        question={'type':'fill_blank','topic':'','question':'判断点(7,15)是否在函数 y=2x+1 的图像上：把 x=7 代入得 y=____。','answer':'15','explain':'2×7+1=15。'}
        card.ask(question)
        for _ in range(5):app.processEvents()
        assert card.height()<230,card.height()
        assert card._input.height()==32
        assert card._input.grab().toImage().pixelColor(8,8).rgb()!=QColor('#ffffff').rgb()
        card.grab().save(str(out/'echo-checkin-compact.png'))
        from echo.backend import assessment,prompts,blackboard,providers,config,account
        figure={'kind':'coord','xmin':-1,'xmax':9,'ymin':-1,'ymax':19,'functions':['2*x+1'],'points':[{'x':7,'y':15,'label':'P'}]}
        clean=assessment.clean_question(dict(question,figure=figure));assert clean['figure']==figure
        assert 'figure' not in assessment.clean_question(dict(question,figure={'kind':'unknown'}))
        card.ask(dict(question,figure=figure))
        for _ in range(5):app.processEvents()
        assert 240<card.height()<400,card.height()
        card.grab().save(str(out/'echo-checkin-figure.png'));card.dismiss();card.close()
        assert 'figure' in prompts.system('CHECKIN_SYSTEM',include_memory=False)
        assert 'figure' in prompts.system('PRACTICE_SYSTEM',n=5,include_memory=False)
        from echo.widgets.web_lesson import HtmlLesson
        lesson=HtmlLesson();lesson.move(-10000,-10000);lesson.resize(340,260)
        lesson.content_height.connect(lambda h:lesson.setFixedHeight(h));lesson.show()
        lesson.display({'html':'<h3>函数图与动点</h3><svg viewBox="0 0 320 230"><path d="M20 210 Q160 200 290 20" fill="none" stroke="orange"/><circle cx="160" cy="140" r="4" fill="orange"/></svg><p>拖动参数，观察点和曲线的位置。</p><label>x <input type="range" min="0" max="1" step=".1"></label>'})
        loop=QEventLoop();QTimer.singleShot(4000,loop.quit);loop.exec_()
        assert 260<lesson.height()<=450,lesson.height()
        buffer=QBuffer();buffer.open(QIODevice.WriteOnly);lesson.view.grab().save(buffer,'PNG');png=bytes(buffer.data())
        model=Mock();model.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'ok':False,'summary':'动点与曲线应共用同一投影。','html':'<p>修正后的图解</p>'},ensure_ascii=False)))])
        spec={'id':'echo','model':'echo-vision'}
        with patch.object(config,'OFFLINE',False),patch.object(providers,'vision',return_value=spec),patch.object(providers,'configured',return_value=True),patch.object(providers,'client',return_value=model),patch.object(providers,'vision_extra',return_value={}):
            result=blackboard.review_visual({'title':'函数图像'},lesson.fragment,png)
        assert result['html'] and model.chat.completions.create.call_count==1
        call=model.chat.completions.create.call_args.kwargs
        assert call['extra_body']['echo_purpose']=='blackboard' and call['timeout']>=110
        assert call['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
        lesson.stop();lesson.close()
        # A transport retry uses the same request and gives vision enough time.
        user={'id':'fixture','balance':2};reply={'protocol':'echo.inference/2','account':{'id':'fixture','balance':1},'result':{'text':'ok'}}
        with patch.object(account,'_token','test-token'),patch.object(account,'_user',user),patch.object(account,'request',side_effect=[account.AccountError('network'),reply]) as request:
            account.inference('vision',{'messages':[{'role':'user','content':'test'}]})
        assert request.call_args_list[0].kwargs['timeout']>=110
        assert request.call_args_list[0].args[1]['request_id']==request.call_args_list[1].args[1]['request_id']
        print('PASS compact login/2FA, readable Chinese edit menu, compact themed fill blank, Qingjuan figure, explicit rendered visual review, vision timeout/idempotency')


if __name__=='__main__':main()
