"""Native Qingjuan UX regression: templates, window controls, no reload and scroll retention."""
import copy,json,os,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(ECHO_OFFLINE='1',ECHO_THEME='dark',QT_QPA_PLATFORM='windows' if os.name=='nt' else 'offscreen',QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu --no-sandbox')
from PyQt5.QtCore import Qt,QSettings,QTimer,QEventLoop
from PyQt5.QtWidgets import QApplication
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
from echo.backend import paths,account
from qingjuan_workbench_check import fixture


def sample_paper():
    def q(kind,stem,answer,analysis,score,**extra):return dict(type=kind,stem=stem,answer=answer,analysis=analysis,score=score,**extra)
    return {'meta':{'title':'一次函数 · 单元复习卷','subject':'数学','grade':'初中二年级','term':'上学期','duration':60},'sections':[
      {'title':'一、选择题','type':'choice','questions':[
        q('choice','下图表示函数 $y=2x+1$。当 $x=2$ 时，$y$ 的值是（　）。','A','将x=2代入，y=2×2+1=5。',5,options=['5','4','3','2'],figure={'kind':'coord','xmin':-2,'xmax':4,'ymin':-2,'ymax':8,'functions':[{'expr':'2*x+1'}]}),
        q('choice','函数 $y=-3x+2$ 的图像随 $x$ 增大而（　）。','B','一次项系数为负，函数值随x增大而减小。',5,options=['增大','减小','不变','无法确定']),
        q('choice','直线 $y=2x-4$ 与 $x$ 轴交点的横坐标是（　）。','C','令y=0，有2x-4=0，所以x=2。',5,options=['-4','-2','2','4']),
        q('choice','下列哪个点在直线 $y=x+3$ 上？','A','将(1,4)代入得4=1+3。',5,options=['(1,4)','(1,3)','(0,0)','(3,1)'])]},
      {'title':'二、填空题','type':'fill','questions':[
        q('fill','函数 $y=4x-1$ 的一次项系数是 ____。','4','y=kx+b中k=4。',5),
        q('fill','直线 $y=3x+2$ 与 $y$ 轴交点是 ____。','(0,2)','令x=0，y=2。',5),
        q('fill','直线 $y=x+1$ 和 $y=x-2$ 的位置关系是 ____。','平行','两条直线一次项系数相同而常数项不同。',5),
        q('fill','若 $y=2x+b$ 经过点 $(1,5)$，则 $b=$ ____。','3','代入5=2+b，解得b=3。',5)]},
      {'title':'三、计算题','type':'calculate','questions':[
        q('calculate','已知一次函数经过点 $(0,1)$ 和 $(2,5)$，求解析式。','y=2x+1','由(0,1)得b=1，再由5=2k+1得k=2。',10),
        q('calculate','求直线 $y=2x+1$ 与 $y=-x+4$ 的交点。','(1,3)','令2x+1=-x+4，得x=1，代入得y=3。',10)]},
      {'title':'四、解答题','type':'solve','questions':[
        q('solve','某出租车前3公里收费10元，超过3公里每公里收费2元。写出行驶里程x≥3时费用y与x的关系，并求行驶8公里的费用。','y=2x+4；20元','y=10+2(x-3)=2x+4。代入x=8，得y=20。',20),
        q('solve','租车方案甲收固定费50元，每小时20元；方案乙无固定费，每小时30元。分别列出费用与时间的关系，并说明何时选甲更便宜。','甲y=50+20x，乙y=30x；x>5时选甲更便宜。','比较50+20x<30x，得x>5；5小时时两方案相同。',20)]}]}


def main():
    with tempfile.TemporaryDirectory(prefix='echo-qj-ui-') as folder:
        paths.config_dir=lambda:folder
        QSettings.setDefaultFormat(QSettings.IniFormat);QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,folder)
        app=QApplication([]);app.setQuitOnLastWindowClosed(False)
        from echo.theme import apply_theme
        apply_theme(app)
        from echo.backend import qingjuan_local as local
        from echo.widgets.qingjuan_workbench import QingjuanWorkbench
        account.current_user=lambda:{'id':'ui-fixture'}
        with patch.object(account,'request',side_effect=AssertionError('unexpected network')):
            w=QingjuanWorkbench();w.move(-10000,-10000);w.show()
            def settle(ms=300):
                loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec_()
            def js(code):
                result=[];w.preview.page().runJavaScript(code,result.append)
                deadline=time.monotonic()+2
                while not result and time.monotonic()<deadline:settle(20)
                assert result,'renderer did not reply'
                return result[0]
            def ready():
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    settle(100)
                    if not w.preview_timer.isActive() and not w.preview._pending and not w.preview._flush_timer.isActive() and js('window.echoReady===true && window.echoRenderId==='+json.dumps(w.preview.render_key)):
                        settle(100);return
                raise AssertionError('preview not ready')
            assert w.parent() is None and w.windowFlags()&Qt.WindowMinimizeButtonHint and not w.windowIcon().isNull()
            w.showMinimized();settle(80);assert w.isMinimized();w.showNormal();settle(80);assert not w.isMinimized()
            w.toggle_pin();assert w.windowFlags()&Qt.WindowStaysOnTopHint
            w.toggle_pin();assert not w.windowFlags()&Qt.WindowStaysOnTopHint
            assert w.preview.contextMenuPolicy()==Qt.NoContextMenu and not w.student_answers.isVisible()
            w.fields['subject'].setEditText('语文');w.apply_template();cfg,lay=w.capture(strict=True)
            assert [s['type'] for s in cfg['sections']]==['choice','fill','reading','reading','essay']
            w.fields['grade'].setEditText('高中二年级');w.apply_template();assert w.capture(strict=True)[0]['total_score']==150
            w.fields['subject'].setEditText('数学');w.fields['grade'].setEditText('初中二年级');w.apply_template()
            assert len(w.section_rows)==4 and sum(s['count']*s['score_each'] for s in w.section_specs())==100
            for widget in w.section_rows[0]['fields'].values():assert widget.maximumWidth()>0
            paper=fixture();paper['sections'][0]['questions']*=3
            for index,q in enumerate(paper['sections'][0]['questions']):paper['sections'][0]['questions'][index]=dict(q,id='test'+str(index))
            local.replace_paper(w.doc,paper);w.populate();ready();reloads=w.preview._index
            assert js('window.QJExpression.compile("sqrt(x)+sin(x)")(0)')==0
            details=js('Array.from(document.querySelectorAll("svg path")).map(n=>({stroke:n.getAttribute("stroke"),len:(n.getAttribute("d")||"").length}))')
            assert any(p['stroke']=='#c45c4a' and p['len']>50 for p in details),details
            before=js('window.echoSelected="0.0";window.scrollTo(0,220);window.scrollY')
            w.questions.setCurrentItem(w.tree_paths[(0,0)]);w.qtexts['stem'].setPlainText('本机交互测试：函数的图像与性质。');w.apply_question();ready()
            assert w.preview._index==reloads,'editing reloaded browser'
            position=js('({y:window.scrollY,selected:window.echoSelected,outlined:document.querySelectorAll(".selected").length})')
            assert position['selected']=='0.0' and position['outlined']==1 and abs(position['y']-before)<5,position
            w.qtexts['analysis'].setPlainText('还没有应用的草稿文本');w.save_current(quiet=True);settle(400)
            assert w.preview._index==reloads and not w.preview_timer.isActive(),'draft-only autosave refreshed preview'
            w.discard_question_edit()
            sample=sample_paper();w.doc=local.new();w.doc['config'].update(title=sample['meta']['title'],duration=60,sections=[{'title':s['title'],'type':s['type'],'count':len(s['questions']),'score_each':s['questions'][0]['score'],'difficulty':'mixed','knowledge':'一次函数'} for s in sample['sections']])
            local.replace_paper(w.doc,sample);w.selected_path=None;w.populate();w.refresh_files();ready()
            w.tabs.setCurrentIndex(0);scroll=w.tabs.widget(0);scroll.verticalScrollBar().setValue(0);js('window.scrollTo(0,0)');settle(300)
            assert scroll.horizontalScrollBar().maximum()==0,'sidebar overflows at normal width'
            w.resize(960,760);settle(200);assert scroll.horizontalScrollBar().maximum()==0,'sidebar overflows at 960px'
            w.resize(1240,820);settle(200)
            output=ROOT/'artifacts';w.grab().save(str(output/'echo-qingjuan-redesign.png'))
            scroll=w.tabs.widget(0);scroll.verticalScrollBar().setValue(430);settle(120);w.grab().save(str(output/'echo-qingjuan-sections.png'))
            w.tabs.setCurrentIndex(3);settle(100);w.grab().save(str(output/'echo-qingjuan-native-practice-entry.png'))
            # In-flight display refresh must not re-expose the previous account.
            w.render_preview();account.current_user=lambda:{'id':'changed-account'};w.check_owner();settle(450)
            assert w.preview._pending is None and not w.preview_timer.isActive() and not w.tabs.isVisible()
            w.close();settle(100)
    print('PASS native taskbar window/icon/minimize/pin, editable metadata, complete subject templates, themed preview, actual function curves, no full reload, preserved scroll/selection, draft-only save, account-switch refresh cancellation')

if __name__=='__main__':main()
