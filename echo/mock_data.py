"""
Echo - 模拟数据层
模拟：实时 transcript 流、Concept Timeline、Break Point 分析、micro lesson、回响页。
真实接入时，把这些函数替换成 ASR + LLM 调用即可。
"""
import random
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Concept:
    timecode: str          # "18:39"
    topic: str
    concepts: List[str]
    prerequisites: List[str]
    summary: str
    status: str = "ok"     # ok / warn / lost / now


@dataclass
class BreakPoint:
    breakpoint_tc: str
    concept: str
    missing: str
    reason: str
    micro_lesson: str
    note: str = ""         # 时间轴上的短备注
    known: str = ""        # 三段式补课 ①你已经知道什么
    step: str = ""         # ②中间漏的那一步
    now: str = ""          # ③所以现在能听懂什么
    fixed: bool = False    # 学生点了「补上了」
    self_review: bool = False  # 学生点了「我自己看看」，没用 AI 补
    lost_at: float = 0.0     # 点「我掉队了」那一刻的墙钟 epoch 秒
    resolved_at: float = 0.0 # 点「补上了」/「我自己看看」那一刻；0 = 未解决


@dataclass
class EchoSkill:
    name: str
    mastery: float         # 0~1
    status: str            # ok 已跟上 / fixed 掉队过但已补上 / review 待回看


# ---------- 一节示例课：概率论 / 贝叶斯 ----------
SAMPLE_TRANSCRIPT = [
    ("18:30", "好，我们今天讲贝叶斯统计。先从条件概率开始。"),
    ("18:32", "条件概率 P(A|B) 表示在 B 已经发生的情况下 A 发生的概率。"),
    ("18:34", "它等于 P(A 交 B) 除以 P(B)，这是定义。"),
    ("18:36", "大家把这个定义记下来，后面会反复用到。"),
    ("18:37", "好，现在我们直接看贝叶斯公式。"),
    ("18:39", "P(A|B) = P(B|A) * P(A) / P(B)，这就是贝叶斯公式。"),
    ("18:40", "它的核心思想是用观测到的结果 B 反过来更新我们对 A 的信念。"),
    ("18:42", "下面我们看后验概率，也就是更新后的 P(A|B)。"),
]

# ---------- 自检脚本用的示例课讲稿（(秒, 讲稿)，无时间码） ----------
# 老师在 160s 处直接甩出贝叶斯公式、未推导 —— 预埋了「知识断点」。
SAMPLE_LESSON = [
    (5, "好，同学们，我们今天讲贝叶斯统计。在讲贝叶斯之前，先回顾一下条件概率。"),
    (20, "条件概率 P(A|B)，读作在 B 发生的条件下 A 发生的概率。"),
    (38, "比如掷一个骰子，B 是掷出偶数，A 是掷出 6，那 P(A|B) 就是三分之一。"),
    (55, "它的定义是 P(A|B) 等于 P(A 交 B) 除以 P(B)，前提是 P(B) 大于零。"),
    (75, "这个定义大家一定要记住，后面整节课都建立在它上面。"),
    (92, "直观理解就是，我们把样本空间缩小到 B 里面，再看 A 占了多大比例。"),
    (115, "再举个例子，一副扑克牌，已知抽到的是红色，那它是红桃的概率就是二分之一，因为样本空间缩小成了 26 张红牌。"),
    (150, "好，有了这些，我们现在直接来看贝叶斯公式。"),
    (160, "P(A|B) 等于 P(B|A) 乘 P(A) 再除以 P(B)，这就是贝叶斯公式，大家记下来。"),
    (185, "贝叶斯公式的核心思想，是用观测到的结果 B，反过来更新我们对原因 A 的判断。"),
    (200, "这里 P(A) 叫先验概率，就是在看到证据之前我们对 A 的信念。"),
    (216, "P(B|A) 叫似然，表示如果 A 成立，观察到 B 的可能性有多大。"),
    (232, "而算出来的 P(A|B) 就是后验概率，也就是看到证据之后更新的信念。"),
    (250, "我们看个例子，某种疾病发病率是千分之一，检测准确率是百分之九十九。"),
    (268, "如果一个人检测呈阳性，他真正患病的概率是多少？很多人会说百分之九十九。"),
    (285, "但用贝叶斯公式算，P(患病|阳性) 只有大约百分之九左右。"),
    (302, "这就是因为先验概率千分之一太小了，大部分阳性其实是误报。"),
    (320, "所以后验概率不仅取决于检测有多准，也取决于先验有多大，这一点非常反直觉。"),
]

SAMPLE_CONCEPTS = [
    Concept("18:30", "条件概率", ["条件概率", "联合概率"], ["概率公理"],
            "老师引入条件概率概念，给出定义 P(A|B)=P(A∩B)/P(B)", "ok"),
    Concept("18:34", "条件概率定义", ["P(A|B)", "P(A∩B)", "P(B)"], ["条件概率"],
            "老师强调条件概率定义，要求记录", "ok"),
    Concept("18:37", "贝叶斯公式", ["贝叶斯公式", "先验", "后验"], ["条件概率"],
            "老师直接给出贝叶斯公式，未推导", "warn"),
    Concept("18:42", "后验概率", ["后验概率", "信念更新"], ["贝叶斯公式"],
            "老师解释后验概率是更新后的信念", "now"),
]

SAMPLE_BREAKPOINT = BreakPoint(
    breakpoint_tc="18:39",
    concept="贝叶斯公式",
    missing="从条件概率定义到贝叶斯公式的变换",
    reason="老师直接使用公式 P(A|B)=P(B|A)P(A)/P(B)，没有解释如何从条件概率定义推导得到。",
    micro_lesson=(
        "其实贝叶斯公式就是条件概率定义的一个变形。\n\n"
        "第一步：由条件概率定义，P(A|B) = P(A∩B) / P(B)。\n"
        "第二步：同样，P(B|A) = P(A∩B) / P(A)，所以 P(A∩B) = P(B|A)·P(A)。\n"
        "第三步：把第二步的 P(A∩B) 代回第一步，就得到\n"
        "         P(A|B) = P(B|A)·P(A) / P(B)。\n\n"
        "这就是贝叶斯公式。它只是把「A 交 B」用两种方式表示了一下。"
    ),
    known="条件概率 P(A|B) = P(A∩B) / P(B)",
    step=("同理 P(B|A) = P(A∩B) / P(A)，所以 P(A∩B) = P(B|A)·P(A)\n"
          "把它代回 P(A|B) 的分子：P(A|B) = P(B|A)·P(A) / P(B)"),
    now="后验概率就是公式左边的 P(A|B)：看到结果 B 之后，对 A 更新后的信念",
)

SAMPLE_ECHO_SKILLS = [
    EchoSkill("极限", 1.00, "ok"),
    EchoSkill("导数定义", 0.85, "ok"),
    EchoSkill("瞬时变化率", 0.55, "fixed"),
    EchoSkill("链式法则", 0.15, "review"),
]

SAMPLE_REVIEW_CHAIN = ["链式法则", "复合函数", "函数复合"]


# ---------- 模拟实时 transcript 流 ----------
class MockStream:
    """每隔几秒吐出下一句 transcript，模拟实时 ASR。"""

    def __init__(self):
        self._idx = 0
        self._lines = SAMPLE_TRANSCRIPT

    @property
    def is_done(self):
        return self._idx >= len(self._lines)

    def next(self):
        if self.is_done:
            return None
        tc, text = self._lines[self._idx]
        self._idx += 1
        return tc, text

    def reset(self):
        self._idx = 0


# ---------- 模拟 AI：概念抽取 ----------
def extract_concept(transcript_window: str) -> Concept:
    """真实场景下把 transcript_window 丢给 LLM。这里按时间码查表。"""
    # 简化：根据窗口里出现的时间码返回对应 concept
    for c in SAMPLE_CONCEPTS:
        if c.timecode in transcript_window:
            return c
    return SAMPLE_CONCEPTS[-1]


# ---------- 模拟 Break Point Engine ----------
def find_breakpoint(transcript_window: str, past_concepts: List[Concept],
                    current: Concept) -> BreakPoint:
    """核心：学生点「我掉队了」后调用。真实场景拼好 prompt 给 LLM。"""
    # 演示用：返回预设断点
    return SAMPLE_BREAKPOINT


# ---------- 模拟回响页 ----------
def generate_echo(skills: List[EchoSkill]) -> List[str]:
    """根据掌握度生成复习链。演示用预设。"""
    return SAMPLE_REVIEW_CHAIN
