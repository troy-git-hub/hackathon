"""Product-owned teaching layout: models supply content, Echo owns the visual system."""
import html
import json

DESIGN_RULES = """呈现规范（与Echo原生界面一致）：
使用安静、紧凑的学习工具风格，留白8/12/16px，细边框、圆角10~14px；不用巨幅封面、花哨渐变、霓虹、表情图标或装饰性动画。
正文14~15px、行高1.7，标题20~22px、说明12px；字体继承宿主系统字体，不引入字体。
颜色仅用 --bg --surface --text --muted --accent --accent-soft --border --on-accent。强调色只标重点和选中态，禁止自选红蓝绿配色。
320~480px宽均可阅读，窄屏单列，按钮可换行、点击区至少36px；没有横向溢出、截断文字、默认浏览器按钮。
先给清楚的理解问题，再给可操作的主体和依据，最后用一个小问题检查理解；不要把所有内容缩成几条“下一步”。
交互必须改变解释或对照结果，而不只是切换编号。默认即显示足够内容，不要空白等用户猜操作。
界面只出现教学内容和自然的操作提示，不出现HTML/JSON/代码/模型/生成中等实现术语，不自称AI，不写网页制作过程。
遵守参考资料边界：扩展思考标为“理解角度”，未讲过的背景说“课堂未说明”，不得把年表先后当因果。
"""


def _text(value, limit=600):
    return str(value or "").strip()[:limit] if isinstance(value, (str, int, float)) else ""


def guided_html(raw, board):
    """Validate and render a humanities/concept lesson without model-authored layout."""
    if not isinstance(raw, dict):
        raise ValueError("讲解内容不完整，请重新展开讲解")
    allowed = {s["id"]: s for s in board.get("sources", [])}
    lenses = []
    items = raw.get("lenses")
    if not isinstance(items, list):
        raise ValueError("讲解缺少可探索的角度，请重试")
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        heading, body = _text(item.get("heading"), 80), _text(item.get("body"), 700)
        if not heading or not body:
            continue
        evidence = item.get("evidence") or []
        evidence = [e for e in evidence if isinstance(e, str) and e in allowed] if isinstance(evidence, list) else []
        lenses.append({"label": _text(item.get("label"), 16) or heading[:8], "heading": heading,
                       "body": body, "evidence": evidence})
    if len(lenses) < 2:
        raise ValueError("讲解缺少可对照的角度，请重试")
    comparison = raw.get("comparison") if isinstance(raw.get("comparison"), dict) else {}
    left, right = comparison.get("left"), comparison.get("right")
    if not all(isinstance(v, dict) and _text(v.get("title")) and _text(v.get("body")) for v in (left, right)):
        raise ValueError("讲解缺少有效的对照内容，请重试")
    if not _text(comparison.get("insight")):
        raise ValueError("讲解没有说明对照中的关键关系，请重试")
    checkpoint = raw.get("checkpoint") if isinstance(raw.get("checkpoint"), dict) else {}
    options = checkpoint.get("options")
    if not isinstance(options, list) or not _text(checkpoint.get("question")):
        raise ValueError("讲解缺少理解检查，请重试")
    options = [{"text": _text(o.get("text"), 180), "correct": o.get("correct") is True,
                "feedback": _text(o.get("feedback"), 500)} for o in options[:4] if isinstance(o, dict)]
    if len(options) < 2 or sum(o["correct"] for o in options) != 1 or not all(o["text"] and o["feedback"] for o in options):
        raise ValueError("讲解中的理解检查不完整，请重试")
    question = _text(raw.get("question"), 100) or board["title"]
    intro = _text(raw.get("intro"), 260) or board.get("gist", "")
    data = {"lenses": lenses, "sources": {key: {"label": value.get("label", key), "text": value.get("text", "")[:1200]}
                                            for key, value in allowed.items()}, "options": options}
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    esc = html.escape
    fragment = """<style>
.reading{padding:16px 14px 24px;max-width:640px;margin:auto}.reading h1{font-size:22px;line-height:1.45;margin:8px 0 10px;font-weight:650;letter-spacing:-.3px}
.reading .eyebrow{font-size:11px;letter-spacing:1px;color:var(--accent)}.reading .intro{color:var(--muted);margin:0 0 20px}
.reading h2{font-size:14px;margin:22px 0 10px}.reading .tabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}
.reading .tabs button{flex:1;white-space:normal;min-width:66px;font-size:12px}.reading button[aria-pressed=true]{background:var(--accent-soft);color:var(--accent);border-color:var(--accent)}
.reading .panel{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px}
.reading .panel h3{font-size:17px;line-height:1.5;margin:0 0 10px}.reading .body{white-space:pre-line;margin:0;line-height:1.85}
.reading .cite{margin-top:14px;color:var(--accent);font-size:12px;padding:4px 0;border:0;background:transparent;text-align:left;min-height:32px}
.reading .evidence{border-left:2px solid var(--accent);padding:0 0 0 12px;margin-top:12px;color:var(--muted);font-size:12px;white-space:pre-line}
.reading .compare{display:grid;grid-template-columns:1fr 1fr;gap:8px}.reading .compare .panel{padding:12px}.reading .compare h3{font-size:14px;margin:0 0 8px}.reading .compare p{font-size:13px;margin:0}
.reading .bridge{margin-top:10px;padding:12px;border-radius:10px;background:var(--accent-soft);font-size:13px}
.reading .check button{display:block;width:100%;margin:8px 0;text-align:left;white-space:normal}.reading .feedback{margin:10px 0 0;line-height:1.8;color:var(--accent);font-size:13px}
.reading .muted{font-size:12px;color:var(--muted)}@media(max-width:360px){.reading .compare{grid-template-columns:1fr}}
</style><main class=reading><div class=eyebrow>""" + esc(_text(raw.get("eyebrow"), 40) or "理解这节课") + "</div><h1>" + esc(question) + "</h1><p class=intro>" + esc(intro) + """</p>
<h2>换个角度，读懂这一点</h2><div class=tabs id=lenses></div>
<article class=panel><h3 id=lens-title></h3><p id=lens-body class=body></p><button class=cite id=evidence-toggle>对照课堂依据 ↗</button><div id=evidence class=evidence hidden></div></article>
<h2>放在一起看，区别在哪里？</h2><section class=compare>"""
    for side in (left, right):
        fragment += '<article class=panel><h3>' + esc(_text(side.get("title"), 60)) + '</h3><p>' + esc(_text(side.get("body"), 600)) + '</p></article>'
    fragment += '</section><p class=bridge>' + esc(_text(comparison.get("insight"), 400)) + '</p><h2>换你来判断</h2><section class="panel check"><p>' + esc(_text(checkpoint.get("question"), 240)) + """</p><div id=answers></div><p id=feedback class=feedback aria-live=polite></p><p class=muted>点选后看理由，也可以换一个答案比较。</p></section></main>
<script>const lesson=""" + payload + """;let active=0;const tabs=document.querySelector('#lenses');
lesson.lenses.forEach((item,i)=>{const b=document.createElement('button');b.type='button';b.textContent=item.label;b.onclick=()=>selectLens(i);tabs.appendChild(b)});
function selectLens(i){active=i;const item=lesson.lenses[i];document.querySelector('#lens-title').textContent=item.heading;document.querySelector('#lens-body').textContent=item.body;
Array.from(tabs.children).forEach((b,j)=>b.setAttribute('aria-pressed',String(j===i)));const e=document.querySelector('#evidence');e.hidden=true;e.textContent=item.evidence.map(id=>lesson.sources[id].label+'\\n'+lesson.sources[id].text).join('\\n\\n');document.querySelector('#evidence-toggle').hidden=!item.evidence.length;}
document.querySelector('#evidence-toggle').onclick=()=>{const e=document.querySelector('#evidence');e.hidden=!e.hidden};
const answers=document.querySelector('#answers');lesson.options.forEach((item,i)=>{const b=document.createElement('button');b.type='button';b.textContent=item.text;b.onclick=()=>{Array.from(answers.children).forEach((n,j)=>n.setAttribute('aria-pressed',String(j===i)));document.querySelector('#feedback').textContent=(item.correct?'理解对了 · ':'再想一步 · ')+item.feedback};answers.appendChild(b)});selectLens(0);
</script>"""
    return {"title": question, "html": fragment, "mode": "ai", "layout": "guided", "design_version": 2}
