/* 青卷 · 结构化配图 → SVG */
(function (global) {
  const NS = "http://www.w3.org/2000/svg";

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function sanitizeSvg(svg) {
    if (!svg || typeof svg !== "string") return "";
    try {
      const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
      const el = doc.documentElement;
      if (!el || el.nodeName.toLowerCase() !== "svg") return "";
      const tags = new Set(['svg','g','path','line','polyline','polygon','rect','circle','ellipse','text','tspan','defs','marker','title','desc','clippath','lineargradient','radialgradient','stop','pattern']);
      const attrs = new Set(['xmlns','viewbox','x','y','x1','x2','y1','y2','cx','cy','r','rx','ry','dx','dy','d','points','width','height','fill','stroke','stroke-width','stroke-linecap','stroke-linejoin','stroke-dasharray','stroke-dashoffset','fill-opacity','stroke-opacity','opacity','transform','font-size','font-family','font-weight','font-style','text-anchor','dominant-baseline','id','marker-start','marker-mid','marker-end','markerwidth','markerheight','refx','refy','orient','markerunits','clip-path','offset','stop-color','stop-opacity','gradientunits','gradienttransform','patternunits','patterntransform','preserveaspectratio','vector-effect']);
      [el, ...el.querySelectorAll("*")].forEach((n) => {
        const tag = n.tagName.toLowerCase();
        if (!tags.has(tag)) {
          n.remove();
          return;
        }
        [...n.attributes].forEach((a) => {
          const v = String(a.value || "");
          if (!attrs.has(a.name.toLowerCase()) || /javascript:/i.test(v) || (/url\s*\(/i.test(v) && !/^url\(#[a-zA-Z_][\w-]*\)$/.test(v))) n.removeAttribute(a.name);
          if ((a.name === "href" || a.name === "xlink:href") && !v.startsWith("#")) n.removeAttribute(a.name);
        });
      });
      if (!el.getAttribute("viewBox")) el.setAttribute("viewBox", "0 0 320 240");
      el.setAttribute("xmlns", NS);
      el.setAttribute("class", "fig-svg");
      el.removeAttribute("width");
      el.removeAttribute("height");
      return new XMLSerializer().serializeToString(el);
    } catch {
      return "";
    }
  }

  function mapper(box, w, h, pad, uniform = false) {
    const x0 = box[0], y0 = box[1], x1 = box[2], y1 = box[3];
    const iw = w - pad * 2;
    const ih = h - pad * 2;
    let sx = iw / Math.max(1e-6, x1 - x0);
    let sy = ih / Math.max(1e-6, y1 - y0);
    if (uniform) sx = sy = Math.min(sx, sy);
    const px = (w - (x1 - x0) * sx) / 2;
    const py = (h - (y1 - y0) * sy) / 2;
    return {
      x: (x) => px + (x - x0) * sx,
      y: (y) => py + (y1 - y) * sy,
      s: (r) => r * Math.min(sx, sy),
      sx, sy,
    };
  }

  function svgEl(w, h, extra = "") {
    return `<svg xmlns="${NS}" viewBox="0 0 ${w} ${h}" class="fig-svg" fill="none" stroke="#1c1917" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round">${extra}</svg>`;
  }

  const DIR = {
    n: [0, -12], s: [0, 14], e: [12, 4], w: [-12, 4],
    ne: [10, -10], nw: [-10, -10], se: [10, 12], sw: [-10, 12],
  };

  function text(x, y, label, cls = "fig-lab", italic = false) {
    return `<text class="${cls}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" fill="#1c1917" stroke="none" font-size="13" font-family="Times New Roman, STSong, SimSun, serif" font-style="${italic ? "italic" : "normal"}" text-anchor="middle">${esc(label)}</text>`;
  }

  function safeFn(expr) { return global.QJExpression ? global.QJExpression.compile(expr) : null; }

  function geomBounds(fig) {
    const xs = [], ys = [];
    const add = (p) => { if (Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1])) { xs.push(p[0]); ys.push(p[1]); } };
    for (const e of fig.elements || []) {
      (e.points || []).forEach(add);
      add(e.from); add(e.to); add(e.at); add(e.c); add(e.a); add(e.b);
    }
    if (xs.length < 2) return null;
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    if (maxX <= minX || maxY <= minY) return null;
    const dx = (maxX - minX) * 0.08 || 0.3;
    const dy = (maxY - minY) * 0.08 || 0.3;
    return [minX - dx, minY - dy, maxX + dx, maxY + dy];
  }

  function renderGeometry(fig, style) {
    const w = fig.width || 320;
    const h = fig.height || 240;
    const auto = geomBounds(fig);
    const box = auto || fig.box || [0, 0, 10, 8];
    const pad = 26;
    const m = mapper(box, w, h, pad, true);
    const cartoon = style === "cartoon";
    const sketch = style === "sketch";
    const sw = cartoon ? 2.4 : sketch ? 1.7 : 1.5;
    const fillDef = cartoon ? "#ffe3b8" : sketch ? "#f4f7f2" : "#f6f1e6";
    let body = `<rect x="0" y="0" width="${w}" height="${h}" fill="#fffef9" stroke="none"/>`;
    const els = fig.elements || [];
    for (const e of els) {
      const t = e.type;
      if (t === "polygon" && e.points) {
        const pts = e.points.map((p) => `${m.x(p[0]).toFixed(1)},${m.y(p[1]).toFixed(1)}`).join(" ");
        body += `<polygon points="${pts}" fill="${esc(e.fill || fillDef)}" stroke="#1c1917" stroke-width="${sw}"/>`;
      } else if (t === "line" || t === "dash" || t === "arrow") {
        const a = e.from, b = e.to;
        if (!a || !b) continue;
        const dash = t === "dash" || e.dash ? ' stroke-dasharray="5 4"' : "";
        const marker = t === "arrow" ? ' marker-end="url(#arr)"' : "";
        body += `<line x1="${m.x(a[0]).toFixed(1)}" y1="${m.y(a[1]).toFixed(1)}" x2="${m.x(b[0]).toFixed(1)}" y2="${m.y(b[1]).toFixed(1)}" stroke="#1c1917" stroke-width="${sw}"${dash}${marker}/>`;
      } else if (t === "circle") {
        const c = e.c || e.at;
        if (!c) continue;
        body += `<circle cx="${m.x(c[0]).toFixed(1)}" cy="${m.y(c[1]).toFixed(1)}" r="${m.s(e.r || 1).toFixed(1)}" fill="${esc(e.fill || "none")}" stroke="#1c1917" stroke-width="${sw}"/>`;
      } else if (t === "arc") {
        const c = e.c;
        const r = e.r || 1;
        const a0 = normDeg(e.a0 || 0);
        const a1 = normDeg(e.a1 || 90);
        const p0 = [c[0] + r * Math.cos((a0 * Math.PI) / 180), c[1] + r * Math.sin((a0 * Math.PI) / 180)];
        const p1 = [c[0] + r * Math.cos((a1 * Math.PI) / 180), c[1] + r * Math.sin((a1 * Math.PI) / 180)];
        let sweep = normDeg(a1 - a0);
        const large = sweep > 180 ? 1 : 0;
        if (sweep > 180) sweep = 360 - sweep;
        body += `<path d="M ${m.x(p0[0]).toFixed(1)} ${m.y(p0[1]).toFixed(1)} A ${m.s(r).toFixed(1)} ${m.s(r).toFixed(1)} 0 ${large} 1 ${m.x(p1[0]).toFixed(1)} ${m.y(p1[1]).toFixed(1)}" fill="none" stroke="#1c1917" stroke-width="${sw}"/>`;
      } else if (t === "point") {
        const p = e.at;
        const [dx, dy] = DIR[e.dir] || [0, -12];
        body += `<circle cx="${m.x(p[0]).toFixed(1)}" cy="${m.y(p[1]).toFixed(1)}" r="${cartoon ? 3.2 : 2.2}" fill="#1c1917" stroke="none"/>`;
        if (e.label) body += text(m.x(p[0]) + dx, m.y(p[1]) + dy, e.label);
      } else if (t === "label") {
        body += text(m.x(e.at[0]), m.y(e.at[1]), e.text || "");
      } else if (t === "right") {
        const at = e.at, f = e.from, to = e.to;
        const v1 = [f[0] - at[0], f[1] - at[1]];
        const v2 = [to[0] - at[0], to[1] - at[1]];
        const n1 = Math.hypot(v1[0], v1[1]) || 1;
        const n2 = Math.hypot(v2[0], v2[1]) || 1;
        const s = 0.45;
        const a = [at[0] + (v1[0] / n1) * s, at[1] + (v1[1] / n1) * s];
        const b = [at[0] + (v2[0] / n2) * s, at[1] + (v2[1] / n2) * s];
        const c = [a[0] + (v2[0] / n2) * s, a[1] + (v2[1] / n2) * s];
        body += `<path d="M ${m.x(a[0]).toFixed(1)} ${m.y(a[1]).toFixed(1)} L ${m.x(c[0]).toFixed(1)} ${m.y(c[1]).toFixed(1)} L ${m.x(b[0]).toFixed(1)} ${m.y(b[1]).toFixed(1)}" fill="none" stroke="#1c1917" stroke-width="${sw * 0.9}"/>`;
      } else if (t === "equal") {
        const a = e.a, b = e.b;
        const n = e.n || 1;
        const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
        const dx = b[0] - a[0], dy = b[1] - a[1];
        const len = Math.hypot(dx, dy) || 1;
        const px = (-dy / len) * 0.22, py = (dx / len) * 0.22;
        const tx = (dx / len) * 0.12, ty = (dy / len) * 0.12;
        for (let i = 0; i < n; i++) {
          const o = (i - (n - 1) / 2) * 0.16;
          const cx = mx + tx * (o / 0.12) * 0.8, cy = my + ty * (o / 0.12) * 0.8;
          body += `<line x1="${m.x(cx - px).toFixed(1)}" y1="${m.y(cy - py).toFixed(1)}" x2="${m.x(cx + px).toFixed(1)}" y2="${m.y(cy + py).toFixed(1)}" stroke="#1c1917" stroke-width="${sw}"/>`;
        }
      } else if (t === "angle") {
        const at = e.at, f = e.from, to = e.to;
        const a0 = Math.atan2(f[1] - at[1], f[0] - at[0]);
        const a1 = Math.atan2(to[1] - at[1], to[0] - at[0]);
        const r = e.r || 0.7;
        const p0 = [at[0] + r * Math.cos(a0), at[1] + r * Math.sin(a0)];
        const p1 = [at[0] + r * Math.cos(a1), at[1] + r * Math.sin(a1)];
        let delta = a1 - a0;
        while (delta <= -Math.PI) delta += 2 * Math.PI;
        while (delta > Math.PI) delta -= 2 * Math.PI;
        const large = Math.abs(delta) > Math.PI ? 1 : 0;
        const sweep = delta > 0 ? 0 : 1; // y-up vs svg y-down handled by mapper
        body += `<path d="M ${m.x(p0[0]).toFixed(1)} ${m.y(p0[1]).toFixed(1)} A ${m.s(r).toFixed(1)} ${m.s(r).toFixed(1)} 0 ${large} ${sweep} ${m.x(p1[0]).toFixed(1)} ${m.y(p1[1]).toFixed(1)}" fill="none" stroke="#1c1917" stroke-width="${sw * 0.9}"/>`;
        if (e.label) {
          const mid = a0 + delta / 2;
          const lr = r + 0.35;
          body += text(m.x(at[0] + lr * Math.cos(mid)), m.y(at[1] + lr * Math.sin(mid)), e.label);
        }
      }
    }
    body = `<defs><marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#1c1917" stroke="none"/></marker></defs>` + body;
    return svgEl(w, h, body);
  }

  let coordSerial = 0;
  function renderCoord(fig) {
    const w = fig.width || 340;
    const h = fig.height || 260;
    const xmin = fig.xmin ?? -2, xmax = fig.xmax ?? 6;
    const ymin = fig.ymin ?? -2, ymax = fig.ymax ?? 6;
    const pad = 32;
    const clip = 'qj-coord-clip-' + (++coordSerial);
    const m = mapper([xmin, ymin, xmax, ymax], w, h, pad);
    let body = `<rect x="0" y="0" width="${w}" height="${h}" fill="#fffef9" stroke="none"/>`;
    if (fig.grid !== false) {
      for (let x = Math.ceil(xmin); x <= Math.floor(xmax); x++) {
        body += `<line x1="${m.x(x).toFixed(1)}" y1="${m.y(ymin).toFixed(1)}" x2="${m.x(x).toFixed(1)}" y2="${m.y(ymax).toFixed(1)}" stroke="#e6dfd2" stroke-width="1"/>`;
      }
      for (let y = Math.ceil(ymin); y <= Math.floor(ymax); y++) {
        body += `<line x1="${m.x(xmin).toFixed(1)}" y1="${m.y(y).toFixed(1)}" x2="${m.x(xmax).toFixed(1)}" y2="${m.y(y).toFixed(1)}" stroke="#e6dfd2" stroke-width="1"/>`;
      }
    }
    const ox = Math.min(Math.max(0, xmin), xmax);
    const oy = Math.min(Math.max(0, ymin), ymax);
    body += `<line x1="${m.x(xmin).toFixed(1)}" y1="${m.y(oy).toFixed(1)}" x2="${m.x(xmax).toFixed(1)}" y2="${m.y(oy).toFixed(1)}" stroke="#1c1917" stroke-width="1.5" marker-end="url(#arr2)"/>`;
    body += `<line x1="${m.x(ox).toFixed(1)}" y1="${m.y(ymin).toFixed(1)}" x2="${m.x(ox).toFixed(1)}" y2="${m.y(ymax).toFixed(1)}" stroke="#1c1917" stroke-width="1.5" marker-end="url(#arr2)"/>`;
    body += text(m.x(xmax) - 8, m.y(oy) + 16, "x");
    body += text(m.x(ox) + 12, m.y(ymax) + 4, "y");
    body += text(m.x(0) - 10, m.y(0) + 14, "O");
    for (const fn of fig.functions || []) {
      const f = safeFn(fn.expr || fn);
      if (!f) continue;
      const dom = fn.domain || [xmin, xmax];
      const steps = 80;
      let d = "";
      let started = false;
      for (let i = 0; i <= steps; i++) {
        const x = dom[0] + ((dom[1] - dom[0]) * i) / steps;
        const y = f(x);
        if (y == null || y < ymin - 1 || y > ymax + 1) {
          started = false;
          continue;
        }
        const cmd = started ? "L" : "M";
        d += `${cmd}${m.x(x).toFixed(1)},${m.y(y).toFixed(1)} `;
        started = true;
      }
      body += `<path d="${d}" fill="none" stroke="#c45c4a" stroke-width="1.8" clip-path="url(#${clip})"/>`;
    }
    for (const seg of fig.segments || []) {
      const a = seg[0], b = seg[1];
      if (!a || !b) continue;
      body += `<line x1="${m.x(a[0]).toFixed(1)}" y1="${m.y(a[1]).toFixed(1)}" x2="${m.x(b[0]).toFixed(1)}" y2="${m.y(b[1]).toFixed(1)}" stroke="#1c1917" stroke-width="1.3"/>`;
    }
    for (const p of fig.points || []) {
      body += `<circle cx="${m.x(p.x).toFixed(1)}" cy="${m.y(p.y).toFixed(1)}" r="2.6" fill="#c45c4a" stroke="none"/>`;
      if (p.label) body += text(m.x(p.x) + 10, m.y(p.y) - 8, p.label);
    }
    body = `<defs><clipPath id="${clip}"><rect x="${pad}" y="${pad}" width="${w-pad*2}" height="${h-pad*2}"/></clipPath><marker id="arr2" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#1c1917" stroke="none"/></marker></defs>` + body;
    return svgEl(w, h, body);
  }

  function renderNumberline(fig) {
    const w = fig.width || 360;
    const h = fig.height || 90;
    const min = fig.min ?? -4, max = fig.max ?? 4;
    const ticks = fig.ticks || 1;
    const pad = 28;
    const y = 48;
    let body = `<rect width="${w}" height="${h}" fill="#fffef9" stroke="none"/>`;
    body += `<line x1="${pad}" y1="${y}" x2="${w - pad}" y2="${y}" stroke="#1c1917" stroke-width="1.5" marker-end="url(#arr3)"/>`;
    const n = Math.round((max - min) / ticks);
    for (let i = 0; i <= n; i++) {
      const v = min + i * ticks;
      const x = pad + ((v - min) / (max - min)) * (w - pad * 2);
      body += `<line x1="${x}" y1="${y - 6}" x2="${x}" y2="${y + 6}" stroke="#1c1917"/>`;
      body += text(x, y + 22, String(v));
    }
    for (const p of fig.points || []) {
      const x = pad + ((p.x - min) / (max - min)) * (w - pad * 2);
      body += `<circle cx="${x}" cy="${y}" r="4" fill="#c45c4a" stroke="none"/>`;
      if (p.label) body += text(x, y - 14, p.label);
    }
    body = `<defs><marker id="arr3" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#1c1917" stroke="none"/></marker></defs>` + body;
    return svgEl(w, h, body);
  }

  function renderBar(fig) {
    const w = fig.width || 320;
    const h = fig.height || 200;
    const cats = fig.categories || [];
    const vals = fig.values || [];
    const max = Math.max(1, ...vals);
    const padL = 36, padB = 36, padT = 16, padR = 16;
    const iw = w - padL - padR, ih = h - padT - padB;
    const bw = iw / Math.max(1, cats.length);
    let body = `<rect width="${w}" height="${h}" fill="#fffef9" stroke="none"/>`;
    body += `<line x1="${padL}" y1="${padT}" x2="${padL}" y2="${h - padB}" stroke="#1c1917"/><line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="#1c1917"/>`;
    const colors = ["#3d6e66", "#c45c4a", "#c4a574", "#6b8e9f", "#8a6a4a"];
    cats.forEach((c, i) => {
      const v = vals[i] || 0;
      const bh = (v / max) * ih;
      const x = padL + i * bw + bw * 0.2;
      const y = h - padB - bh;
      body += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw * 0.6).toFixed(1)}" height="${bh.toFixed(1)}" fill="${colors[i % colors.length]}" stroke="none" rx="2"/>`;
      body += text(padL + i * bw + bw / 2, h - 12, c);
      body += text(padL + i * bw + bw / 2, y - 8, String(v));
    });
    if (fig.unit) body += text(padL, 14, fig.unit);
    return svgEl(w, h, body);
  }

  function renderPie(fig) {
    const w = fig.width || 280;
    const h = fig.height || 200;
    const slices = fig.slices || [];
    const sum = slices.reduce((a, s) => a + (s.value || 0), 0) || 1;
    const cx = 90, cy = h / 2, r = Math.min(70, h / 2 - 12);
    const colors = ["#3d6e66", "#c45c4a", "#c4a574", "#6b8e9f", "#8a6a4a", "#7a9e7e"];
    let body = `<rect width="${w}" height="${h}" fill="#fffef9" stroke="none"/>`;
    let a = -Math.PI / 2;
    slices.forEach((s, i) => {
      const da = ((s.value || 0) / sum) * Math.PI * 2;
      const x1 = cx + r * Math.cos(a), y1 = cy + r * Math.sin(a);
      const x2 = cx + r * Math.cos(a + da), y2 = cy + r * Math.sin(a + da);
      const large = da > Math.PI ? 1 : 0;
      body += `<path d="M ${cx} ${cy} L ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)} Z" fill="${colors[i % colors.length]}" stroke="#fffef9" stroke-width="2"/>`;
      body += `<rect x="180" y="${24 + i * 22}" width="10" height="10" fill="${colors[i % colors.length]}" stroke="none"/>`;
      body += `<text x="196" y="${34 + i * 22}" fill="#1c1917" stroke="none" font-size="12" font-family="STSong, SimSun, serif">${esc(s.label)} ${s.value}</text>`;
      a += da;
    });
    return svgEl(w, h, body);
  }

  function normDeg(d) {
    d = Number(d) % 360;
    if (d < 0) d += 360;
    return d;
  }

  function turnTo(base, turn, side) {
    const cw = normDeg(base - turn);
    const ccw = normDeg(base + turn);
    if (side === "cw") return cw;
    if (side === "ccw") return ccw;
    const sinCcw = Math.sin((ccw * Math.PI) / 180);
    const sinCw = Math.sin((cw * Math.PI) / 180);
    if (side === "down") return sinCw <= sinCcw ? cw : ccw;
    return sinCcw >= sinCw ? ccw : cw;
  }

  function bisectDeg(a, b, side) {
    a = normDeg(a);
    b = normDeg(b);
    const ccw = normDeg(b - a);
    const minor = ccw <= 180 ? normDeg(a + ccw / 2) : normDeg(a - (360 - ccw) / 2);
    const major = normDeg(minor + 180);
    if (side === "major") return major;
    if (side === "down") {
      return Math.sin((minor * Math.PI) / 180) <= Math.sin((major * Math.PI) / 180) ? minor : major;
    }
    if (side === "up") {
      return Math.sin((minor * Math.PI) / 180) >= Math.sin((major * Math.PI) / 180) ? minor : major;
    }
    return minor;
  }

  function resolveRays(fig) {
    const rays = (fig.rays || []).map((r) => ({ ...r, name: r.name || r.to || r.label }));
    if (Array.isArray(fig.baseline) && fig.baseline.length >= 3) {
      const [a, o, b] = fig.baseline;
      fig.center = fig.center || o;
      if (!rays.some((r) => r.name === a)) rays.unshift({ name: a, deg: 180 });
      if (!rays.some((r) => r.name === b)) rays.unshift({ name: b, deg: 0 });
    }
    const byName = {};
    for (let pass = 0; pass < 8; pass++) {
      for (const r of rays) {
        if (r._deg != null || !r.name) continue;
        if (typeof r.deg === "number" && Number.isFinite(r.deg)) {
          r._deg = normDeg(r.deg);
        } else if (r.from && typeof r.turn === "number" && byName[r.from]) {
          r._deg = turnTo(byName[r.from]._deg, r.turn, r.side || "up");
        } else if (Array.isArray(r.bisect) && r.bisect.length >= 2 && byName[r.bisect[0]] && byName[r.bisect[1]]) {
          r._deg = bisectDeg(byName[r.bisect[0]]._deg, byName[r.bisect[1]]._deg, r.side);
        } else if (r.perp && byName[r.perp]) {
          r._deg = turnTo(byName[r.perp]._deg, 90, r.side || "up");
        }
        if (r._deg != null) byName[r.name] = r;
      }
    }
    return rays.filter((r) => r._deg != null && r.name);
  }

  function renderRays(fig) {
    const rays = resolveRays(fig);
    if (rays.length < 2) return "";
    const L = 132;
    const pts = rays.map((r) => {
      const rad = (r._deg * Math.PI) / 180;
      return { name: r.name, deg: r._deg, x: Math.cos(rad) * L, y: Math.sin(rad) * L };
    });
    const degs = pts.map((p) => p.deg).sort((a, b) => a - b);
    let gap = 0;
    let mid = 270;
    for (let i = 0; i < degs.length; i++) {
      const a = degs[i];
      const b = i + 1 === degs.length ? degs[0] + 360 : degs[i + 1];
      if (b - a > gap) {
        gap = b - a;
        mid = a + (b - a) / 2;
      }
    }
    const orad = (mid * Math.PI) / 180;
    const ox = Math.cos(orad) * 22;
    const oy = Math.sin(orad) * 22;
    let minX = Math.min(ox, 0) - 10;
    let maxX = Math.max(ox, 0) + 10;
    let minY = Math.min(oy, 0) - 10;
    let maxY = Math.max(oy, 0) + 10;
    for (const p of pts) {
      const rad = (p.deg * Math.PI) / 180;
      const lx = p.x + Math.cos(rad) * 20;
      const ly = p.y + Math.sin(rad) * 20;
      minX = Math.min(minX, p.x, lx);
      maxX = Math.max(maxX, p.x, lx);
      minY = Math.min(minY, p.y, ly);
      maxY = Math.max(maxY, p.y, ly);
    }
    const pad = 18;
    const W = Math.ceil(maxX - minX + pad * 2);
    const H = Math.ceil(maxY - minY + pad * 2);
    const X = (x) => pad + (x - minX);
    const Y = (y) => pad + (maxY - y);
    let body = `<rect width="${W}" height="${H}" fill="#fffef9" stroke="none"/>`;
    for (const p of pts) {
      body += `<line x1="${X(0).toFixed(1)}" y1="${Y(0).toFixed(1)}" x2="${X(p.x).toFixed(1)}" y2="${Y(p.y).toFixed(1)}" stroke="#1c1917" stroke-width="1.6"/>`;
      body += `<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="2.5" fill="#1c1917" stroke="none"/>`;
    }
    body += `<circle cx="${X(0).toFixed(1)}" cy="${Y(0).toFixed(1)}" r="2.2" fill="#1c1917" stroke="none"/>`;
    for (const p of pts) {
      const rad = (p.deg * Math.PI) / 180;
      body += text(X(p.x + Math.cos(rad) * 19), Y(p.y + Math.sin(rad) * 19) + 4, p.name, "fig-lab", true);
    }
    body += text(X(ox), Y(oy) + 4, fig.center || "O", "fig-lab", true);
    (fig.marks || []).forEach((mk, i) => {
      const a = pts.find((p) => p.name === mk.from);
      const b = pts.find((p) => p.name === mk.to);
      if (!a || !b) return;
      const diff = Math.abs(normDeg(a.deg - b.deg));
      const minor = diff > 180 ? 360 - diff : diff;
      const rpx = 28 + (i % 3) * 11;
      if (mk.right || (minor > 84 && minor < 96 && mk.label === "90°")) {
        const s = 17;
        const a1 = (a.deg * Math.PI) / 180;
        const a2 = (b.deg * Math.PI) / 180;
        const p1 = [Math.cos(a1) * s, Math.sin(a1) * s];
        const p2 = [Math.cos(a2) * s, Math.sin(a2) * s];
        const c = [p1[0] + p2[0], p1[1] + p2[1]];
        body += `<path d="M ${X(p1[0]).toFixed(1)} ${Y(p1[1]).toFixed(1)} L ${X(c[0]).toFixed(1)} ${Y(c[1]).toFixed(1)} L ${X(p2[0]).toFixed(1)} ${Y(p2[1]).toFixed(1)}" fill="none" stroke="#1c1917" stroke-width="1.3"/>`;
        return;
      }
      let start = a.deg;
      let sweep = normDeg(b.deg - a.deg);
      if (sweep > 180) {
        start = b.deg;
        sweep = normDeg(a.deg - b.deg);
      }
      const sRad = (start * Math.PI) / 180;
      const eRad = ((start + sweep) * Math.PI) / 180;
      const p0 = [Math.cos(sRad) * rpx, Math.sin(sRad) * rpx];
      const p1 = [Math.cos(eRad) * rpx, Math.sin(eRad) * rpx];
      body += `<path d="M ${X(p0[0]).toFixed(1)} ${Y(p0[1]).toFixed(1)} A ${rpx} ${rpx} 0 0 1 ${X(p1[0]).toFixed(1)} ${Y(p1[1]).toFixed(1)}" fill="none" stroke="#1c1917" stroke-width="1.15"/>`;
      if (mk.label) {
        const m = ((start + sweep / 2) * Math.PI) / 180;
        const lr = rpx + 13;
        body += text(X(Math.cos(m) * lr), Y(Math.sin(m) * lr) + 4, mk.label, "fig-ang", false);
      }
    });
    return svgEl(W, H, body);
  }

  function niceCaption(cap) {
    const t = String(cap || "").trim();
    if (!t || /^如\s*图/.test(t) || /^图\s*\d*$/.test(t)) return "";
    return t;
  }

  function renderFigure(fig, style) {
    if (!fig) return "";
    let inner = "";
    const kind = fig.kind || (fig.svg ? "svg" : fig.src ? "image" : "");
    if (kind === "geometry") inner = renderGeometry(fig, style);
    else if (kind === "rays") inner = renderRays(fig);
    else if (kind === "coord") inner = renderCoord(fig);
    else if (kind === "numberline") inner = renderNumberline(fig);
    else if (kind === "bar") inner = renderBar(fig);
    else if (kind === "pie") inner = renderPie(fig);
    else if (kind === "svg") inner = sanitizeSvg(fig.svg);
    else if (kind === "image" && fig.src) inner = `<img class="fig-img" src="${esc(fig.src)}" alt="${esc(fig.caption || "配图")}"/>`;
    else if (fig.svg) inner = sanitizeSvg(fig.svg);
    else return "";
    if(kind!=="image")inner=sanitizeSvg(inner);
    if (!inner) return "";
    const cap = niceCaption(fig.caption) ? `<div class="fig-cap">${esc(niceCaption(fig.caption))}</div>` : "";
    return `<figure class="q-fig kind-${kind}">${inner}${cap}</figure>`;
  }

  function trianglePair(stem) {
    const pair = stem.match(/^(?:如图[，,：:]?)?[△▲]([A-Z]{3})(?:≌|≅|\\cong)[△▲]([A-Z]{3})[，,]?(?:若|已知|且)/);
    if (!pair || new Set(pair[1] + pair[2]).size !== 6) return null;
    const names = pair[1] + pair[2];
    const tail = stem.slice(pair[0].length);
    const marks = [...tail.matchAll(/∠([A-Z])=(\d+(?:\.\d+)?)°/g)];
    const sides = [...tail.matchAll(/([A-Z]{2})=(\d+(?:\.\d+)?)(?:cm|mm|m|厘米|毫米|米)?(?=[，,；;。]|$)/g)];
    let points;
    if (marks.length === 2 && /^∠[A-Z]=[\d.]+°[，,]∠[A-Z]=[\d.]+°[，,](?:则|求)∠[A-Z]/.test(tail)) {
      const angles = [null, null, null];
      for (const [, name, value] of marks) {
        const i = names.indexOf(name) % 3;
        if (i < 0 || angles[i] !== null) return null;
        angles[i] = Number(value);
      }
      const missing = angles.indexOf(null);
      angles[missing] = 180 - angles.reduce((sum, value) => sum + value, 0);
      if (angles.some(value => value <= 0 || value >= 180)) return null;
      const [a, , c] = angles.map(value => value * Math.PI / 180);
      const ac = 6;
      const ab = ac * Math.sin(c) / Math.sin(angles[1] * Math.PI / 180);
      points = [[0, 0], [ab * Math.cos(a), ab * Math.sin(a)], [ac, 0]];
    } else if (sides.length === 3 && /[，,](?:则|求)[A-Z]{2}/.test(tail)) {
      const given = new Map(sides.map(([, side, value]) => [[...side].sort().join(""), Number(value)]));
      const length = (i, j) => given.get([names[i], names[j]].sort().join(""));
      const [ab, bc, ac] = [length(0, 1), length(1, 2), length(0, 2)];
      if (![ab, bc, ac].every(Number.isFinite) || 2 * Math.max(ab, bc, ac) >= ab + bc + ac) return null;
      const bx = (ab ** 2 + ac ** 2 - bc ** 2) / (2 * ac);
      points = [[0, 0], [bx, Math.sqrt(ab ** 2 - bx ** 2)], [ac, 0]];
    } else return null;

    const xs = points.map(point => point[0]);
    const shift = Math.max(...xs) - Math.min(...xs) + points[2][0] * .46;
    const elements = [];
    for (let triangle = 0; triangle < 2; triangle++) {
      const vertices = points.map(([x, y]) => [x + triangle * shift, y]);
      elements.push({type: "polygon", points: vertices, fill: "none"});
      vertices.forEach((at, i) => elements.push({
        type: "point", at, label: names[triangle * 3 + i], dir: ["sw", "n", "se"][i],
      }));
      for (const [, name, value] of marks) {
        const i = names.slice(triangle * 3, triangle * 3 + 3).indexOf(name);
        if (i >= 0) elements.push({type:"angle", at:vertices[i], from:vertices[(i+1)%3],
          to:vertices[(i+2)%3], r:points[2][0] * .16, label:value + "°"});
      }
    }
    return {kind:"geometry", width:370, height:155, elements};
  }

  function angleAt(vertex, from, to) {
    const a = [from[0] - vertex[0], from[1] - vertex[1]];
    const b = [to[0] - vertex[0], to[1] - vertex[1]];
    return Math.atan2(Math.abs(a[0] * b[1] - a[1] * b[0]), a[0] * b[0] + a[1] * b[1]) * 180 / Math.PI;
  }

  function figureMatchesStem(fig, stem) {
    if (fig.kind !== "geometry" && fig.kind !== "rays") return true;
    const names = new Set();
    const vertices = new Map();
    if (fig.kind === "geometry") {
      for (const e of fig.elements || []) {
        if (e.type === "point" && e.label) {
          const label = String(e.label).trim();
          names.add(label);
          if (Array.isArray(e.at)) vertices.set(label, e.at);
        }
        if (e.type === "label" && /^[A-Z]$/.test(e.text)) names.add(e.text);
      }
    } else {
      if (fig.center) names.add(fig.center);
      for (const name of fig.baseline || []) names.add(name);
      for (const ray of fig.rays || []) names.add(ray.name || ray.to || ray.label);
    }
    const references = stem.matchAll(/(?:[△▲][A-Z]{3}|[∠⊙][A-Z]{1,3}|点[A-Z]|[A-Z]{2}(?=[=⊥∥]|平分|是|在)|[=⊥∥][A-Z]{2})/g);
    for (const [reference] of references) {
      if ([...(reference.match(/[A-Z]/g) || [])].some(name => !names.has(name))) return false;
    }
    if (fig.kind !== "geometry") return true;
    const triangles = [...new Set([...stem.matchAll(/[△▲]([A-Z]{3})/g)].map(match => match[1]))];
    const pair = stem.match(/[△▲]([A-Z]{3})(?:≌|≅|\\cong)[△▲]([A-Z]{3})/);
    if (pair) {
      const edges = new Set();
      const key = (a, b) => [a.join(","), b.join(",")].sort().join("|");
      for (const item of fig.elements || []) {
        if (item.type === "polygon") {
          item.points?.forEach((point, i, points) => edges.add(key(point, points[(i+1)%points.length])));
        }
        if (item.type === "line" && item.from && item.to) edges.add(key(item.from, item.to));
      }
      for (const triangle of pair.slice(1)) {
        const points = [...triangle].map(name => vertices.get(name));
        if (points.some(point => !point) || points.some((at, i) => !edges.has(key(at, points[(i+1)%3])))) return false;
      }
    }
    for (const [, name, degrees] of stem.matchAll(/∠([A-Z]{3}|[A-Z])=(\d+(?:\.\d+)?)°/g)) {
      let labels = [...name];
      if (labels.length === 1) {
        const [other] = triangles.filter(triangle => triangle.includes(name));
        if (!other || triangles.filter(triangle => triangle.includes(name)).length !== 1) continue;
        const ends = [...other].filter(label => label !== name);
        labels = [ends[0], name, ends[1]];
      }
      const [a, vertex, b] = labels.map(label => vertices.get(label));
      if (a && vertex && b && Math.abs(angleAt(vertex, a, b) - Number(degrees)) > 2) return false;
    }
    return true;
  }

  function renderQuestionFigure(question, style) {
    const original = String(question.stem || "");
    const stem = original.replace(/\\triangle\b/g, "△").replace(/\\angle\b/g, "∠")
      .replace(/\\circ\b/g, "°").replace(/[\s{}$^]/g, "").replace(/＝/g, "=");
    const needsFigure = /如图|下图|图中|见图|图所示|根据图|观察图/.test(original);
    if (!question.figure && !needsFigure) return "";
    const figure = trianglePair(stem) || question.figure;
    if (figure && (figure !== question.figure || figureMatchesStem(figure, stem))) {
      const rendered = renderFigure(figure, style);
      if (rendered) return rendered;
    }
    return needsFigure || question.figure
      ? '<div class="q-fig-notice">此题缺少与题干相符的配图，请核对卷稿。</div>' : "";
  }

  global.QJFigures = { renderFigure, renderQuestionFigure, sanitizeSvg, resolveRays };
})(typeof window !== "undefined" ? window : globalThis);
