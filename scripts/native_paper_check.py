"""Native API exam contract checks; isolated drafts, no real model or network."""
import copy
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
native_shots="--shots" in sys.argv
os.environ.update(ECHO_THEME="dark",QT_QPA_PLATFORM="windows" if native_shots and os.name=="nt" else "offscreen")
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication,QLabel,QRadioButton,QCheckBox,QTextEdit
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
from echo.backend import account,paper_cache,paths
from echo.widgets.paper_book import PaperBook,rich
from echo.widgets.paper_figure import expression,svg_bytes


def main():
    import traceback
    sys.excepthook=lambda typ,value,tb:traceback.print_exception(typ,value,tb)
    app=QApplication.instance() or QApplication([])
    from echo.theme import apply_theme
    apply_theme(app)
    print("APP_READY",flush=True)
    uid='fixture-user';aid=uuid.uuid4().hex;pid=uuid.uuid4().hex
    user={'id':uid,'name':'Echo 同学','email':'student@example.com'}
    paper={'id':aid,'title':'一次函数 · 青卷专项','status':'active','created':int(time.time()),'deadline':int(time.time())+1800,'revision':0,'server_time':int(time.time()),'anti_cheat':False,'answers':{},'count':3,'questions':[
        {'id':'q1','type':'single_choice','question':'如果以 10 元记作 $+10$ 元，那么支出 5 元记作（　）','points':33.333333,'options':['$+5$ 元','$-5$ 元','$+10$ 元','$-10$ 元']},
        {'id':'q2','type':'multiple_choice','question':'对于函数 $y=2x+1$，下列说法正确的是？','points':33.333333,'options':['图像经过点 (0,1)','y 随 x 增大而增大','图像经过原点','斜率为 2'],'figure':{'kind':'coord','xmin':-2,'xmax':3,'ymin':-3,'ymax':7,'functions':[{'expr':'2*x+1'}]}},
        {'id':'q3','type':'short_answer','question':'请写出你对一次函数斜率的理解。','points':33.333334,'options':[]}]}
    calls=[];fail=False
    def request(path,data=None,**kwargs):
        nonlocal paper
        calls.append((path,copy.deepcopy(data)))
        if fail:raise account.AccountError('测试断网')
        if path=='/v1/me/qingjuan/papers':return {'items':[{'id':pid,'title':paper['title']}]}
        if path=='/v1/me/study/attempts':return {'items':[dict(paper)]}
        if path.endswith('/start'):return copy.deepcopy(paper)
        if path.endswith('/answers'):
            assert data['revision']==paper['revision']
            paper['answers'].update(data['answers']);paper['revision']+=1;return copy.deepcopy(paper)
        if path.endswith('/submit'):
            paper.update(status='submitted',answers=data['answers'],score=66.7,pending_count=1,results={'q1':{'status':'correct','answer':1,'explanation':'支出用负数表示。'}})
            return copy.deepcopy(paper)
        if path.endswith(aid):return copy.deepcopy(paper)
        raise AssertionError(path)
    def wait(window):
        end=time.monotonic()+3
        while window.busy and time.monotonic()<end:app.processEvents();time.sleep(.01)
        app.processEvents();assert not window.busy
    with tempfile.TemporaryDirectory() as folder,patch.object(paths,'config_dir',return_value=folder),patch.object(account,'current_user',side_effect=lambda:dict(user) if user else None),patch.object(account,'token',return_value='fixture-session'),patch.object(account,'request',side_effect=request),patch('echo.widgets.paper_book.QMessageBox.question',return_value=16384):
        window=PaperBook(autoload=False);print("WINDOW_READY",flush=True);window.show();window.refresh();wait(window);print("LIST_READY",flush=True)
        assert window.list.count()==2
        window.open_selected();wait(window);print("ATTEMPT_READY",flush=True)
        assert window.stack.currentIndex()==1
        assert not any('WebEngine' in type(w).__name__ for w in window.findChildren(QLabel))
        window.body.findChildren(QRadioButton)[1].click();window.body.findChildren(QCheckBox)[0].click();window.body.findChildren(QCheckBox)[1].click()
        window.sync();wait(window)
        assert paper['answers']['q1']==1 and paper['revision']==1
        window.body.findChildren(QTextEdit)[0].setPlainText('斜率表示自变量每增加一单位时，函数值的变化。')
        fail=True;window.sync();wait(window)
        assert '草稿已保留' in window.notice.text()
        assert paper_cache.load(uid,aid)['answers']['q3'].startswith('斜率')
        try:paper_cache.load('different-user',aid)
        except OSError:pass
        else:raise AssertionError('cross-account draft leaked')
        fail=False;window.sync();wait(window)
        assert paper['answers']['q3'].startswith('斜率')
        # Screenshot a real native widget, including its QPainter coordinate chart.
        output=Path(__file__).resolve().parents[1]/'artifacts';output.mkdir(exist_ok=True)
        app.processEvents()
        if native_shots:window.grab().save(str(output/'echo-native-paper-answer.png'))
        window.submit();wait(window);assert window.paper['status']=='submitted'
        assert any('支出用负数' in label.text() for label in window.findChildren(QLabel))
        user.clear();window.tick();assert window.paper is None and not window.stack.isEnabled()
        assert window.list.count()==0
        window.closed=True;window.close()
        user.update(id=uid)
        library=PaperBook(autoload=False);library.show();library.refresh();wait(library);app.processEvents()
        if native_shots:library.grab().save(str(output/'echo-native-paper-library.png'))
        library.closed=True;library.close()
    assert '$' not in rich('$-5$') and '<sup>2</sup>' in rich('$x^2$')
    assert expression('2*x+1',3)==7
    try:expression('__import__("os").system("x")',1)
    except ValueError:pass
    else:raise AssertionError('unsafe function evaluated')
    assert b'href' not in svg_bytes('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://invalid"/><script>x</script><path d="M0 0L1 1"/></svg>')
    assert not any('inference' in path for path,_ in calls)
    print(json.dumps({'ok':True,'checks':['native answering','API revisions','offline draft','owner isolation','submission review','logout hides data','safe figures'],'requests':len(calls)}))


if __name__=='__main__':main()
