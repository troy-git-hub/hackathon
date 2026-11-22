"""Isolated native learning-path integration; no live account or paid AI."""
import copy, os, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch,Mock
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
os.environ.update(ECHO_OFFLINE='1', ECHO_THEME=os.getenv('ECHO_THEME','dark'), QT_QPA_PLATFORM='windows' if '--native' in sys.argv else 'offscreen')


def main():
    from PyQt5.QtCore import Qt, QSettings
    from PyQt5.QtWidgets import QApplication, QWidget
    from PyQt5.QtTest import QTest
    from echo.backend import account, paths, learning_path as api
    with tempfile.TemporaryDirectory(prefix='echo-learning-path-') as folder:
        paths.config_dir=lambda:folder; paths.app_dir=lambda:folder
        QSettings.setDefaultFormat(QSettings.IniFormat); QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,folder)
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        app=QApplication([]); app.setQuitOnLastWindowClosed(False)
        from echo.theme import apply_theme
        apply_theme(app)
        from echo.widgets.learning_path import LearningPath, GoalOnboarding
        user={'id':'fixture-user'}; token=['fixture-token']; calls=[]
        state={'protocol':'echo.learning-path/1','day':api.today(),'goal':None,
            'day_plan':{'mode':'review','revision':0,'day':api.today()},'progress':{},
            'recommendations':[{'topic':'一次函数的应用','reason':'到期再确认'}]}
        def request(path,data=None,**kwargs):
            assert kwargs['auth_token']=='fixture-token'
            calls.append((path,copy.deepcopy(data)))
            if path.endswith('/planner/task'):
                p=state['planner'];assert data['context']==p['context'] and data['revision']==p['revision']
                next(t for t in p['tasks'] if t['id']==data['id'])['state']=data['state'];p['revision']+=1
            elif path.endswith('/planner'):
                p=state['planner'];assert data['context']==p['context'] and data['revision']==p['revision']
                assert all(set(t)=={'action','title','reason','topic','source_ids','minutes'} for t in data['tasks'])
                p.update(saved=True,stale=False,revision=p['revision']+1,tasks=[dict(t,id=str(i)*32,state='pending') for i,t in enumerate(data['tasks'],1)])
            elif path.endswith('/goal'):
                old=(state['goal'] or {}).get('revision',0)
                if data['revision']!=old: raise account.AccountError('目标已修改',409)
                state['goal']={**data,'revision':old+1}
            elif path.endswith('/today'):
                if data['revision']!=state['day_plan']['revision']: raise account.AccountError('今日安排已修改',409)
                state['day_plan'].update(mode=data['mode'],revision=data['revision']+1)
            elif path.endswith('/reflections'):
                state['progress']={'recalled':True,'reflected':bool(data['next_question'])}
            else: assert path==api.ROOT
            return copy.deepcopy(state)
        def settle(w):
            until=time.monotonic()+3
            while w.busy and time.monotonic()<until: QTest.qWait(10)
            assert not w.busy,'worker stalled'
        with patch.object(account,'current_user',side_effect=lambda:dict(user)), patch.object(account,'token',side_effect=lambda:token[0]), patch.object(account,'request',side_effect=request):
            w=LearningPath(snapshot=copy.deepcopy(state)); w.setAttribute(Qt.WA_DontShowOnScreen,True); w.show(); app.processEvents()
            assert w.tabs.currentIndex()==0 and not w.day_save.isEnabled()
            w.target.setText('独立解出一次函数应用题'); w.subject.setEditText('数学'); w.custom.setText('篮球计分情境')
            w.interests['运动'].setChecked(True); w.save_goal(); settle(w)
            assert w.snapshot['goal']['revision']==1 and w.tabs.currentIndex()==1
            assert calls[-1][1]['interests']==['运动'] and calls[-1][1]['interest']=='篮球计分情境'
            # Known cloud interests from another platform remain visible/removable.
            state['goal']['interests']=['篮球']; w.start('read',w.client.read); settle(w)
            assert w.interests['篮球'].isChecked(); w.interests['篮球'].setChecked(False)
            # A daily intent save preserves the unsaved goal form.
            w.target.setText('尚未保存的数学目标'); w.learn.setChecked(True); w.save_today(); settle(w)
            assert state['day_plan']['mode']=='learn' and w.dirty and w.target.text()=='尚未保存的数学目标'
            w.topic.setText('一次函数'); w.recall.setPlainText('变化率相同但初始值可以不同。'); w.question.setText('怎样区分截距？')
            w.save_reflection(); settle(w); rid=calls[-1][1]['id']; w.save_reflection(); settle(w)
            assert calls[-1][1]['id']==rid and state['progress']['recalled']
            # A stale revision cannot silently overwrite the server or auto retry.
            state['goal']['revision']+=1; before=len(calls); w.save_goal(); settle(w)
            assert w.conflict and w.target.text()=='尚未保存的数学目标' and len(calls)==before+1
            w.save_goal(); assert len(calls)==before+1
            from echo.widgets import dialogs
            with patch.object(dialogs,'confirm',return_value=True): w.reload(); settle(w)
            assert not w.conflict and not w.dirty
            # Crossing the Beijing day requires an explicit refresh, not a stale write.
            w.snapshot['day']='2000-01-01'; before=len(calls); w.save_today(); assert len(calls)==before and '新的一天' in w.notice.text()
            w.render(copy.deepcopy(state)); w.notice.setText('已同步到账户。'); w.tabs.setCurrentIndex(0); app.processEvents()
            # Shared task plan and all task buttons are real actions, never inference.
            state['planner']={'protocol':'echo.learning-planner/1','context':'f'*24,'revision':0,'origin':'rules','saved':False,'stale':False,'summary':'围绕一次函数安排今天。',
                'tasks':[{'id':'step-'+str(i),'action':a,'title':title,'reason':'先独立尝试，再核对。','topic':'一次函数','source_ids':[],'minutes':3,'state':'pending'} for i,(a,title) in enumerate([('reflect','回想关键关系'),('practice','验证理解'),('studio','理解卡点'),('qingjuan','配置综合练习')])]}
            w.render(copy.deepcopy(state));w.tabs.setCurrentIndex(2);app.processEvents();assert len(w.planner.buttons)==4
            QTest.mouseClick(w.planner.save,Qt.LeftButton);settle(w);assert w.snapshot['planner']['saved']
            task=w.snapshot['planner']['tasks'][0];w.plan_action('task_state',task);settle(w);assert w.snapshot['planner']['tasks'][0]['state']=='done'
            w.recall.clear();QTest.mouseClick(w.planner.buttons[0],Qt.LeftButton);assert w.tabs.currentIndex()==1 and w.topic.text()=='一次函数'
            from PyQt5.QtGui import QDesktopServices
            with patch.object(QDesktopServices,'openUrl',return_value=True) as browser:
                w.plan_action('studio',{});assert browser.call_args.args[0].toString()=='https://echo.xhbtroy.cn/studio.html'
            with patch('echo.widgets.qingjuan_workbench.open_qingjuan_workbench',return_value=Mock()) as compose:
                w.plan_action('qingjuan',{'topic':'函数'});assert compose.call_count==1
            child=Mock();child.busy=False;w.snapshot['practice']={'id':'a'*32,'status':'active'}
            with patch('echo.widgets.paper_book.open_paper_book',return_value=child):
                w.plan_action('practice',{});assert child.run.call_args.args[0]=='attempt'
            assert all('/inference' not in path for path,_ in calls)
            w.tabs.setCurrentIndex(2);app.processEvents();(ROOT/'artifacts').mkdir(exist_ok=True);w.grab().save(str(ROOT/'artifacts'/('echo-learning-planner-'+os.getenv('ECHO_THEME','dark')+'.png')))
            w.tabs.setCurrentIndex(0);app.processEvents()
            out=ROOT/'artifacts'; out.mkdir(exist_ok=True); theme=os.getenv('ECHO_THEME','dark')
            assert w.save.isVisible() and w.save.geometry().bottom()<w.height()
            w.grab().save(str(out/f'echo-learning-goal-{theme}.png'))
            if theme=='dark':w.grab().save(str(out/'echo-learning-goal.png'))
            w.tabs.setCurrentIndex(1); app.processEvents(); assert not w.save.isVisible()
            w.grab().save(str(out/f'echo-learning-today-{theme}.png'))
            if theme=='dark':w.grab().save(str(out/'echo-learning-today.png'))
            # Missing/legacy optional interests are supported.
            legacy=copy.deepcopy(state); legacy['goal'].pop('interests'); w.render(legacy)
            assert all(not c.isChecked() for c in w.interests.values())
            # Old-account responses and personal form text are discarded.
            user['id']='other-user'; w.finished('read',copy.deepcopy(state),None)
            assert w.closed and not w.snapshot and not w.target.text() and not w.recall.toPlainText()
            client=api.Client(); token[0]='rotated'; before=len(calls)
            try: client.read(); raise AssertionError('stale session accepted')
            except account.AccountError: pass
            assert len(calls)==before
            # First login only: no read for guests/offline, one read per identity.
            user['id']='fixture-user'; token[0]='fixture-token'; state['goal']=None
            parent=QWidget(); parent.setAttribute(Qt.WA_DontShowOnScreen,True); parent.show(); app.processEvents()
            onboarding=GoalOnboarding(parent); onboarding.timer.stop()
            with patch.dict(os.environ,{'ECHO_OFFLINE':'0'}), patch('echo.widgets.learning_path.open_learning_path') as opened:
                before=len(calls); onboarding.check()
                until=time.monotonic()+3
                while onboarding.pending and time.monotonic()<until: QTest.qWait(10)
                assert opened.call_count==1 and len(calls)==before+1
                onboarding.check(); assert len(calls)==before+1
            parent.close()
    print('PASS native goal/interest/day setup, legacy compatibility, reflection UUID reuse, conflict no-retry, draft preservation, Beijing rollover, account/session isolation, first-login one-shot; no live API/model')


if __name__=='__main__': main()
