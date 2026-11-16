"""Isolated checks for wide home, booklets, board decisions and visible chat replies."""
import copy
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['ECHO_OFFLINE']='1'
os.environ['QT_QPA_PLATFORM']='windows' if '--shots' in sys.argv else 'offscreen'
from PyQt5.QtCore import Qt,QSettings
from PyQt5.QtWidgets import QApplication,QPushButton


def main():
    with tempfile.TemporaryDirectory(prefix='echo-workspace-revision-') as folder:
        from echo.backend import paths
        paths.config_dir=lambda:folder
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,folder)
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        app=QApplication([])
        from echo.theme import apply_theme
        apply_theme(app)
        from echo.backend import store,booklets,blackboard,config
        store.save_lesson('数学 · 正比例函数',[{'name':'正比例函数','mastery':.7,'status':'review'}],[],
                          summary='正比例函数写成 y=kx，图像经过原点。')
        store.save_lesson('数学 · 反比例函数',[{'name':'反比例函数','mastery':.8,'status':'ok'}],[],
                          summary='反比例函数写成 y=k/x，分母不能为零。')
        topics=booklets.catalog()
        assert len(topics)==2 and all(t['category']=='数学' for t in topics)
        generated=booklets.generate('函数综合复习','函数',topics,use_ai=False)
        saved=booklets.save(generated)
        assert len(saved['chapters'])==2 and len(booklets.load())==1
        assert len({s['label'] for s in saved['sources']})==2
        source_snapshot=copy.deepcopy(saved['sources'])
        with patch('echo.backend.booklets.store.list_lessons',return_value=[]):
            assert booklets.load()[0]['sources']==source_snapshot
        with patch('echo.backend.llm.LLM') as model:
            model.return_value.json.return_value={'intro':'比较两种函数。','chapters':[{'title':'先看关系','body':'根据来源比较函数表达式。','source_ids':['S1'],'question':'定义域要注意什么？','answer':'检查表达式的限制。'}]}
            ai=booklets.generate('函数复习','数学',topics,use_ai=True)
            assert ai['mode']=='ai' and model.return_value.json.call_args.kwargs['purpose']=='booklet'

        gate=blackboard.TopicBoardGate()
        moment={'concepts':[{'topic':'正比例函数','summary':'第一段','board_needed':True,'board_focus':'正比例函数'}],'sources':[{'text':'y=kx'}]}
        assert not gate.ready(moment,0) and gate.ready(moment,3)
        gate.completed(gate.key(moment))
        moment['concepts'][0]['summary']='只是继续举例，摘要变了'
        assert not gate.ready(moment,100)
        moment['concepts'][0].update(board_needed=False,board_focus='另一个主线')
        assert not gate.key(moment)
        with patch.dict(os.environ,ECHO_AI_ACTIVITY='active'):
            assert config.activity_intervals()[0]==20
        with patch.dict(os.environ,ECHO_AI_ACTIVITY='economy'):
            assert config.activity_intervals()[0]==50

        from echo.widgets.floating_window import FloatingWindow,HOME
        window=FloatingWindow()
        window._show_home()
        window.show()
        for _ in range(3): app.processEvents()
        assert not window.home_tools_panel.isVisible()
        compact_height=window.height()
        window.home_tools_toggle.click()
        for _ in range(3):app.processEvents()
        a=window.home_features_grid.itemAtPosition(0,0).widget().geometry()
        b=window.home_features_grid.itemAtPosition(0,1).widget().geometry()
        assert b.x()>a.x() and a.y()==b.y() and window.width()>650
        assert window.height()>compact_height
        window.home_tools_toggle.click()
        for _ in range(3):app.processEvents()
        assert not window.home_tools_panel.isVisible()
        fake_exam=ModuleType('echo.widgets.exam_window')
        from unittest.mock import Mock
        fake_exam.open_exam_window=Mock(return_value=SimpleNamespace())
        with patch.dict(sys.modules,{'echo.widgets.exam_window':fake_exam}):
            window.home_exam_entry.btn.click()
            assert fake_exam.open_exam_window.call_args.kwargs['engine'] is window.echo.engine
            assert fake_exam.open_exam_window.call_args.kwargs['parent'] is window
        fake_cloud=ModuleType('echo.widgets.cloud_workspace')
        fake_cloud.open_cloud_workspace=Mock(return_value=SimpleNamespace())
        with patch.dict(sys.modules,{'echo.widgets.cloud_workspace':fake_cloud}):
            window.home_cloud_paper_card.btn.click()
            fake_cloud.open_cloud_workspace.assert_called_once_with(parent=window,view='qingjuan')
            assert window._cloud_workspace is fake_cloud.open_cloud_workspace.return_value
            from echo.widgets.exam_window import ExamWindow
            cloud_exam=ExamWindow(parent=window)
            cloud_exam.cloud_paper_button.click()
            assert fake_cloud.open_cloud_workspace.call_args.kwargs=={'parent':cloud_exam,'view':'qingjuan'}
            assert cloud_exam._cloud_workspace is fake_cloud.open_cloud_workspace.return_value
            cloud_exam.close()
        assert not any('课前资料库' in button.text() for button in window.stack.widget(HOME).findChildren(QPushButton))
        with patch.object(window,'_open_settings') as open_settings:
            # Rewire the signal only for this isolated navigation check.
            window.profile_page.settings_requested.connect(open_settings)
            with patch('echo.widgets.settings.open_settings_dialog'):
                window.profile_page.btn_settings.click()
            assert open_settings.called
        from echo.widgets.settings import SettingsDialog
        settings=SettingsDialog(window)
        assert settings.btn_library and settings.combos['ECHO_AI_ACTIVITY']
        with patch('echo.widgets.learning_studio.KnowledgeLibrary.exec_',return_value=0) as library:
            settings.btn_library.click()
            library.assert_called_once()
        settings.close()
        from echo.widgets.booklet_window import BookletWindow
        shelf=BookletWindow(parent=window)
        assert shelf.windowTitle()=='Echo · 我的小本'
        with patch.dict(sys.modules,{'echo.widgets.exam_window':fake_exam}):
            shelf.exam_button.click()
            assert fake_exam.open_exam_window.call_args.kwargs['parent'] is window
        assert shelf.list.count()==1 and '函数综合复习' in shelf.reader.toPlainText()

        from echo.widgets.blackboard import BlackboardWindow
        from echo.backend.engine import Line
        from echo.mock_data import Concept
        engine=window.echo.engine
        engine.active=True
        engine.title='数学 · 正比例函数'
        engine.entries=[SimpleNamespace(t=0,concept=Concept('00:00','正比例函数',[],[],'y=kx'))]
        engine.lines=[Line(1,'正比例函数可以写为 y=kx，图像经过原点。')]
        board=BlackboardWindow(engine)
        assert len(board.tabs)==4 and board.tabs[3].text()=='聊天'
        initial={'title':'正比例函数','gist':'y=kx','steps':[{'label':'关系','heading':'表达式','body':'y=kx','evidence':['T1']}],
                 'sources':[{'id':'T1','kind':'transcript','label':'老师原话','text':'y=kx'}],'pattern':'概念脉络','check':{},
                 'pitfall':'','course':engine.title,'created':time.time(),'mode':'ai','trigger':'manual'}
        board._request+=1
        board.finish(board._request,copy.deepcopy(initial),'')
        assert len(board._boards)==1
        board._chat_question='为什么经过原点？'
        board.chat_page.add('user',board._chat_question)
        revised=copy.deepcopy(initial)
        revised.update(created=time.time(),reply='因为把 x=0 代入，有 y=0。我补充了第一节的这一步。')
        revised['steps'][0]['body']='把 x=0 代入 y=kx，可得 y=0。'
        board._request+=1
        board.finish(board._request,revised,'')
        assert len(board._boards)==1 and board._board['revision']==1
        assert board.chat_page.history[-1]['role']=='assistant'
        assert any('第1节' in button.text() for button in board.chat_page.findChildren(QPushButton))
        unchanged=copy.deepcopy(board._board)
        board._chat_question='好的'
        board._request+=1
        response=blackboard.normalize({'update_board':False,'reply':'不客气，继续听老师讲。'},[])
        board.finish(board._request,response,'')
        assert board._board==unchanged and len(board._boards)==1
        assert board.chat_page.history[-1]['text']=='不客气，继续听老师讲。'
        if '--shots' in sys.argv:
            (ROOT/'artifacts').mkdir(exist_ok=True)
            engine.active=False
            window._show_home()
            for _ in range(3):app.processEvents()
            window.grab().save(str(ROOT/'artifacts/echo-home-horizontal.png'))
            shelf.show()
            app.processEvents()
            shelf.grab().save(str(ROOT/'artifacts/echo-revision-booklet.png'))
            engine.active=True
            board.show()
            board.show_tab(3)
            app.processEvents()
            board.grab().save(str(ROOT/'artifacts/echo-board-chat.png'))
            board.history.showPopup()
            app.processEvents()
            board.history.view().window().grab().save(str(ROOT/'artifacts/echo-board-dropdown.png'))
            board.history.hidePopup()
        board._timer.stop()
        board.close()
        shelf.close()
        engine.active=False
        window.close()
    print('PASS compact home / my notebook / exam entry wiring / settings / board decisions / chat replies and revisions')


if __name__=='__main__':main()
