"""Real sandbox rendering with isolated diagram accounts and mocked inference."""
import copy,json,os,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(ECHO_OFFLINE='1',ECHO_THEME=os.getenv('ECHO_THEME','dark'),QT_QPA_PLATFORM='windows' if os.name=='nt' else 'offscreen',QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu --no-sandbox')
SOURCE='''<main style="padding:20px"><h2>一次函数：变化率与初始值</h2><p>同一函数 y = 2x + 1；曲线、点和刻度共用投影。</p><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 260" style="width:100%;max-height:300px"><g stroke="var(--muted)"><path d="M30 220H330M70 240V20"/><path id="line" stroke="var(--accent)" stroke-width="3" d="M30 240L290 20"/></g><circle id="point" r="6" fill="var(--series-blue)"/><text x="330" y="238" fill="var(--text)">x</text><text x="80" y="22" fill="var(--text)">y</text></svg><input id="slider" type="range" min="0" max="4" value="2" step=".1"><p id="value"></p></main><script>const f=x=>2*x+1,px=x=>70+x*40,py=y=>220-y*20;const s=document.getElementById('slider');document.getElementById('line').setAttribute('d','M'+px(-1)+','+py(f(-1))+'L'+px(4)+','+py(f(4)));function draw(){let x=Number(s.value),y=f(x);document.getElementById('point').setAttribute('cx',px(x));document.getElementById('point').setAttribute('cy',py(y));document.getElementById('value').textContent='x = '+x+'，y = '+y;}s.oninput=draw;draw();</script>'''


def main():
    from PyQt5.QtCore import Qt,QSettings
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtTest import QTest
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    from echo.backend import paths,account,config,visual_code as api
    with tempfile.TemporaryDirectory(prefix='echo-visual-code-') as folder:
        paths.config_dir=lambda:folder;paths.app_dir=lambda:folder
        QSettings.setDefaultFormat(QSettings.IniFormat);QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,folder)
        app=QApplication([]);app.setQuitOnLastWindowClosed(False)
        from echo.theme import apply_theme
        apply_theme(app)
        from echo.widgets.visual_code import VisualCode
        user={'id':'visual-fixture'};calls=[];fail=[False]
        answer={'action':'read_code','reply':'代码使用统一函数和投影；仅根据代码分析，尚未查看真实画面。','html':''}
        def request(path,data,**kwargs):
            assert path=='/v1/echo/inference' and kwargs['auth_token']=='visual-token'
            assert data['purpose']=='blackboard' and data['context']['max_tokens']==3500
            calls.append(copy.deepcopy(data))
            if fail[0]:raise account.AccountError('模拟网络中断')
            return {'protocol':'echo.inference/2','account':{'id':'visual-fixture','balance':9},'result':{'text':json.dumps(answer),'finish_reason':'stop'}}
        spec={'id':'echo','api_key':'visual-token','model':'echo-text','base_url':'unused'}
        with patch.object(account,'current_user',side_effect=lambda:dict(user)),patch.object(account,'token',return_value='visual-token'),patch.object(account,'request',side_effect=request),patch.object(config,'OFFLINE',False),patch('echo.widgets.visual_code.providers.text',return_value=spec),patch('echo.widgets.visual_code.providers.vision',return_value=dict(spec,model='echo-vision')):
            assert api.checked(SOURCE)==SOURCE
            for unsafe in ('<iframe srcdoc="x"></iframe>','<script>fetch("/x")</script>','<img src="file:///secret">','<script>localStorage.x=1</script>'):
                try:api.checked(unsafe);raise AssertionError('accepted unsafe fragment')
                except ValueError:pass
            client=api.Client();fail[0]=True
            for _ in range(2):
                try:client.run('read',SOURCE,'解释','函数',spec=spec)
                except account.AccountError:pass
            assert len(calls)==2 and calls[-1]['request_id']==calls[-2]['request_id'],'uncertain retry changed billing identity'
            fail[0]=False;client.run('read',SOURCE,'解释','函数',spec=spec)
            assert calls[-1]['request_id']==calls[-2]['request_id']
            valid=[True];adopted=[];w=VisualCode(SOURCE,'一次函数 · 看代码与实际画面',context_valid=lambda:valid[0],adopt=adopted.append)
            w.setAttribute(Qt.WA_DontShowOnScreen,True);w.show()
            def wait(condition):
                until=time.monotonic()+10
                while not condition() and time.monotonic()<until:QTest.qWait(25)
                assert condition(),'renderer or worker did not settle'
            wait(lambda:w.preview_ready)
            assert w.preview.view.contextMenuPolicy()==Qt.NoContextMenu
            assert w.preview.profile.isOffTheRecord() and w.preview.page.settings().testAttribute(w.preview.page.settings().LocalContentCanAccessFileUrls)==False
            # Native board entry adopts exactly its selected diagram/version.
            from echo.widgets.blackboard import BlackboardWindow
            fixture={'created':1,'revision':0,'title':'函数关系','gist':'同一函数与投影','sources':[],
                'steps':[{'heading':'函数','body':'y=2x+1','evidence':[]}],'inline_visual':{'html':SOURCE},'check':{}}
            board=BlackboardWindow(archived=[fixture]);board.setAttribute(Qt.WA_DontShowOnScreen,True);board.show();app.processEvents()
            board.open_visual_code();workspace=board._visual_code_window;workspace.setAttribute(Qt.WA_DontShowOnScreen,True)
            wait(lambda:workspace.preview_ready);assert workspace.context_valid()
            workspace.code.appendPlainText('<!-- 采用测试 -->');workspace.apply_local();wait(lambda:workspace.preview_ready);workspace.apply_board()
            assert board._board['revision']==1 and '采用测试' in board._inline_view.fragment and workspace.context_valid()
            board._board['revision']+=1;assert not workspace.context_valid()
            workspace.close();board.close()
            from echo.widgets import dialogs
            with patch.object(dialogs,'confirm',return_value=True):
                before=len(calls);w.run('read');wait(lambda:not w.busy)
                assert len(calls)==before+1 and calls[-1]['task']=='text' and isinstance(calls[-1]['context']['messages'][-1]['content'],str)
                assert '仅根据代码' in w.reply.text() and not adopted
                answer.update(reply='已核对当前实际画面的可见区域，仍请对照教材。')
                w.run('inspect');wait(lambda:not w.busy)
                content=calls[-1]['context']['messages'][-1]['content']
                assert calls[-1]['task']=='vision' and content[1]['image_url']['url'].startswith('data:image/png;base64,iVBOR')
                # An unpreviewed edit cannot be presented as an actual screenshot review.
                before=len(calls);w.code.appendPlainText('<!-- 手改 -->');w.run('inspect');assert len(calls)==before
                w.apply_local();wait(lambda:w.preview_ready);w.apply_board();assert adopted and '手改' in adopted[-1]
                revision=w.revision;w.code.appendPlainText('<!-- 新版本 -->');w.finished(revision,{'reply':'旧回复','html':'<p>旧代码</p>'},'')
                assert '新版本' in w.code.toPlainText() and '没有覆盖' in w.notice.text()
                valid[0]=False;before=len(calls);w.run('write');assert len(calls)==before and not w.adopt_button.isEnabled()
            valid[0]=True;w.code.setPlainText(SOURCE);w.apply_local();wait(lambda:w.preview_ready)
            w.reply.setText('可查看代码、手改预览；需要时再让AI读取代码或核对当前实际画面。');w.notice.setText('预览仅运行当前片段，不联网、不读写文件、不执行系统命令。')
            app.processEvents();out=ROOT/'artifacts';out.mkdir(exist_ok=True);w.grab().save(str(out/f'echo-visual-code-{os.getenv("ECHO_THEME","dark")}.png'))
            user['id']='other';w.check_context();assert w.closed and not w.code.toPlainText() and not w.reply.text()
    print('PASS actual offline diagram preview, local edits/adopt, text-vs-image requests, 3500-token purpose, uncertain same-ID retry, stale-code/board/account guards, sandbox and private rendering; no live model')


if __name__=='__main__':main()
