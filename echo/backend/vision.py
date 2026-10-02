"""
Echo - 「圈一下问 AI」（视觉问答）

学生在网课画面上用笔圈出看不懂的地方、写上批注 → 截图 + 老师最近讲的内容
→ 视觉模型读屏理解后，按学习的方式讲解，可追问。

视觉模型：优先 Qwen-VL（阿里云百炼 / DashScope，真正的读屏视觉模型）；
没配 DASHSCOPE_API_KEY 时退回 DeepSeek 的视觉模型。

不改引擎：只读 engine 的转写 / 时间轴拼上下文。回调在后台线程，UI 层自行切回主线程。
"""
import base64
import logging
import threading
from typing import Callable, List, Optional

from echo.backend import config

log = logging.getLogger("echo.vision")

SYSTEM = """你是 Echo，一个陪学生听网课的 AI 学习副驾驶，像一位耐心的助教，专门帮学生在课堂上搞懂没跟上的地方。

学生正在听课，遇到看不懂的内容，会用笔在屏幕截图上圈出来，也可能在旁边写了批注文字（比如「这里怎么来的？」「为什么除以 P(B)」）。截图里所有笔迹和文字都是学生给你的线索，先读懂它们再回答。

你会同时拿到老师最近讲的内容（语音转写，可能有同音错字，按语义理解）。

回答按「教懂」来，而不是「查字典」：
1. 先准确复述学生圈出的内容是什么（公式、定理、图表、代码……），把图上关键文字原样读出来，别凭空猜
2. 再针对学生的问题/批注，讲清楚「这一步为什么对」或「它是怎么推出来的」
3. 结合老师刚才讲的话：老师是在推导、举例、还是直接给了结论？据此判断学生卡在哪
4. 需要时给一个和课上一致的小例子，把它接回老师现在讲的内容

硬性要求：
- 只用纯文本，公式写成 P(A|B)、x^2、a/b 这种，不要 LaTeX、不要 Markdown 标题/加粗/表格
- 简洁：一般 4~8 行，每行一个要点，别复述整节课
- 如果截图里圈的内容看不清、或跟课堂无关，直接说，并告诉学生该怎么圈会更清楚"""

CONTEXT = """【课堂上下文】
老师现在在讲：{current}
最近的知识点：{timeline}
老师最近说的话：
{transcript}"""

QUICK_QUESTIONS = ["这是什么意思？", "这一步是怎么来的？", "能举个例子吗？", "和老师现在讲的有什么关系？"]


def lesson_context(engine, seconds: float = 120) -> str:
    """从引擎里取当前知识点 + 最近 N 秒转写。engine 可为 None。"""
    if engine is None:
        return ""
    try:
        with engine._lock:
            lines = list(engine.lines)
            entries = [e.concept for e in engine.entries]
        now = lines[-1].t if lines else 0
        recent = [l for l in lines if l.t >= now - seconds][-25:]
    except Exception as e:   # 引擎结构变了也不影响问答本身
        log.warning("取课堂上下文失败: %s", e)
        return ""
    if not lines and not entries:
        return ""
    return CONTEXT.format(
        current=entries[-1].topic if entries else "（还没识别出知识点）",
        timeline=" → ".join(c.topic for c in entries[-5:]) or "（暂无）",
        transcript="\n".join(f"[{l.tc}] {l.text}" for l in recent) or "（暂无）")


def _make_client():
    """按配置选视觉模型：优先 Qwen-VL，退回 DeepSeek。返回 (client, model, extra_body)。"""
    from openai import OpenAI
    if config.DASHSCOPE_API_KEY:
        return (OpenAI(api_key=config.DASHSCOPE_API_KEY, base_url=config.DASHSCOPE_BASE_URL,
                       timeout=config.LLM_TIMEOUT, max_retries=1),
                config.QWEN_VL_MODEL, {})
    if config.DEEPSEEK_API_KEY:
        return (OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL,
                       timeout=config.LLM_TIMEOUT, max_retries=1),
                config.VISION_MODEL,
                # DeepSeek 视觉：关掉思考模式，首字快且追问不会空答案
                {"thinking": {"type": "disabled"}})
    return None, None, {}


class VisionChat:
    """一次圈选对应一个会话：第一问带图，后续追问共享历史。"""

    def __init__(self, image_png: Optional[bytes], context: str = ""):
        self.image_png = image_png
        self.context = context
        self.history: List[dict] = []
        self._busy = threading.Lock()
        self._cancel = threading.Event()

    def ask(self, question: str,
            on_delta: Callable[[str], None],
            on_done: Callable[[str], None],
            on_error: Callable[[str], None]):
        """后台线程流式回答。on_delta 收增量文本，on_done 收完整答案。"""
        if not self._busy.acquire(blocking=False):
            on_error("上一个问题还在回答中")
            return
        self._cancel.clear()
        threading.Thread(target=self._run, args=(question, on_delta, on_done, on_error),
                         daemon=True, name="echo-vision").start()

    def cancel(self):
        self._cancel.set()

    def _messages(self, question: str) -> List[dict]:
        msgs = [{"role": "system", "content": SYSTEM}]
        msgs += self.history
        if not self.history:
            text = (self.context + "\n\n" if self.context else "") + f"【学生的问题】{question}"
            content = [{"type": "text", "text": text}]
            if self.image_png:
                b64 = base64.b64encode(self.image_png).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
            msgs.append({"role": "user", "content": content})
        else:
            # 追问时把图再带上，避免模型丢掉视觉上下文
            content = [{"type": "text", "text": question}]
            if self.image_png:
                b64 = base64.b64encode(self.image_png).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
            msgs.append({"role": "user", "content": content})
        return msgs

    def _run(self, question, on_delta, on_done, on_error):
        try:
            client, model, extra = _make_client()
            if client is None:
                raise RuntimeError("缺少视觉模型 API key：请配置 DASHSCOPE_API_KEY 或 DEEPSEEK_API_KEY")
            msgs = self._messages(question)
            stream = client.chat.completions.create(
                model=model, messages=msgs, stream=True,
                temperature=0.4, max_tokens=900, extra_body=extra or None)
            parts = []
            for chunk in stream:
                if self._cancel.is_set():
                    stream.close()
                    return
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    parts.append(delta)
                    on_delta(delta)
            answer = "".join(parts).strip()
            self.history = msgs[1:] + [{"role": "assistant", "content": answer}]
            on_done(answer)
        except Exception as e:
            log.exception("圈选问答失败")
            on_error(f"AI 暂时回答不了：{e}")
        finally:
            self._busy.release()


ASK_SYSTEM = """你是 Echo，一个陪学生听网课的 AI 学习副驾驶。学生刚点了「我掉队了」，现在针对自己的困惑追问你。
你会拿到课堂时间轴、老师最近讲的内容，以及刚才定位到的知识断点。请像一位耐心的助教，只针对学生问的那一点讲清楚。

要求：
- 先一句话确认学生问的是什么，再讲；结合老师刚讲的内容，不要脱离课堂
- 只讲缺失的那一步 / 那个点，别把整节课再讲一遍
- 纯文本，公式写成 P(A|B)、x^2、a/b 这种，不要 LaTeX、不要 Markdown 标题/加粗/表格
- 简洁：一般 3~7 行，能用一个小例子就用一个"""


class LessonAsk:
    """文字追问（不带图）：把学生的问题 + 课堂上下文一起给 DeepSeek 文本模型，流式回答。"""

    def __init__(self, engine, extra_context: str = ""):
        self.context = (lesson_context(engine) or "").strip()
        if extra_context:
            self.context = (self.context + "\n\n" + extra_context).strip()
        self.history: List[dict] = []
        self._busy = threading.Lock()
        self._cancel = threading.Event()

    def ask(self, question, on_delta, on_done, on_error):
        if not self._busy.acquire(blocking=False):
            on_error("上一个问题还在回答中")
            return
        self._cancel.clear()
        threading.Thread(target=self._run, args=(question, on_delta, on_done, on_error),
                         daemon=True, name="echo-ask").start()

    def cancel(self):
        self._cancel.set()

    def _run(self, question, on_delta, on_done, on_error):
        try:
            if not config.DEEPSEEK_API_KEY:
                raise RuntimeError("缺少 DEEPSEEK_API_KEY，离线模式下不能追问")
            from openai import OpenAI
            client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL,
                            timeout=config.LLM_TIMEOUT, max_retries=1)
            msgs = [{"role": "system", "content": ASK_SYSTEM}] + self.history
            if not self.history:
                text = (self.context + "\n\n" if self.context else "") + f"【学生的问题】{question}"
                msgs.append({"role": "user", "content": text})
            else:
                msgs.append({"role": "user", "content": question})
            stream = client.chat.completions.create(
                model=config.DEEPSEEK_MODEL, messages=msgs, stream=True, temperature=0.4, max_tokens=700)
            parts = []
            for chunk in stream:
                if self._cancel.is_set():
                    stream.close()
                    return
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    parts.append(delta)
                    on_delta(delta)
            answer = "".join(parts).strip()
            self.history = msgs[1:] + [{"role": "assistant", "content": answer}]
            on_done(answer)
        except Exception as e:
            log.exception("追问失败")
            on_error(f"AI 暂时回答不了：{e}")
        finally:
            self._busy.release()
