"""Prompts for DeepSeek exam-paper generation."""

import json

TYPE_NAMES = {
    "choice": "单选题",
    "multi": "多选题",
    "tf": "判断题",
    "fill": "填空题",
    "short": "简答题",
    "calculate": "计算题",
    "solve": "解答题 / 应用题",
    "essay": "作文 / 论述题",
    "reading": "阅读理解",
    "cloze": "完形填空",
    "experiment": "实验题",
    "drawing": "作图题",
}


SYSTEM = """你是资深命题专家与排版编辑，为中国大陆中小学及高考命题。你熟悉课程标准、教材难度梯度、常见陷阱与压轴题手法。

输出必须是一个 JSON 对象，不要 Markdown 围栏，不要解释。

## 题目质量
- 题干用语地道：如「下列说法正确的是」「如图所示」「若……则……」。
- 范围锁优先于「综合发挥」。期中、月考、阶段测验只考本册前一半已学内容；期末只考本册。禁止下册、禁止还没学的章节、禁止用高年级知识包装成本年级题。拿不准就换更早的基础题。
- 严格匹配年级与学科，不出超纲题，也不要幼稚于该学段。
- 选项干扰项要有迷惑性，避免明显错项。
- 计算题数字尽量「好算」但过程完整。
- 每题必须有标准答案与简明解析（步骤关键点，不是长篇讲义）。
- 答案与解析必须一致：数字自己验算一遍，答案和解析算出的结果必须相同，选项字母必须和解析推出的选项一致。宁可少出题，不要出一张算错的卷。
- 同一张卷内知识点不重复堆砌，由易到难。
- 数学/物理/化学涉及几何、函数、受力、电路、装置时必须配图。
- 语文阅读给完整材料；英语阅读给完整短文；完形给带空短文。
- 题干、选项、材料中的数学用 TeX：$行内$ 与 $$独立$$。

## 配图 figure（强烈鼓励）
坐标系：原点在左下，y 轴向上。用结构化 spec，不要手写原始 SVG（除非情景简笔画）。

几何：
{
  "kind": "geometry",
  "width": 320,
  "height": 240,
  "box": [0, 0, 10, 8],
  "caption": "",
  "elements": [
    {"type": "polygon", "points": [[1,1],[5,6.5],[9,1]], "fill": "#f6f1e6"},
    {"type": "point", "at": [1,1], "label": "A", "dir": "sw"},
    {"type": "point", "at": [5,6.5], "label": "B", "dir": "n"},
    {"type": "point", "at": [9,1], "label": "C", "dir": "se"},
    {"type": "equal", "a": [1,1], "b": [5,6.5], "n": 1},
    {"type": "right", "at": [1,1], "from": [9,1], "to": [5,6.5]},
    {"type": "label", "at": [5,0.45], "text": "10 cm"}
  ]
}

elements.type 可选：
- line {from,to,dash?}
- polygon {points, fill?}
- circle {c:[x,y], r, fill?}
- arc {c, r, a0, a1} 角度为度，从 x 轴正方向逆时针
- point {at, label, dir: n/s/e/w/ne/nw/se/sw}
- angle {at, from, to, label?, r?}
- right {at, from, to} 直角记号
- equal {a, b, n} 边上的等长刻痕，n=1/2/3
- label {at, text}
- arrow {from, to}

共顶点的角、射线、直线（角平分线、垂直、邻补角）禁止手填坐标，必须用 rays，角度由程序计算：
{
  "kind": "rays",
  "rays": [
    {"name": "A", "deg": 180},
    {"name": "B", "deg": 0},
    {"name": "C", "from": "A", "turn": 50, "side": "up"},
    {"name": "D", "bisect": ["B", "C"]},
    {"name": "E", "perp": "D", "side": "up"}
  ],
  "marks": [
    {"from": "A", "to": "C", "label": "50°"},
    {"from": "E", "to": "D", "right": true}
  ]
}
约定：deg 是数学角，0 向右、90 向上、180 向左。
from+turn+side：从已有射线转过 turn 度，side=up 转到上半平面。
bisect：两边夹角里不超过 180° 的平分线。
perp：与某射线垂直。
题干里的每个点都要有 name，不要多画题干没有的射线。caption 留空，不要写「如图」。
例：点 O 在直线 AB 上，∠AOC=50°，OD 平分 ∠BOC，OE⊥OD → 就是上面这组 rays。

函数坐标系：
{
  "kind": "coord",
  "width": 340,
  "height": 260,
  "xmin": -2, "xmax": 6, "ymin": -2, "ymax": 8,
  "grid": true,
  "functions": [{"expr": "0.5*(x-1)**2+1", "domain": [-1, 5]}],
  "points": [{"x": 1, "y": 1, "label": "A"}],
  "segments": [[[0,0],[4,0]]],
  "caption": ""
}
expr 只允许数字、x、+ - * / ** () 以及 sin cos tan abs sqrt log exp。

数轴：
{"kind": "numberline", "min": -4, "max": 4, "ticks": 1, "points": [{"x": -1, "label": "A"}, {"x": 2, "label": "B"}]}

统计：
{"kind": "bar", "categories": ["甲","乙","丙"], "values": [12, 20, 9], "unit": "人"}
{"kind": "pie", "slices": [{"label": "A", "value": 30}, {"label": "B", "value": 70}]}

小学情景简笔（仅小学，其余一律禁止手写 SVG）：
{"kind": "svg", "svg": "<svg viewBox='0 0 260 160' xmlns='http://www.w3.org/2000/svg'>...</svg>", "caption": ""}

程序框图、流程图、电路、实验装置等，如果你不能肯定画得准确，就不要配图，把流程或装置用文字描述清楚即可；需要图时优先用 geometry/coord/bar/pie 结构化 spec，禁止手写 SVG（小学卡通简笔除外）。

## 题目对象
{
  "id": "s1q1",
  "type": "choice|multi|tf|fill|short|calculate|solve|essay|reading|cloze|experiment|drawing",
  "stem": "题干，填空用 ______ 表示空白",
  "options": ["选项文本，不要带 A. 前缀"],
  "blanks": 1,
  "score": 4,
  "difficulty": "easy|medium|hard",
  "knowledge": "知识点",
  "answer": "C 或 填空答案 或 多选 BD",
  "analysis": "解析",
  "figure": null,
  "answer_space": 0,
  "passage": "",
  "passage_title": "",
  "questions": [],
  "requirements": [],
  "grid": null
}

- choice/multi: options 长度 4（小学可 3）。单选 answer 为 A/B/C/D。
- tf: options 可省略，answer 为 「正确」或「错误」。
- fill: stem 含 ______，answer 用分号分隔多空。
- reading: passage 必填，段落之间空一行，不要挤成一段。passage_title 篇名，passage_author 作者，passage_source 出处可空。questions 为子题（choice 或 short），每问单独写 stem。
- cloze: passage 用 {{1}} {{2}} 标记空，questions 为每空的 choice。
- essay: requirements 数组，grid 如 {"chars": 600}。
- solve/calculate/experiment/drawing: answer_space 只是预留空白的行数（4-10）。数学、物理、化学、生物不要横线，横线只用于语文、英语、历史、地理的文字作答。choice/fill/tf 的 answer_space 必须为 0。
- 子题也要 score/answer/analysis。

## 大题
{
  "title": "一、选择题",
  "instruction": "本大题共 8 小题，每小题 4 分，共 32 分。在每小题给出的四个选项中，只有一项符合题目要求。",
  "type": "choice",
  "questions": []
}
"""


def _mode_hint(mode: str) -> str:
    if mode == "fast":
        return "极速模式：题干短，解析一句话，只在几何/函数/实验题配图，figure 尽量小。"
    if mode == "fine":
        return "精细模式：解析含关键步骤与易错点；凡有助于理解的题都配图；压轴题有层次。"
    return "标准模式：该配图的题必须配图；解析简洁完整。"


def _figure_hint(figures: str, style: str, grade: str) -> str:
    style_map = {
        "line": "线条几何风，浅填色，适合中考高考。",
        "sketch": "略松的手绘感，线宽 1.6，圆角。",
        "cartoon": "小学卡通：圆润描边、浅彩填充（#ffe7c2/#cde7df/#d9e6f2），可配简单表情/实物。",
    }
    s = style_map.get(style, style_map["line"])
    if figures == "off":
        return "不要配图，figure 一律为 null。"
    if figures == "rich":
        return f"尽量多配图。风格：{s}"
    return f"按需配图（几何、函数、实验、统计、看图题必须有图）。风格：{s} 学段：{grade}"


# 人教版常见册次。期中≈前一半，期末=本册，模拟=已学全部但不到下一学段。
_SCOPE = {
    ("j1", "数学"): (
        "七年级上册期中只考：有理数（概念、数轴、相反数、绝对值、大小比较、加减乘除乘方、混合运算）、整式的加减（单项式、多项式、系数次数、同类项、合并同类项、去括号、化简求值、简单的找规律）。禁止：一元一次方程（含解方程、列方程解应用题）、分段计费/分段优惠、销售利润、行程、工程、配套、盈亏等方程模型应用题、程序框图/流程图、几何图形初步（角、线、射线、角平分线、余角补角）、以及七年级下册全部。",
        "七年级上册：有理数、整式的加减、一元一次方程、几何图形初步。禁止七年级下册及以后。",
    ),
    ("j2", "数学"): (
        "八年级上册期中只考三角形、全等三角形。禁止轴对称后的内容、整式乘法与因式分解、分式，禁止八年级下册的二次根式、勾股定理、平行四边形、一次函数。",
        "八年级上册全部。禁止勾股定理、平行四边形、一次函数、二次根式（这些在下册）。",
    ),
    ("j3", "数学"): (
        "九年级上册期中只考一元二次方程、二次函数的基础。禁止旋转、圆、概率初步，禁止九年级下册的相似、锐角三角函数、反比例函数。",
        "九年级上册：一元二次方程、二次函数、旋转、圆、概率初步。禁止下册相似与三角函数。",
    ),
    ("s1", "数学"): (
        "高一上学期期中只考集合、不等式、函数概念与性质。禁止三角函数、平面向量、以及高二的立体几何、解析几何、导数。",
        "高一上：集合、不等式、函数、三角函数。禁止导数、圆锥曲线、计数概率（若尚未分册学到）。",
    ),
    ("s2", "数学"): (
        "高二期中只考已学的立体几何或解析几何前半，不要提前考导数综合压轴。",
        "高二已学内容。禁止用高考压轴里才出现的技巧，禁止未学选修。",
    ),
    ("s3", "数学"): (
        "高三期中复习不超过已讲专题。不要把未复习的圆锥曲线最值、导数综合硬塞进来。",
        "高考范围内已复习专题。",
    ),
    ("j2", "物理"): (
        "八年级上册期中只考机械运动、声现象。禁止光现象、透镜、质量与密度，禁止八年级下册的力、运动和力、压强、浮力。",
        "八年级上册。禁止力学（在下册）。",
    ),
    ("j3", "物理"): (
        "九年级期中只考内能、内能的利用、电流和电路。禁止欧姆定律之后的电功率综合，禁止电与磁。",
        "九年级全一册已学章节。禁止高中电磁。",
    ),
    ("j3", "化学"): (
        "九年级上册期中只考走进化学、空气、物质构成的奥秘。禁止水、化学方程式的综合计算、碳和碳的氧化物、燃料，禁止下册的金属、酸、碱、盐。",
        "九年级上册。禁止金属活动性、酸碱盐综合。",
    ),
    ("s1", "物理"): (
        "高一上期中只考运动的描述、匀变速直线运动。禁止相互作用、牛顿定律，禁止曲线运动、万有引力、机械能。",
        "高一上：运动学、相互作用、牛顿运动定律。禁止圆周运动、万有引力、机械能（若在下册）。",
    ),
    ("s1", "化学"): (
        "高一上期中只考物质分类、离子反应、氧化还原的初步。禁止元素周期律之后、以及化学反应与能量的综合计算。",
        "高一必修第一册已学章节。禁止未学的有机化学。",
    ),
}


def _grade_key(grade: str) -> str:
    g = grade or ""
    pairs = (
        ("小学一年级", "p1"), ("小学二年级", "p2"), ("小学三年级", "p3"),
        ("小学四年级", "p4"), ("小学五年级", "p5"), ("小学六年级", "p6"),
        ("初中一年级", "j1"), ("七年级", "j1"),
        ("初中二年级", "j2"), ("八年级", "j2"),
        ("初中三年级", "j3"), ("九年级", "j3"),
        ("高中一年级", "s1"), ("高一", "s1"),
        ("高中二年级", "s2"), ("高二", "s2"),
        ("高中三年级", "s3"), ("高三", "s3"),
    )
    for name, key in pairs:
        if name in g:
            return key
    return ""


def _exam_kind(cfg: dict) -> str:
    text = " ".join(str(cfg.get(k) or "") for k in ("exam_name", "title", "extra_requirements"))
    if any(k in text for k in ("单元", "课时", "周测", "随堂")):
        return "unit"
    if any(k in text for k in ("期中", "月考", "阶段")):
        return "mid"
    if any(k in text for k in ("中考", "高考", "一模", "二模", "三模", "模拟")):
        return "mock"
    if "期末" in text:
        return "final"
    return "term"


def scope_rule(cfg: dict) -> str:
    kind = _exam_kind(cfg)
    grade = cfg.get("grade") or ""
    subject = cfg.get("subject") or ""
    key = _grade_key(grade)
    band = _SCOPE.get((key, subject))
    if kind == "unit":
        head = "这是单元/课时测验。只考用户点名的那一单元。没点名就考本册最前一个单元。禁止用后面单元的知识，哪怕它「不难」。"
    elif kind == "mid":
        head = "这是期中（或月考、阶段测验）。只考本学期教材前一半，大约前三个单元。后一半、下册、竞赛结论一律禁止。"
        if band:
            head += band[0]
    elif kind == "final":
        head = "这是期末。可以考本册全部，但禁止下一册、禁止更高年级。"
        if band:
            head += band[1]
    elif kind == "mock":
        head = "这是升学模拟。可以综合本学段已经学完的内容，仍然禁止下一学段（初中模拟不要高中知识，小学不要初中）。"
        if band:
            head += "本年级本册边界：" + band[1]
    else:
        head = "未标明期中或期末时，按「本学期已学」出题，默认不超过本册前一半，以免超纲。"
        if band:
            head += band[0]
    if key.startswith("p"):
        head += " 小学按人教版该册前一半单元，计算不超已学运算，应用题情景用已学数量关系。不要出现分数/比例/方程，除非该册前一半已经学过。"
    if subject in ("语文", "英语", "历史", "地理", "道德与法治", "政治"):
        head += " 阅读和积累只用课本前一半已学课文、已学语法或已学专题。不要默写还没教的篇目，不要用下册文言文字词。"
    if subject in ("数学", "物理", "化学", "生物", "科学") and kind in ("unit", "mid"):
        head += " 应用题只用已学章节的模型，不要出现方程模型、分段计费、销售利润、行程、工程、程序框图等还没学的内容。"
    return "【范围锁】" + head + " 用户额外要求里点了名的章节可以考，但不要自行再往后面加。拿不准是否已学，就换更早的题。"


def figure_review_prompt(cfg: dict, questions: list) -> str:
    block = json.dumps(questions, ensure_ascii=False)
    return f"""你是审图编辑。配图已经按规格画过一次，请对照题干检查实际图形是否成立。
只输出 JSON：{{"fixes":[{{"id":"题号","ok":true,"figure":{{...}}}}]}}

必须改图（ok=false，并给出新 figure）的情况：
- 题干里的点没有全部标出，或多了题干没有的射线
- 角度、垂直、角平分线、平行、等长和题干矛盾
- 说了「点在直线上」但三点不共线
- 这是共顶点的角或射线，却用了手填坐标的 geometry

共顶点问题一律改成 kind=rays（不要自己算坐标）：
{{"kind":"rays","rays":[{{"name":"A","deg":180}},{{"name":"B","deg":0}},{{"name":"C","from":"A","turn":50,"side":"up"}},{{"name":"D","bisect":["B","C"]}},{{"name":"E","perp":"D","side":"up"}}],"marks":[{{"from":"A","to":"C","label":"50°"}},{{"from":"E","to":"D","right":true}}]}}
deg：0 向右，90 向上，180 向左。side=up 转到上方。bisect 平分较小夹角。perp 垂直。
caption 用空字符串，不要写「如图」。
图本身正确则 ok=true，figure 原样返回。没有图且题干也不依赖图，则 figure 为 null。

年级学科：{cfg.get('grade')} {cfg.get('subject')}
题目列表：
{block}
"""


def answer_review_prompt(cfg: dict, questions: list) -> str:
    block = json.dumps(questions, ensure_ascii=False)
    return f"""你是独立命题审校员，先独立求解再核对原答案。逐个选项求值，单选必须恰好一个正确选项，检查等价选项、漏条件、无解、超纲及所有子题。
允许修正题干、选项、材料、配图、子题、答案和解析，使整题成立；不要只在解析里议论原题错误而保留错题。
发现问题时给出完整可用的修正版，然后重新验算。解析只能包含最终正确推导，禁止出现“原题有误”“建议删除”“保留原答案”等自我争论。
无法确定修正题正确时 valid=false，禁止猜测放行。每题必须返回一条审校结果。
只输出 JSON：{{"fixes":[{{"id":"原题id","valid":true,"stem":"最终题干","options":[],"answer":"最终答案","analysis":"最终解析"}}]}}
其他被修改的字段一并返回；保留原题类型、分值、知识点和子题数量。题干完整保留，不要截断。
年级学科：{cfg.get('grade')} {cfg.get('subject')}
题目：{block}
"""


def outline_prompt(cfg: dict) -> str:
    sections = cfg.get("sections") or []
    lines = []
    for i, s in enumerate(sections, 1):
        t = TYPE_NAMES.get(s.get("type", ""), s.get("type", ""))
        title = s.get("title") or f"{t}"
        kn = s.get("knowledge") or "按课标综合"
        lines.append(
            f"{i}. {title}  type={s.get('type')}  题量={s.get('count')}  "
            f"每题{s.get('score_each')}分  难度={s.get('difficulty','mixed')}  知识点={kn}"
        )
    extra = cfg.get("extra_requirements") or "无"
    school = cfg.get("school") or "（未指定学校，拟一个得体的中小学名称）"
    exam_name = cfg.get("exam_name") or "（根据年级学科拟一个考试名称，如期中考试）"
    return f"""根据命题蓝图，输出试卷元信息 JSON：
{{
  "meta": {{
    "school": "{school if cfg.get('school') else '将由你拟定'}",
    "title": "试卷主标题（学校可放在 school 字段）",
    "subtitle": "学科 + 考试名称，如 数学 期中考试",
    "subject": "{cfg.get('subject','')}",
    "grade": "{cfg.get('grade','')}",
    "term": "{cfg.get('term','')}",
    "duration": {int(cfg.get('duration') or 90)},
    "total_score": {int(cfg.get('total_score') or 0)},
    "year": "2026",
    "instructions": ["注意事项 3-5 条，符合该学段，简洁"]
  }}
}}

蓝图：
- 学校：{school}
- 年级：{cfg.get('grade')}
- 学科：{cfg.get('subject')}
- 考试：{exam_name}
- 时长：{cfg.get('duration')} 分钟
- 学期：{cfg.get('term') or '未指定'}
- 用户指定标题：{cfg.get('title') or '未指定，请拟定'}
- 额外要求：{extra}

大题结构：
{chr(10).join(lines) or '（未指定，请按该学段该学科常规考试结构设计）'}

规则：
- 若用户已指定 school/title，尽量尊重，只做轻微润色。
- instructions 不要写「用 2B 铅笔」除非是有答题卡的中考高考风。
- 只输出 meta 对象包在 {{"meta": ...}} 里。
"""


def section_prompt(cfg: dict, meta: dict, spec: dict, index: int, prior_stems: list[str]) -> str:
    t = spec.get("type") or "choice"
    count = int(spec.get("count") or 4)
    score_each = spec.get("score_each")
    title = spec.get("title") or f"{TYPE_NAMES.get(t, t)}"
    kn = spec.get("knowledge") or ""
    diff = spec.get("difficulty") or "mixed"
    extra = cfg.get("extra_requirements") or "无"
    avoid = "；".join(prior_stems[:40]) if prior_stems else "无"
    fig = spec.get("with_figures")
    fig_override = ""
    if fig is True:
        fig_override = "本大题尽量每题配图。"
    elif fig is False:
        fig_override = "本大题不要配图。"
    type_note = ""
    if t == "reading":
        type_note = "阅读：passage 分段（段落之间空一行），写 passage_title 和 passage_author。现代文正式整卷小学 350–600 字、初中 600–1000 字、高中 800–1500 字；专项练习按知识点灵活缩短。古诗文按完整篇章提供，不受现代文字数限制。现代文材料优先原创，署名“原创”；不要复现仍在版权期的出版文章全文。子题紧扣这段材料。必须在 questions 数组中提供 3–5 道子题，每道子题有 stem、type、answer、analysis、score；子题分值之和等于本阅读题分值，不得只给材料或空子题。"
    if t in ("solve", "calculate", "experiment", "drawing") and cfg.get("subject") in ("数学", "物理", "化学", "生物", "科学"):
        type_note += " 理科解答只留空白，不要在题干里要求「把答案写在横线上」。answer_space 是空白行数，不是横线条数。"
    type_note += " 每道题的 answer 和 analysis 结果必须一致，数字要验算。"

    return f"""请命制试卷的第 {index + 1} 大题，输出 JSON：
{{
  "title": "{title}",
  "instruction": "本大题共 x 小题，……（写清题量与分值）",
  "type": "{t}",
  "questions": [ 题目对象, ... ]
}}

试卷：{meta.get('school','')} {meta.get('subtitle') or meta.get('title')} · {cfg.get('grade')} {cfg.get('subject')}
出卷用途：{'正式整卷' if cfg.get('paper_scope') == 'full' else '专项练习'}
本大题：{title}  类型 {TYPE_NAMES.get(t,t)} ({t})
题量：{count}（必须正好 {count} 题）
每题分值：{score_each if score_each is not None else '按题型合理分配，压轴可递增'}
难度：{diff}（mixed 则由易到难）
指定知识点：{kn or '本学段本学科常见综合'}
{scope_rule(cfg)}
额外要求：{extra}
{type_note}
{_mode_hint(cfg.get('mode') or 'standard')}
{_figure_hint(cfg.get('figures') or 'auto', cfg.get('figure_style') or 'line', cfg.get('grade') or '')}
{fig_override}

避免与已有题干重复：{avoid}

编号 id 用 s{index + 1}q1 这种。题号不必写进 stem。
只输出这一大题的 JSON 对象。
"""


def question_prompt(cfg: dict, section: dict, question: dict, instruction: str) -> str:
    return f"""重写/新出一道题，替换原题。输出单个题目 JSON 对象（不要包一层）。
年级学科：{cfg.get('grade')} {cfg.get('subject')}
{scope_rule(cfg)}
大题：{section.get('title')} 类型 {section.get('type')}
原题：{question}
用户要求：{instruction or '保持知识点，换一套数字/材料，难度相当。'}
{_figure_hint(cfg.get('figures') or 'auto', cfg.get('figure_style') or 'line', cfg.get('grade') or '')}
{_mode_hint(cfg.get('mode') or 'standard')}
"""


def figure_prompt(cfg: dict, question: dict) -> str:
    return f"""为下面这道题设计配图，只输出 JSON：{{"figure": {{...}}}}。
年级学科：{cfg.get('grade')} {cfg.get('subject')}
风格：{_figure_hint('rich', cfg.get('figure_style') or 'line', cfg.get('grade') or '')}
共顶点的角、射线必须用 kind=rays，不要手填坐标。caption 留空。
题目：{question.get('stem')}
选项：{question.get('options')}
如果确实无法配图，输出 {{"figure": null}}。
"""
