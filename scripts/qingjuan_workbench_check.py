"""Isolated local authoring + real offline renderer; all account/AI APIs mocked."""
import copy,json,os,sys,tempfile,time,uuid
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(ECHO_OFFLINE='1',ECHO_THEME='dark',QT_QPA_PLATFORM='windows' if os.name=='nt' else 'offscreen',QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu --no-sandbox')
from PyQt5.QtCore import Qt,QSettings
from PyQt5.QtWidgets import QApplication,QMessageBox,QFileDialog
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
from echo.backend import paths,account


def fixture():
    question={'id':'q1','type':'choice','stem':'若 $y=2x$，当 $x=3$ 时，$y$ 等于（　）。','options':['6','3'],'answer':'A','analysis':'代入可得 $y=2\\times3=6$。','score':2,'knowledge':'正比例函数','figure':{'kind':'coord','box':[-2,-2,4,8],'functions':[{'expr':'2*x'}]}}
    paper={'meta':{'title':'函数与阅读 · 本机测试','subject':'数学','grade':'初中二年级','duration':45},'sections':[
      {'title':'一、选择题','type':'choice','questions':[question,dict(question,id='q2',stem='正比例函数图像经过哪里？',options=['原点','任意点'])]},
      {'title':'二、阅读理解','type':'reading','questions':[{'id':'r1','type':'reading','stem':'读材料回答问题。','passage':'这是一段用于本机测试的原创材料。理解数量之间的关系，再用数学语言表达。','score':6,'questions':[
        {'id':'r1a','type':'short','stem':'用自己的话解释数量关系。','answer':'两个量成正比例。','analysis':'比值不变。','score':3},
        {'id':'r1b','type':'fill','stem':'比例系数是 ____。','answer':'2','analysis':'根据表达式识别。','score':3}]}]}]}
    return paper


def main():
    app=QApplication([])
    with tempfile.TemporaryDirectory(prefix='echo-qingjuan-local-') as folder:
        paths.config_dir=lambda:folder
        QSettings.setDefaultFormat(QSettings.IniFormat);QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,folder)
        from echo.theme import apply_theme
        apply_theme(app)
        from echo.backend import qingjuan_local as local
        user={'id':'test-account','name':'测试','balance':100,'role':'user'};calls=[]
        account.current_user=lambda:dict(user);account.token=lambda:'test-session'
        config=copy.deepcopy(local.DEFAULT_CONFIG);config.update(title='函数与阅读 · 本机测试',duration=45,total_score=10,sections=[
          {'title':'一、选择题','type':'choice','count':2,'score_each':2,'difficulty':'mixed','knowledge':'正比例函数'},
          {'title':'二、阅读理解','type':'reading','count':1,'score_each':6,'difficulty':'medium','knowledge':'数量关系'}])
        data=fixture();local.config(config)
        doc=local.new();doc['config']=config;local.save(doc)
        local.replace_paper(doc,data)
        all_questions=[]
        for kind in local.TYPES:
            q={'type':kind,'stem':'检查'+kind,'answer':'参考答案','analysis':'测试解析','score':1}
            if kind in ('choice','multi'):q.update(options=['选项一','选项二'],answer='A')
            elif kind=='tf':q['answer']='正确'
            elif kind in ('reading','cloze'):q.update(passage='原创测试阅读材料。',questions=[{'type':'short','stem':'子题','answer':'参考答案','analysis':'子题解析','score':1}])
            all_questions.append(q)
        full_types=local.normalize({'meta':{'title':'十二种题型'},'sections':[{'title':'全题型','questions':all_questions}]})
        assert {q['type'] for q in full_types['sections'][0]['questions']}==set(local.TYPES)
        assert local.load(user['id'],doc['id'])['paper']['meta']['total_score']==10
        assert local.list_documents('another-account')==[]
        old=copy.deepcopy(doc)
        with patch.object(local.os,'replace',side_effect=OSError('模拟磁盘写入失败')):
            try:local.replace_paper(doc,data)
            except OSError:pass
            else:raise AssertionError('disk failure swallowed')
        assert doc==old
        local.finalize(doc)
        try:local.replace_paper(doc,data)
        except ValueError:pass
        else:raise AssertionError('final paper overwritten')
        doc=local.fork(doc);assert doc['state']=='draft'
        def request(path,data=None,**kwargs):
            calls.append((path,copy.deepcopy(data)))
            if path=='/v1/qingjuan/capabilities':return {'local_storage':True}
            if path.endswith('/generate/start'):
                assert data['storage']=='local';assert 'config' in data and 'layout' in data
                return {'id':data['request_id'],'storage':'local','status':'accepted'}
            if '/generate/jobs/' in path:return {'id':path.rsplit('/',1)[1],'status':'succeeded','storage':'local','paper':fixture(),'layout':doc['layout'],'billing':{'cost':.3}}
            if path.endswith('/regenerate-question'):return {'question':dict(fixture()['sections'][0]['questions'][0],stem='新题：求 $2+4$。')}
            if path.endswith('/figure'):return {'figure':{'kind':'numberline','min':-3,'max':3}}
            if path=='/v1/echo/inference':
                assert data['purpose']=='qingjuan_generate' and data['protocol']=='echo.inference/2' and data['account_id']==user['id']
                return {'protocol':'echo.inference/2','account':{'id':user['id'],'balance':99},'result':inference(data['task'],data['context'],data['request_id'],data['purpose'])}
            if path=='/v1/me/requests':
                trace_id=next(body['request_id'] for route,body in reversed(calls) if body and body.get('request_id'))
                return {'items':[{'purpose':'qingjuan_generate','purpose_label':'清卷命题','state':'succeeded','cost':.3,'request_id':trace_id,'created':time.time(),'input_tokens':123,'output_tokens':456}]}
            raise AssertionError(path)
        def inference(task,context,request_id=None,purpose=None):
            assert purpose=='qingjuan_generate' and task=='text' and request_id
            assert context['max_tokens']<=4096
            payload=json.loads(context['messages'][1]['content'])
            if 'paper' in payload:return {'text':json.dumps({'approved':True,'summary':'未发现确定错误，仍需人工核对。','issues':[]})}
            entries=payload['entries']
            return {'text':json.dumps({'grades':[{'id':e['id'],'score':1,'feedback':'符合参考答案。'} for e in entries]}),'usage':{'input_tokens':10,'output_tokens':20}}
        account.request=request;account.inference=inference;local.GENERATION_ENABLED=True
        payload={'config':config,'layout':doc['layout']}
        result=local.ai(doc,'generate',payload)
        rid=doc['pending']['generate']['id'];local.ai(doc,'generate',payload)
        assert doc['pending']['generate']['id']==rid
        assert local.load(user['id'],doc['id'])['received']['paper']['meta']['title']==config['title']
        assert all(r['purpose']=='qingjuan_generate' for r in doc['requests'])
        with patch.object(account,'request',return_value={'local_storage':False}) as network:
            try:local.ai(doc,'generate',payload)
            except account.AccountError:pass
            else:raise AssertionError('unsupported local mode allowed')
            assert network.call_count==1
        from echo.widgets.qingjuan_workbench import QingjuanWorkbench
        from echo.widgets.ai_usage import AIUsageDialog
        window=QingjuanWorkbench();window.setAttribute(Qt.WA_DontShowOnScreen,True);window.doc=doc;window.populate();window.show()
        assert window.parent() is None and window.windowFlags()&Qt.WindowMinimizeButtonHint
        assert window.title_bar.minimize_button is not None and not window.windowIcon().isNull()
        assert window.preview.contextMenuPolicy()==Qt.NoContextMenu and window.student_answers.isHidden()
        assert all(window.fields[key].isEditable() for key in ('title','subject','grade','term','exam_name'))
        for subject in ('数学','语文','英语','物理','化学','生物','历史','地理','道德与法治','科学'):
            for scope in ('full','special'):
                preset=local.blueprint_template(subject,scope)
                cfg={**copy.deepcopy(local.DEFAULT_CONFIG),**{k:v for k,v in preset.items() if k!='layout_template'},'subject':subject,'paper_scope':scope}
                assert local.config(cfg)['sections']
        def wait(seconds=5):
            end=time.monotonic()+seconds
            while window.busy and time.monotonic()<end:app.processEvents();time.sleep(.01)
            app.processEvents();assert not window.busy
        def ready():
            if window.preview_timer.isActive() or window.preview._pending or window.preview._flush_timer.isActive():return False
            value=[];window.preview.page().runJavaScript('window.echoReady===true && window.echoRenderId==='+json.dumps(window.preview.render_key),lambda v:value.append(v))
            end=time.monotonic()+1
            while not value and time.monotonic()<end:app.processEvents();time.sleep(.01)
            return value and value[0]
        end=time.monotonic()+12
        while time.monotonic()<end and not ready():app.processEvents();time.sleep(.03)
        assert ready(),'offline paper renderer did not finish'
        info=[];window.preview.page().runJavaScript("({pages:document.querySelectorAll('.a4-page').length,math:document.querySelectorAll('.katex').length,curve:document.querySelector('path[stroke=\"#c45c4a\"]')?.getAttribute('d'),sqrt:window.QJExpression.compile('sqrt(x)')(9),text:document.body.textContent})",lambda v:info.append(v))
        end=time.monotonic()+2
        while not info and time.monotonic()<end:app.processEvents();time.sleep(.01)
        assert info[0]['pages']>=1 and info[0]['math']>=1
        assert len(info[0]['curve'] or '')>50 and info[0]['sqrt']==3,'real coordinate curve/parser missing'
        reloads=window.preview._index
        window.questions.setCurrentItem(window.tree_paths[(0,0)])
        window.qtexts['analysis'].setPlainText('本机编辑：代入表达式，计算得6。');window.apply_question()
        assert '本机编辑' in window.doc['paper']['sections'][0]['questions'][0]['analysis']
        window.undo();assert '本机编辑' not in window.doc['paper']['sections'][0]['questions'][0]['analysis']
        end=time.monotonic()+5
        while time.monotonic()<end and not ready():app.processEvents();time.sleep(.03)
        assert ready() and window.preview._index==reloads,'editing reloaded WebEngine instead of updating'
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
            window.questions.setCurrentItem(window.tree_paths[(0,0)]);window.regenerate();wait()
            assert window.doc['paper']['sections'][0]['questions'][0]['stem'].startswith('新题')
            window.figure();wait();assert window.doc['paper']['sections'][0]['questions'][0]['figure']['kind']=='numberline'
            window.answer_template();answers=json.loads(window.student_answers.toPlainText());answers={k:'解释数量关系' for k in answers};answers['q1']='A';answers['r1b']='2';window.student_answers.setPlainText(json.dumps(answers));window.grade();wait()
            assert window.doc['grading']['grades']
            window.review();wait();assert window.doc['review']['approved']
        # Pending editor text survives a save and re-open, but cannot leak into
        # exports or finalization until explicitly applied.
        window.questions.setCurrentItem(window.tree_paths[(0,0)]);window.qtexts['stem'].setPlainText('未应用编辑草稿')
        window.save_current(quiet=True);saved=local.load(window.owner,window.doc['id']);assert saved['editor_drafts']['0.0']['texts']['stem']=='未应用编辑草稿'
        window.doc=saved;window.populate();assert window.qtexts['stem'].toPlainText()=='未应用编辑草稿'
        window.discard_question_edit();assert not window.doc.get('editor_drafts')
        from echo.widgets.qingjuan_practice import LocalPaperPractice
        practice=LocalPaperPractice(window.doc,window);practice.setAttribute(Qt.WA_DontShowOnScreen,True);practice.show()
        # Existing graded practice can be restarted without network calls.
        before=len(calls)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
            practice.restart();practice.inputs['q1'][0][0].click();practice.inputs['q2'][0][0].click()
            practice.inputs['r1a'].setPlainText('两个量成正比例。');practice.inputs['r1b'].setPlainText('2');practice.submit()
        assert len(calls)==before and practice.practice['results']['q1']['score']==1
        assert practice.practice['results']['r1a']['status']=='pending'
        practice.close();window.doc=practice.doc
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
            window.generate();wait();ui_rid=window.doc['pending']['generate']['id'];window.generate(retry=True);wait()
            assert window.doc['pending']['generate']['id']==ui_rid
        from echo.widgets.qingjuan_preview import html
        exported=html(window.doc['paper'],window.doc['layout'],'answers',standalone=True)
        assert 'data:font/' in exported and 'connect-src' in exported and 'http://' not in exported.split('<body>')[0].split('<style>')[0]
        student_html=html(window.doc['paper'],window.doc['layout'],'paper',standalone=True)
        raw=student_html.split('const data=',1)[1].split(';window.echoReady',1)[0]
        student_data=json.loads(raw)
        assert 'config' not in student_data['paper']
        for section in student_data['paper']['sections']:
            for q in section['questions']:
                assert 'answer' not in q and 'analysis' not in q
                assert all('answer' not in child and 'analysis' not in child for child in q.get('questions',[]))
        out=Path(folder)/'export.json'
        with patch.object(QFileDialog,'getSaveFileName',return_value=(str(out),'')):window.export('json')
        assert json.loads(out.read_text(encoding='utf-8'))['schema']=='echo.qingjuan.paper/1'
        pdf=Path(folder)/'paper.pdf'
        with patch.object(QFileDialog,'getSaveFileName',return_value=(str(pdf),'')):window.export('pdf')
        deadline=time.monotonic()+18
        while window.printing and time.monotonic()<deadline:app.processEvents();time.sleep(.02)
        assert not window.printing and pdf.is_file() and pdf.read_bytes().startswith(b'%PDF'),window.notice.text()
        usage=AIUsageDialog(autoload=False);usage.finish(request('/v1/me/requests'),'')
        assert usage.table.item(0,1).text()=='清卷' and usage.table.item(0,6).text()==window.doc['pending']['generate']['id']
        assert any(item['id']==usage.table.item(0,6).text() and item['purpose']=='qingjuan_generate' for item in window.doc['requests'])
        usage.close()
        output=ROOT/'artifacts';output.mkdir(exist_ok=True)
        window.tabs.setCurrentIndex(1);app.processEvents();window.grab().save(str(output/'echo-qingjuan-workbench.png'))
        window.tabs.setCurrentIndex(0);app.processEvents();window.grab().save(str(output/'echo-qingjuan-blueprint.png'))
        user['id']='another-account';window.check_owner();assert not window.tabs.isVisible() and not window.generate_button.isEnabled()
        window.close();app.processEvents()
        print('PASS local blueprint/atomic drafts/final fork/account isolation/local-only job/idempotency/capability guard/offline math preview/edit drafts/undo/regenerate/figure/grade/review/usage tracing/JSON HTML PDF export')


if __name__=='__main__':main()
