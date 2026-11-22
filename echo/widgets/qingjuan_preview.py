"""Offline-only Qingjuan typesetting; no account cookies, remote scripts or API."""
import base64
import copy
import hashlib
import json
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from PyQt5.QtCore import Qt,QUrl,pyqtSignal,QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor
from PyQt5.QtWebEngineWidgets import QWebEngineView,QWebEnginePage,QWebEngineProfile,QWebEngineSettings
from echo.backend import paths
from echo.theme import Colors


def assets():return Path(paths.asset('assets','qingjuan-local')).resolve()


def render_key(paper,layout,view):return hashlib.sha256(json.dumps([paper,layout,view],sort_keys=True,ensure_ascii=False).encode()).hexdigest()


@lru_cache(maxsize=2)
def resources(standalone):
    root=assets();css=(root/'paper.css').read_text(encoding='utf-8')
    katex=(root/'katex/katex.min.css').read_text(encoding='utf-8')
    if standalone:
        def font(match):
            name=match.group(1).strip('"\'');file=root/'katex'/name
            return 'url(data:font/'+('woff2' if file.suffix=='.woff2' else 'woff' if file.suffix=='.woff' else 'ttf')+';base64,'+base64.b64encode(file.read_bytes()).decode()+')'
        katex=re.sub(r'url\((fonts/[^)]+)\)',font,katex)
        js='\n'.join((root/file).read_text(encoding='utf-8') for file in ('katex/katex.min.js','katex/auto-render.min.js','expression.js','figures.js','paper.js'))
        return '<style>'+katex+css+'</style>','<script>'+js.replace('</script','<\\/script')+'</script>'
    styles=''.join('<link rel="stylesheet" href="'+(root/file).as_uri()+'">' for file in ('katex/katex.min.css','paper.css'))
    scripts=''.join('<script src="'+(root/file).as_uri()+'"></script>' for file in ('katex/katex.min.js','katex/auto-render.min.js','expression.js','figures.js','paper.js'))
    return styles,scripts


def html(paper,layout,view='paper',standalone=False):
    if view not in ('paper','answers','sheet'):raise ValueError('预览视图无效。')
    if standalone and view!='answers':
        # A student-facing HTML file must not hide solutions in its JS source.
        allowed={'id','type','stem','options','score','passage','passage_title','passage_author','passage_source','answer_space','figure','requirements','grid'}
        def question(q):
            result={k:copy.deepcopy(v) for k,v in q.items() if k in allowed}
            if q.get('questions'):result['questions']=[question(c) for c in q['questions']]
            return result
        paper={'meta':{k:copy.deepcopy(v) for k,v in paper['meta'].items() if k in ('title','subtitle','school','subject','grade','term','duration','total_score')},
               'sections':[{'title':s['title'],'type':s.get('type','short'),'instruction':s.get('instruction',''),'questions':[question(q) for q in s['questions']]} for s in paper['sections']]}
    styles,scripts=resources(standalone)
    data=json.dumps({'paper':paper,'layout':layout,'view':view},ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    size='185mm 260mm' if layout.get('paperSize')=='16k' else 'A4'
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src file: 'unsafe-inline'; style-src file: 'unsafe-inline'; font-src file: data:; img-src data:; connect-src 'none'; object-src 'none'; base-uri 'none'">
<title>清卷 · 本地预览</title>'''+styles+'''<style>
body{margin:0;background:#d8d7d2;padding:18px;font-family:'Microsoft YaHei',sans-serif}#paper{width:max-content;margin:auto}
.a4-page{margin-bottom:18px}.q-stem,.ans-item{overflow-wrap:anywhere}.selected{outline:2px solid #b78b2c}
@media print{body{padding:0}#paper{margin:0}.a4-page{margin:0;box-shadow:none;break-after:page}.selected{outline:0}}
@page{size:'''+size+''';margin:0}
</style></head><body><main id="paper"></main>'''+scripts+'''<script>
const data='''+data+''';window.echoReady=false;window.echoRenderId="'''+render_key(paper,layout,view)+'''";
let paintVersion=0;window.echoSelected='';
window.echoUpdate=async function(data,key,restore=true){const version=++paintVersion;window.echoReady=false;window.echoRenderId=key;
const scroll=window.scrollY;const selected=window.echoSelected;
let pageStyle=document.getElementById('echo-page-size');if(!pageStyle){pageStyle=document.createElement('style');pageStyle.id='echo-page-size';document.head.appendChild(pageStyle);}pageStyle.textContent='@page{size:'+(data.layout.paperSize==='16k'?'185mm 260mm':'A4')+';margin:0}';
const selector=selected?'[data-path="'+selected+'"]':null;const old=selector&&document.querySelector(selector);const top=old?old.getBoundingClientRect().top:null;
try{
QJPaper.renderPaper(document.getElementById('paper'),data.paper,data.layout,data.view);
if(document.fonts)await document.fonts.ready;
if(version!==paintVersion)return;
QJPaper.renderPaper(document.getElementById('paper'),data.paper,data.layout,data.view);
if(document.fonts)await document.fonts.ready;
if(version!==paintVersion)return;
if(restore){const node=selector&&document.querySelector(selector);if(node){node.classList.add('selected');window.scrollTo(0,top===null?scroll:window.scrollY+node.getBoundingClientRect().top-top);}else window.scrollTo(0,scroll);}
window.echoReady=true;document.title='清卷 · '+document.querySelectorAll('.a4-page').length+' 页';
}catch(error){document.getElementById('paper').textContent='排版未完成：'+error.message;window.echoError=error.message;}};
document.addEventListener('click',event=>{const q=event.target.closest('[data-path]');if(q){window.echoSelected=q.dataset.path;document.querySelectorAll('.selected').forEach(n=>n.classList.remove('selected'));q.classList.add('selected');document.title='qingjuan-select:'+q.dataset.path;}});window.echoUpdate(data,window.echoRenderId,false);
</script></body></html>'''


class _OnlyLocal(QWebEngineUrlRequestInterceptor):
    def __init__(self,folder,parent):super().__init__(parent);self.folder=Path(folder).resolve()
    def interceptRequest(self,info):
        url=info.requestUrl()
        if url.scheme()=='data':return
        if url.scheme()=='file':
            path=Path(url.toLocalFile()).resolve()
            if path.is_relative_to(assets()) or path.is_relative_to(self.folder):return
        info.block(True)


class _Page(QWebEnginePage):
    def acceptNavigationRequest(self,url,typ,main):
        return url.scheme() in ('file','about') and typ!=QWebEnginePage.NavigationTypeLinkClicked


class PaperPreview(QWebEngineView):
    selected=pyqtSignal(str)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.folder=tempfile.TemporaryDirectory(prefix='echo-qingjuan-preview-')
        self.profile=QWebEngineProfile(self)
        self.interceptor=_OnlyLocal(self.folder.name,self.profile);self.profile.setUrlRequestInterceptor(self.interceptor)
        self.setPage(_Page(self.profile,self))
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.page().setBackgroundColor(QColor(Colors.SURFACE))
        self.settings().setAttribute(QWebEngineSettings.LocalStorageEnabled,False)
        self.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls,False)
        self.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows,False)
        self.titleChanged.connect(lambda title:self.selected.emit(title.split(':',1)[1]) if title.startswith('qingjuan-select:') else None)
        self._index=0
        self.render_key=None;self._loaded=False;self._empty=False;self._pending=None
        self._flush_timer=QTimer(self);self._flush_timer.setSingleShot(True);self._flush_timer.setInterval(30);self._flush_timer.timeout.connect(self._flush)
        self.loadFinished.connect(self._load_done)

    def show_empty(self):
        if self._empty:return
        self._empty=True;self.render_key=None;self._loaded=False;self._pending=None
        self.setHtml(f'<html><body style="background:{Colors.SURFACE};color:{Colors.TEXT_SECONDARY};font:15px Microsoft YaHei,sans-serif;padding:60px 36px"><div style="color:{Colors.ACCENT};font-size:12px">清卷 · 本地排版</div><h2 style="color:{Colors.TEXT_PRIMARY};font-size:25px">把知识整理成一张好卷子。</h2><p>左侧已有完整蓝图，可按学科套用模板。</p><p>点击右上方 <b style="color:{Colors.ACCENT}">AI 命题</b>，生成后在这里预览、点选题目并编辑。</p><p style="margin-top:32px;font-size:12px">试卷 / 答案与解析 / 答题卡 · 本机作答 · PDF 导出</p></body></html>')

    def clear_content(self):
        self._pending=None;self._flush_timer.stop();self._loaded=False;self._loading=False;self._empty=True;self.render_key=None
        self.stop();self.setHtml('')

    def render(self,paper,layout,view):
        key=render_key(paper,layout,view)
        if key==self.render_key:return
        self.render_key=key;self._empty=False
        self._pending=(paper,layout,view,key)
        if self._loaded:self._flush_timer.start();return
        if getattr(self,'_loading',False):return
        self._start_load()

    def _start_load(self):
        if not self._pending:return
        paper,layout,view,key=self._pending;self._pending=None
        self._index+=1
        self._loading=True;self._loaded=False
        file=Path(self.folder.name)/('preview-'+str(self._index%2)+'.html')
        file.write_text(html(paper,layout,view),encoding='utf-8');self.load(QUrl.fromLocalFile(str(file)))

    def _load_done(self,ok):
        if self._empty:return
        self._loading=False;self._loaded=bool(ok)
        if self._pending:
            if self._loaded:self._flush_timer.start()
            else:self._start_load()

    def _flush(self):
        if not self._loaded or not self._pending:return
        paper,layout,view,key=self._pending;self._pending=None
        data=json.dumps({'paper':paper,'layout':layout,'view':view},ensure_ascii=False,allow_nan=False)
        self.page().runJavaScript('window.echoUpdate('+data+','+json.dumps(key)+',true)')

    def cleanup(self):
        self._pending=None;self._flush_timer.stop();self.stop();self.setHtml('');self.folder.cleanup()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.setZoomFactor(min(1,max(.35,(self.width()-44)/794)))
