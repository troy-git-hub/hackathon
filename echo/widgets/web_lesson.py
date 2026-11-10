"""Offline HTML lesson viewer. No network, files, navigation or Python bridge."""
import html
import json

from PyQt5.QtCore import Qt, QCoreApplication, QUrl, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtGui import QColor

from echo.theme import Colors

if QCoreApplication.instance() is None:
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


def step_visual(board):
    """A grounded, immediately readable lesson while deeper teaching is prepared."""
    sources = {source["id"]: source for source in board.get("sources", [])}
    steps = [{"heading": step["heading"], "label": step.get("label", ""), "body": step["body"],
              "source": "\n\n".join(sources[key].get("label", "") + "\n" + sources[key].get("text", "")
                                      for key in step.get("evidence", []) if key in sources)} for step in board["steps"]]
    data = json.dumps(steps, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    check = board.get("check") or {}
    reflection = ("<details><summary>" + html.escape(check.get("question", "")) + "</summary><p>" +
                  html.escape(check.get("answer", "")) + "</p></details>") if check.get("question") else ""
    return {"title": board["title"], "mode": "local", "html": """
<style>
main{padding:16px 14px 24px;max-width:640px;margin:auto}.hint{color:var(--accent);font-size:11px;letter-spacing:1px}
h1{font-size:22px;margin:8px 0 10px;line-height:1.45}.intro{color:var(--muted);margin:0 0 18px}.node{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0}
.node button{flex:1;min-width:80px;font-size:12px}.node button[aria-pressed=true]{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}
article{padding:16px;border:1px solid var(--border);border-radius:12px;background:var(--surface)}
small{color:var(--accent)}h2{font-size:18px;margin:6px 0 10px}p{line-height:1.85}.actions{display:flex;gap:8px;margin-top:12px}.actions button{flex:1;font-size:12px}
.source{font-size:12px;color:var(--muted);white-space:pre-line;border-left:2px solid var(--accent);padding-left:12px;margin-top:12px}
#source-toggle{border:0;background:transparent;color:var(--accent);font-size:12px;padding-left:0;margin-top:6px}
details{margin-top:18px;padding:14px;border:1px solid var(--border);border-radius:12px}summary{cursor:pointer;font-weight:600}details p{color:var(--muted);margin-bottom:0}
</style><main><div class=hint>课堂脉络</div><h1>""" + html.escape(board["title"]) + "</h1><p class=intro>" + html.escape(board.get("gist", "")) + """</p>
<div id=nodes class=node></div><article><small id=stage></small><h2 id=heading></h2><p id=detail></p><button id=source-toggle>对照老师原话 ↗</button><div id=source class=source hidden></div></article>
<div class=actions><button id=prev>回看前一个关系</button><button id=next>继续梳理 →</button></div>""" + reflection + """</main>
<script>const steps=""" + data + """;let index=0;const nodes=document.querySelector('#nodes');
steps.forEach((s,i)=>{const b=document.createElement('button');b.textContent=s.heading;b.onclick=()=>show(i);nodes.appendChild(b)});
function show(i){index=i;document.querySelector('#stage').textContent=steps[i].label;
document.querySelector('#heading').textContent=steps[i].heading;document.querySelector('#detail').textContent=steps[i].body;
const source=document.querySelector('#source');source.textContent=steps[i].source;source.hidden=true;document.querySelector('#source-toggle').hidden=!steps[i].source;
Array.from(nodes.children).forEach((b,j)=>b.setAttribute('aria-pressed',String(i===j)));
document.querySelector('#prev').disabled=i===0;document.querySelector('#next').disabled=i===steps.length-1;}
document.querySelector('#source-toggle').onclick=()=>{const source=document.querySelector('#source');source.hidden=!source.hidden};
document.querySelector('#prev').onclick=()=>show(Math.max(0,index-1));document.querySelector('#next').onclick=()=>show(Math.min(steps.length-1,index+1));show(0);
</script>"""}


def sandbox_document(fragment):
    palette = {"bg": Colors.WINDOW_BG, "surface": Colors.SURFACE, "text": Colors.TEXT_PRIMARY,
               "muted": Colors.TEXT_SECONDARY, "accent": Colors.ACCENT, "border": Colors.BORDER_STRONG,
               "accent-soft": Colors.ACCENT_SOFT, "on-accent": Colors.ON_ACCENT}
    variables = ";".join(f"--{key}:{value}" for key, value in palette.items())
    policy = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
              "img-src data:; connect-src 'none'; font-src 'none'; frame-src 'none'; "
              "object-src 'none'; base-uri 'none'; form-action 'none'; worker-src 'none'")
    lockdown = """<script>
for(const key of ['fetch','XMLHttpRequest','WebSocket','WebTransport','EventSource','RTCPeerConnection',
 'webkitRTCPeerConnection','Worker','SharedWorker','open']){
 try{Object.defineProperty(window,key,{value:undefined,writable:false,configurable:false});}catch(e){}
}
try{Object.defineProperty(navigator,'sendBeacon',{value:undefined,writable:false,configurable:false});}catch(e){}
window.addEventListener('error',e=>parent.postMessage({type:'echo-lesson',ready:false,error:String(e.message).slice(0,180)},'*'));
window.addEventListener('unhandledrejection',()=>parent.postMessage({type:'echo-lesson',ready:false,error:'交互脚本未能完成'},'*'));
document.addEventListener('DOMContentLoaded',()=>parent.postMessage({type:'echo-lesson',ready:true,error:''},'*'));
</script>"""
    child = (f'<!doctype html><html lang="zh"><head><meta charset="utf-8">'
             f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
             '<meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<style>:root{{{variables}}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);'
             'font:14px/1.75 "Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif;overflow-wrap:anywhere}'
             'h1,h2,h3,p{overflow-wrap:anywhere}h1{font-size:22px;line-height:1.45}h2{font-size:18px;line-height:1.5}'
             'button,input,select,textarea{font:inherit;color:var(--text)}svg,canvas{max-width:100%}'
             'button{cursor:pointer;min-height:36px;padding:8px 12px;border-radius:9px;border:1px solid var(--border);'
             'background:var(--surface);color:var(--text);line-height:1.5;max-width:100%;white-space:normal}'
             'button:hover{border-color:var(--accent)}button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}'
             'button:disabled{opacity:.4;cursor:default}input[type=range]{width:100%;accent-color:var(--accent)}'
             'input:not([type=range]){max-width:100%;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:7px 10px}'
             '::-webkit-scrollbar{width:6px;height:6px;background:transparent}'
             '::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}</style>' + lockdown + '</head><body>' + fragment + '</body></html>')
    # Separate opaque iframe origin; no same-origin privilege, popup, forms or download flags.
    return ('<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;width:100%;height:100%;'
            f'overflow:hidden;background:{Colors.WINDOW_BG}' + '}iframe{width:100%;height:100%;border:0}</style></head><body>'
            '<script>window.echoLessonState={ready:false,error:""};window.addEventListener("message",e=>{'
            'const f=document.querySelector("iframe");if(f&&e.source===f.contentWindow&&e.data&&e.data.type==="echo-lesson")'
            '{if(e.data.error)window.echoLessonState={ready:false,error:String(e.data.error)};'
            'else if(!window.echoLessonState.error)window.echoLessonState={ready:!!e.data.ready,error:""};}});</script>'
            '<iframe title="课堂交互讲解" sandbox="allow-scripts" referrerpolicy="no-referrer" srcdoc="'
            + html.escape(child, quote=True) + '"></iframe></body></html>')


if AVAILABLE:
    class OfflineRequests(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            if info.requestUrl().scheme().lower() not in ("data", "about"):
                info.block(True)

    class OfflinePage(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, main_frame):
            return url.toString() in ("about:blank", "about:srcdoc") or (main_frame and url.scheme() == "data")

        def createWindow(self, kind):
            return None

        def chooseFiles(self, mode, old_files, accepted_mime_types):
            return []

        def javaScriptConsoleMessage(self, level, message, line, source):
            # Do not forward model-controlled console messages to application logs.
            pass


class HtmlLesson(QWidget):
    loaded = pyqtSignal(bool)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fragment = ""
        self.view = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if not AVAILABLE:
            text = QLabel("此安装版本尚未包含交互讲解组件，请更新应用。板书与来源仍可查看。")
            text.setWordWrap(True)
            layout.addWidget(text)
            return
        self.profile = QWebEngineProfile(self)  # Off the record: no disk cookies or cache.
        self.interceptor = OfflineRequests(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(lambda item: item.cancel())
        self.profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        self.view = QWebEngineView(self)
        self.page = OfflinePage(self.profile, self.view)
        self.page.setBackgroundColor(QColor(Colors.WINDOW_BG))
        self.view.setPage(self.page)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        settings = self.page.settings()
        for attribute in (QWebEngineSettings.JavascriptCanOpenWindows, QWebEngineSettings.JavascriptCanAccessClipboard,
                          QWebEngineSettings.LocalContentCanAccessFileUrls, QWebEngineSettings.LocalContentCanAccessRemoteUrls,
                          QWebEngineSettings.LocalStorageEnabled, QWebEngineSettings.PluginsEnabled,
                          QWebEngineSettings.FullScreenSupportEnabled, QWebEngineSettings.ScreenCaptureEnabled,
                          QWebEngineSettings.WebGLEnabled, QWebEngineSettings.AllowRunningInsecureContent):
            settings.setAttribute(attribute, False)
        self.page.featurePermissionRequested.connect(lambda origin, feature: self.page.setFeaturePermission(origin, feature, QWebEnginePage.PermissionDeniedByUser))
        self.page.renderProcessTerminated.connect(lambda *_: self.failed.emit("演示已中断，可切回板书后重新打开。"))
        self.view.loadFinished.connect(self.loaded)
        self.view.loadFinished.connect(self._check_state)
        layout.addWidget(self.view)

    def _check_state(self, ok):
        if ok and self.view:
            self.page.runJavaScript("window.echoLessonState", lambda state: self.failed.emit("这次讲解中的交互未能完成，请重新展开讲解。")
                                    if isinstance(state, dict) and state.get("error") else None)

    def display(self, visual):
        self.fragment = visual.get("html", "")
        if self.view:
            self.view.setHtml(sandbox_document(self.fragment), QUrl("about:blank"))

    def stop(self):
        if self.view:
            self.view.setHtml("", QUrl("about:blank"))
