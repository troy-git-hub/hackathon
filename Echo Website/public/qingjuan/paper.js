/* 青卷 · 试卷渲染 + 分页 */
(function (global) {
  const LETTERS = "ABCDEFGHIJ";

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function blanks(text) {
    return esc(text).replace(/_{2,}/g, '<span class="blank"></span>');
  }

  function figCaption(fig) {
    if (!fig) return "";
    const c = String(fig.caption || "").trim();
    if (!c || /^如\s*图/.test(c) || /^图\s*\d*$/.test(c)) return "";
    return `<div class="fig-cap">${esc(c)}</div>`;
  }

  function figureHTML(fig, style) {
    if (!fig || !global.QJFigures) return "";
    return global.QJFigures.renderFigure(fig, style);
  }

  function isWen(subject) {
    return ["语文", "英语", "历史", "地理", "道德与法治", "政治"].includes(subject);
  }

  function densityFactor(layout) {
    const d = layout.density || "normal";
    return d === "compact" ? 0.6 : d === "loose" ? 1.5 : 1;
  }

  function spaceLines(n, layout) {
    return Math.max(1, Math.round((Number(n) || 0) * densityFactor(layout)));
  }

  function optionsHTML(opts, layout) {
    if (!opts || !opts.length) return "";
    const long = opts.some((o) => String(o).length > 18);
    const cols = layout.optionCols === "auto" ? (long ? 1 : opts.length >= 4 && !long ? 2 : 1) : Number(layout.optionCols || 2);
    const cls = cols >= 4 ? "cols-4" : cols === 1 ? "cols-1" : "cols-2";
    const items = opts
      .map((o, i) => {
        const t = String(o).replace(/^[A-DＡ-Ｄ][\.．、]\s*/, "");
        return `<div class="opt"><span class="opt-mark">${LETTERS[i]}.</span>${esc(t)}</div>`;
      })
      .join("");
    return `<div class="q-opts ${cls}">${items}</div>`;
  }

  function spaceHTML(n, layout, lined) {
    n = spaceLines(n, layout);
    if (n <= 0) return "";
    const ln = lined ? "<div class='ln'></div>".repeat(n) : "<div class='room'></div>".repeat(n);
    return `<div class="q-space${lined ? "" : " blank-room"}">${ln}</div>`;
  }

  function clozePassage(s) {
    return esc(s).replace(/\{\{(\d+)\}\}/g, '<span class="cloze-n">$1</span>');
  }

  function essayGrid(chars) {
    const total = Math.min(800, Math.max(40, Number(chars) || 200));
    const per = 200; // 每块 10 行 200 字，可跨页
    let out = "";
    for (let n = 0; n < total; n += per) {
      const c = Math.min(per, total - n);
      out += `<div class="essay-grid" style="grid-template-columns: repeat(20, 1fr)">${"<i></i>".repeat(c)}</div>`;
    }
    return out;
  }

  function subQuestionHTML(sq, layout, view, no, path) {
    let s = `<div class="sub-q" data-path="${esc(path)}"><div class="q-hd"><span class="q-no">（${no}）</span><div class="q-stem">${blanks(sq.stem || "")}</div></div>`;
    if (sq.type === "choice" || (sq.options && sq.options.length)) s += optionsHTML(sq.options, layout);
    if (view === "answers") {
      s += `<div class="ans-q"><span class="ans">答案：${esc(sq.answer)}</span>${sq.analysis ? `<div class="ana">${esc(sq.analysis)}</div>` : ""}</div>`;
    } else if (sq.type === "short" || sq.type === "fill") {
      s += spaceHTML(3, layout, isWen(layout.subject));
    }
    return s + "</div>";
  }

  function passageHTML(q, layout) {
    const para = String(q.passage || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
    const body = para.length > 1
      ? para.map((p) => (q.type === "cloze" ? clozePassage(p) : esc(p))).map((p) => `<p>${p}</p>`).join("")
      : (q.type === "cloze" ? clozePassage(q.passage || "") : esc(q.passage || ""));
    const author = q.passage_author ? `<div class="passage-author">${esc(q.passage_author)}</div>` : "";
    const source = q.passage_source ? `<div class="passage-source">${esc(q.passage_source)}</div>` : "";
    return `<div class="passage"><div class="passage-meta">${author}${source}</div>${body}</div>`;
  }

  function renderQuestion(q, no, layout, view, path) {
    const type = q.type || "choice";
    const stem = blanks(q.stem || "");
    let extra = "";
    if (q.passage) extra += passageHTML(q, layout);
    if (type === "choice" || type === "multi") extra += optionsHTML(q.options, layout);
    if (type === "tf") extra += `<div class="q-tf"><div class="tf-row">（正确　错误）</div></div>`;
    if (q.questions && q.questions.length) {
      extra += q.questions.map((sq, i) => subQuestionHTML(sq, layout, view, i + 1, path)).join("");
    }
    if (q.requirements && q.requirements.length) {
      extra += `<ul class="req-list">${q.requirements.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`;
    }
    if (type === "essay" && layout.essayGrid !== false && view === "paper") {
      extra += essayGrid(q.grid?.chars || 400);
    } else if (view !== "answers" && type !== "choice" && type !== "multi" && type !== "tf" && type !== "essay" && type !== "fill") {
      extra += spaceHTML(q.answer_space, layout, isWen(layout.subject) && (type === "short" || type === "reading"));
    }
    const fig = figureHTML(q.figure, layout.figureStyle) + figCaption(q.figure);
    const choiceParen = (type === "choice" || type === "multi") && view === "paper" && !/[（(]\s*[）)]/.test(q.stem || "") ? '<span class="choice-paren">（　　）</span>' : "";
    const split = type === "reading" || type === "cloze" || type === "essay" ? " split-ok" : "";
    return `<div class="q-block${split}" data-path="${esc(path)}" data-type="${esc(type)}">
      <div class="q-hd"><span class="q-no">${no}．</span><div class="q-stem">${stem}${choiceParen}</div></div>
      ${fig}${extra}
    </div>`;
  }

  function renderAnswerItem(q, no, layout, path) {
    const type = q.type || "choice";
    const withQ = layout.answerQuestion !== false;
    let html = `<div class="ans-item" data-path="${esc(path)}"><div class="ans-head"><span class="q-no">${no}．</span>${withQ ? `<span class="ans-stem">${blanks(q.stem || "")}</span>` : ""}</div>`;
    if (withQ && q.passage) html += passageHTML(q, layout);
    if (withQ && (type === "choice" || type === "multi") && q.options?.length) html += optionsHTML(q.options, layout);
    if (withQ && q.figure) html += figureHTML(q.figure, layout.figureStyle) + figCaption(q.figure);
    if (withQ && q.questions && q.questions.length) {
      html += q.questions.map((sq, i) => {
        let s = `<div class="sub-q"><div class="q-hd"><span class="q-no">（${i + 1}）</span><div class="q-stem">${blanks(sq.stem || "")}</div></div>`;
        if (sq.options?.length) s += optionsHTML(sq.options, layout);
        s += `<div class="ans-q"><span class="ans">答案：${esc(sq.answer)}</span>${sq.analysis ? `<div class="ana">${esc(sq.analysis)}</div>` : ""}</div>`;
        return s + "</div>";
      }).join("");
    }
    html += `<div class="ans-q"><span class="ans">【答案】${esc(q.answer)}</span>${q.analysis ? `<div class="ana">${esc(q.analysis)}</div>` : ""}</div>`;
    return html + "</div>";
  }

  function answerBlocks(q,no,layout,path){
    const blocks=[];
    const parts=text=>String(text || '').split(/\n/).filter(Boolean).flatMap(p=>p.match(/.{1,300}(?:[。！？；]|$)|.{1,300}/g) || []);
    blocks.push(`<div class="ans-item" data-path="${esc(path)}"><div class="ans-head"><span class="q-no">${no}．</span>${layout.answerQuestion!==false?`<span class="ans-stem">${blanks(q.stem || '')}</span>`:''}</div>${layout.answerQuestion!==false && q.options?.length ? optionsHTML(q.options,layout):''}</div>`);
    if(layout.answerQuestion!==false && q.passage) for(const p of parts(q.passage)) blocks.push(`<div class="passage"><p>${esc(p)}</p></div>`);
    if(layout.answerQuestion!==false && q.figure) blocks.push(figureHTML(q.figure,layout.figureStyle));
    const children=q.questions || [];
    const answers=children.length ? children : [q];
    answers.forEach((item,i)=>{
      if(children.length){blocks.push(`<div class="ans-head"><b>${no}（${i+1}）</b><span class="ans-stem">${blanks(item.stem || '')}</span></div>`);if(item.options?.length)blocks.push(optionsHTML(item.options,layout));}
      parts(item.answer).forEach((p,j)=>blocks.push(`<div class="ans-q"><span class="ans">${j?'【答案续】':'【答案】'}${esc(p)}</span></div>`));
      parts(item.analysis).forEach((p,j)=>blocks.push(`<div class="ans-q"><div class="ana">${j?'':'【解析】'}${esc(p)}</div></div>`));
    });
    return blocks;
  }

  function studentFields(layout) {
    const fields = layout.fields || ["班级", "姓名", "学号", "得分"];
    return fields
      .map((f) => `<span>${esc(f)}：<span class="u"></span></span>`)
      .join("");
  }

  function renderTitle(paper, layout) {
    const m = paper.meta || {};
    const showScore = layout.scoreBox !== false;
    const fieldsOnTop = !layout.sealLine;
    return `<header class="paper-head" style="position:relative">
      ${showScore ? `<div class="score-box"><span>得分</span><span></span></div>` : ""}
      ${m.school ? `<div class="school">${esc(m.school)}</div>` : ""}
      <div class="main-title">${esc(m.title || "考试试卷")}</div>
      <div class="sub-title">${esc(m.subtitle || `${m.grade || ""} ${m.subject || ""}`.trim())}</div>
      <div class="meta-row">
        <span>考试时间：${esc(m.duration || 90)} 分钟</span>
        <span>满分：${esc(m.total_score || "")} 分</span>
        ${m.term ? `<span>${esc(m.term)}</span>` : ""}
      </div>
      ${fieldsOnTop ? `<div class="info-grid">${studentFields(layout)}</div>` : ""}
      <div class="head-rule"></div>
    </header>`;
  }

  function renderInstructions(paper) {
    const ins = (paper.meta || {}).instructions || [];
    if (!ins.length) return "";
    return `<div class="instructions"><span class="ins-h">注意事项：</span><ol>${ins.map((x) => `<li>${esc(x)}</li>`).join("")}</ol></div>`;
  }

  function sectionHead(sec, layout) {
    const score = layout.sectionScore === false ? "" : `<span class="sec-score">得分 <span style="display:inline-block;min-width:10mm"></span></span>`;
    return `<div class="sec-h"><span class="sec-title">${esc(sec.title || "")}</span><span class="sec-ins">${esc(sec.instruction || "")}</span>${score}</div>`;
  }

  function numberQuestions(paper) {
    let n = 0;
    return (paper.sections || []).filter(Boolean).map((sec) => {
      const qs = (sec.questions || []).map((q) => {
        n += 1;
        return { q, no: n };
      });
      return { sec, qs };
    });
  }

  function layoutClass(layout) {
    return [
      `tpl-${layout.template || "gaokao"}`,
      layout.colorMode === "color" ? "" : "print-mono",
      `density-${layout.density || "normal"}`,
      layout.bindLine ? "has-bind" : "",
      layout.sealLine ? "has-seal" : "",
      layout.paperSize === "16k" ? "size-16k" : "",
    ].join(" ");
  }

  function sealHTML(paper, layout) {
    if (!layout.sealLine) return "";
    const fields = layout.sealFields || ["姓名", "班级", "考号"];
    return `<div class="seal-col">
      <div class="seal-title">密封线内不要答题</div>
      ${fields.map((f) => `<div class="seal-field">${esc(f)}</div>`).join("")}
      <div class="barcode">条形码区</div>
    </div>`;
  }

  function pageShell(layout, paper, i, total, isFirst) {
    const el = document.createElement("article");
    el.className = `a4-page ${layoutClass(layout)} ${isFirst ? "is-first" : ""}`;
    const m = paper.meta || {};
    el.innerHTML = `
      ${layout.bindLine ? `<div class="bind-line"><span>装订线</span></div>` : ""}
      ${sealHTML(paper, layout)}
      ${layout.watermark ? `<div class="watermark">${esc(layout.watermark)}</div>` : ""}
      <div class="a4-inner">
        <div class="running-h"><span>${esc(m.school || "")} ${esc(m.subtitle || m.subject || "")}</span><span>第 ${i} 页</span></div>
        <div class="a4-body ${layout.columns === 2 ? "cols-2" : ""}"></div>
        <footer class="a4-foot">
          <span>${esc(layout.footerLeft || "")}</span>
          <span class="pg-num">${i} / ${total || "?"}</span>
          <span>${esc(layout.footerRight || "· 清卷 ·")}</span>
        </footer>
      </div>`;
    return el;
  }

  function typeset(root) {
    if (global.renderMathInElement) {
      try {
        global.renderMathInElement(root, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "\\[", right: "\\]", display: true },
            { left: "$", right: "$", display: false },
            { left: "\\(", right: "\\)", display: false },
          ],
          throwOnError: false,
        });
      } catch (_) {}
    }
  }

  function collectBlocks(paper, layout, view) {
    const htmls = [];
    if (view === "sheet") return sheetBlocks(paper, layout);
    if (view === "answers") {
      htmls.push(`<header class="paper-head"><div class="main-title">${esc((paper.meta || {}).title || "试卷")}</div><div class="sub-title">参考答案与解析</div><div class="head-rule"></div></header>`);
      htmls.push(...answerIndex(paper));
      const numbered = numberQuestions(paper);
      numbered.forEach(({ sec, qs }, si) => {
        htmls.push(sectionHead(sec, layout));
        qs.forEach(({ q, no }, qi) => htmls.push(...answerBlocks(q, no, layout, `${si}.${qi}`)));
      });
      return htmls.filter(Boolean);
    }
    htmls.push(renderTitle(paper, layout));
    if (layout.instructions !== false) htmls.push(renderInstructions(paper));
    const numbered = numberQuestions(paper);
    const splitVol = layout.splitVolume;
    let seenSubjective = false;
    numbered.forEach(({ sec, qs }, si) => {
      const subjective = !["choice", "multi", "tf"].includes(sec.type);
      if (splitVol && !seenSubjective && subjective && si > 0) {
        htmls.push(`<div class="vol-banner">第 II 卷（非选择题）</div>`);
        seenSubjective = true;
      }
      if (splitVol && si === 0 && !subjective) {
        htmls.push(`<div class="vol-banner">第 I 卷（选择题）</div>`);
      }
      htmls.push(sectionHead(sec, layout));
      qs.forEach(({ q, no }, qi) => {
        if ((q.type === "reading" || q.type === "cloze") && q.passage) {
          htmls.push(...readingBlocks(q, no, layout, view, `${si}.${qi}`));
        } else if(q.type==='essay' && layout.essayGrid!==false){
          htmls.push(renderQuestion(q,no,{...layout,essayGrid:false},view,`${si}.${qi}`));
          htmls.push(...(essayGrid(q.grid?.chars || 600).match(/<div class="essay-grid"[\s\S]*?<\/div>/g) || []));
        } else {
          htmls.push(renderQuestion(q, no, layout, view, `${si}.${qi}`));
        }
      });
    });
    return htmls.filter(Boolean);
  }

  function readingBlocks(q, no, layout, view, path) {
    const blocks = [];
    const paras = String(q.passage || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
    const head = `<div class="q-block split-ok" data-path="${esc(path)}"><div class="q-hd"><span class="q-no">${no}．</span><div class="q-stem">${blanks(q.stem || "")}</div></div>`;
    const meta = q.passage_author || q.passage_source
      ? `<div class="passage-meta">${q.passage_author ? `<span>${esc(q.passage_author)}</span>` : ""}${q.passage_source ? `<span class="passage-source">${esc(q.passage_source)}</span>` : ""}</div>`
      : "";
    const fig = figureHTML(q.figure, layout.figureStyle) + figCaption(q.figure);
    const chunks = [];
    const renderPara = (p) => (q.type === "cloze" ? clozePassage(p) : esc(p));
    const chunksCount = paras.length > 1 ? paras.length : 1;
    for (let i = 0; i < chunksCount; i++) {
      let html = "";
      if (i === 0) html += head + meta + `<div class="passage">`;
      else html += `<div class="q-block split-ok" data-path="${esc(path)}"><div class="passage">`;
      html += paras.length > 1 ? `<p>${renderPara(paras[i])}</p>` : renderPara(q.passage || "");
      html += `</div>`;
      if (i === chunksCount - 1) html += fig;
      html += `</div>`;
      chunks.push(html);
    }
    blocks.push(...chunks);
    if (q.questions && q.questions.length) {
      blocks.push(...q.questions.map((sq, i) => subQuestionHTML(sq, layout, view, i + 1, path)));
    }
    if (q.requirements && q.requirements.length) {
      blocks.push(`<div class="q-block split-ok" data-path="${esc(path)}"><ul class="req-list">${q.requirements.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`);
    }
    return blocks;
  }

  function answerIndex(paper) {
    const cells = [];
    let k = 0;
    (paper.sections || []).filter(Boolean).forEach((sec) => {
      (sec.questions || []).forEach((q) => {
        k += 1;
        cells.push({ no: k, answer: q.answer });
      });
    });
    const blocks = [];
    // Keep the index compact. Full answers, including long text and formulas,
    // are rendered below in the corresponding answer/analysis blocks.
    for (let i = 0; i < cells.length; i += 12) {
      const grid = cells.slice(i, i + 12).map(c => {
        const answer = String(c.answer ?? "").trim();
        const compact = answer.length <= 4 && !/[\n\r$\\]/.test(answer);
        const value = answer === "" ? "未填写" : compact ? answer : "见详解";
        return `<span class="idx-cell"><b>${c.no}</b><span class="idx-answer${compact ? "" : " idx-ref"}">${esc(value)}</span></span>`;
      }).join("");
      blocks.push(`<div class="answer-index"><div class="idx-h">答案速查${i ? "（续）" : ""}</div>${i ? "" : '<div class="idx-note">长答案及公式请查看下方对应题号的答案与解析。</div>'}<div class="idx-grid">${grid}</div></div>`);
    }
    return blocks;
  }

  function sheetBlocks(paper, layout) {
    const m = paper.meta || {};
    const blocks = [];
    blocks.push(`<div class="sheet-title">${esc(m.subtitle || m.subject || "答题卡")}</div><div class="sheet-sub">${esc(m.title || "")}</div>`);
    const fields = layout.fields || ["班级", "姓名", "学号"];
    blocks.push(`<div class="sheet-fields">${fields.map((f) => `<span class="sf"><i>${esc(f)}</i><b></b></span>`).join("")}<span class="sf"><i>得分</i><b></b></span></div>`);
    blocks.push(`<div class="sheet-note">请用黑色签字笔在对应区域内作答，选择题涂黑所选字母，不得超出答题区域。</div>`);
    const numbered = numberQuestions(paper);
    numbered.forEach(({ sec, qs }) => {
      const choice = ["choice", "multi", "tf"].includes(sec.type);
      blocks.push(`<div class="sheet-sec"><span class="sheet-sec-t">${esc(sec.title || "")}</span><span class="sheet-sec-s">得分<b></b></span></div>`);
      if (choice) {
        const rows = [];
        qs.forEach(({ q, no }) => {
          const n = q.type === "tf" ? 2 : (q.options || ["A", "B", "C", "D"]).length || 4;
          const marks = Array.from({ length: n }, (_, i) => `<span class="bub"><i>${q.type === "tf" ? (i ? "错" : "对") : LETTERS[i]}</i></span>`).join("");
          rows.push(`<div class="bubble-row"><span class="n">${no}</span><span class="bs">${marks}</span><span class="sc"></span></div>`);
        });
        for (let i = 0; i < rows.length; i += 10) {
          blocks.push(`<div class="bubbles">${rows.slice(i, i + 10).join("")}</div>`);
        }
      } else {
        qs.forEach(({ q, no }) => {
          const hint = layout.sheetHint !== false ? `<div class="sw-hint">${esc((q.stem || "").slice(0, 28))}${(q.stem || "").length > 28 ? "…" : ""}</div>` : "";
          if (q.type === "essay" && layout.essayGrid !== false) {
            blocks.push(`<div class="sheet-write"><div class="sw-h"><span class="n">${no}．</span><span class="sw-score">${esc(q.score || "")} 分</span></div>${hint}${essayGrid(q.grid?.chars || 400)}</div>`);
          } else {
            const score = Number(q.score || 0);
            const per = layout.density === "compact" ? 2.4 : layout.density === "loose" ? 4.4 : 3.4;
            const rows = Math.max(4, Math.min(12, Math.round(score * per)));
            const lined = isWen(layout.subject) && (q.type === "short" || q.type === "reading");
            const body = lined ? `<div class="sw-lines">${"<span></span>".repeat(rows)}</div>` : `<div class="sw-room" style="height:${rows * 8}mm"></div>`;
            blocks.push(`<div class="sheet-write"><div class="sw-h"><span class="n">${no}．</span><span class="sw-score">${esc(q.score || "")} 分</span></div>${hint}${body}</div>`);
          }
        });
      }
    });
    return blocks;
  }

  function paginate(container, paper, layout, view) {
    container.innerHTML = "";
    const htmls = collectBlocks(paper, layout, view);
    const probe = pageShell(layout, paper, 1, 1, true);
    probe.style.position = "absolute";
    probe.style.left = "-9999px";
    probe.style.visibility = "hidden";
    document.body.appendChild(probe);
    const body = probe.querySelector(".a4-body");
    const maxH = body.clientHeight;
    const width = body.clientWidth;
    probe.classList.remove("is-first");
    const runningH = Math.max(0, maxH - body.clientHeight);
    probe.classList.add("is-first");
    const cols = Number(layout.columns) === 2 ? 2 : 1;
    const measureW = cols === 2 ? Math.max(120, Math.floor((width - 24) / 2)) : width;
    const measure = document.createElement("div");
    measure.style.cssText = `position:absolute;left:-9999px;visibility:hidden;width:${measureW}px;height:auto;overflow:visible;display:flow-root;`;
    measure.className = probe.className;
    document.body.appendChild(measure);

    const heights = htmls.map((html) => {
      measure.innerHTML = html;
      typeset(measure);
      return Math.ceil(measure.getBoundingClientRect().height);
    });
    measure.remove();
    probe.remove();

    const pages = [];
    let used = 0;
    let page = pageShell(layout, paper, 1, 1, true);
    let dest = page.querySelector(".a4-body");

    function push() {
      pages.push(page);
      page = pageShell(layout, paper, pages.length + 1, 1, false);
      dest = page.querySelector(".a4-body");
      used = runningH;
    }

    htmls.forEach((html, i) => {
      const h = heights[i] || 24;
      const limit = maxH * (cols === 2 ? 1.82 : 1);
      const nextH=/class="sec-h"/.test(html) ? (heights[i+1] || 0) : 0;
      if (used > 8 && used + h + nextH > limit) push();
      dest.insertAdjacentHTML("beforeend", html);
      used += h + 2;
    });
    pages.push(page);

    pages.forEach((p, i) => {
      p.querySelector(".pg-num").textContent = `${i + 1} / ${pages.length}`;
      const rh = p.querySelector(".running-h span:last-child");
      if (rh) rh.textContent = `第 ${i + 1} 页`;
    });
    container.append(...pages);
    typeset(container);
    return pages.length;
  }

  function renderPaper(container, paper, layout, view) {
    if (!paper) {
      container.innerHTML = "";
      return 0;
    }
    layout = layout || {};
    if (!layout.subject) layout.subject = (paper.meta || {}).subject || "";
    view = view || "paper";
    return paginate(container, paper, layout, view);
  }

  global.QJPaper = { renderPaper, esc, numberQuestions };
})(window);
