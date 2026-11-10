"""
Echo - 多家模型（都走 OpenAI 兼容接口）

文本和视觉分开选。没填新字段时沿用原来的 DEEPSEEK_* / DASHSCOPE_*，
老的 .env 不用改也能继续用 DeepSeek。

每次调用现读环境变量，设置窗口保存后，下一次提问就换厂商
（已经在跑的这节课，引擎是启动时接上的，要重新开一节或重启才换）。
"""
import os
from urllib.parse import urlparse

# id, 中文名, 英文名, base_url, 默认文本模型, 默认视觉模型（空 = 这家不看图）
PRESETS = (
    ("deepseek", "DeepSeek", "DeepSeek",
     "https://api.deepseek.com", "deepseek-flash", "deepseek-flash"),
    ("qwen", "通义千问", "Qwen",
     "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus", "qwen3-vl-plus"),
    ("kimi", "Kimi（月之暗面）", "Kimi",
     "https://api.moonshot.cn/v1", "moonshot-v1-8k", ""),
    ("zhipu", "智谱 GLM", "Zhipu GLM",
     "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash", "glm-4v-flash"),
    ("silicon", "硅基流动", "SiliconFlow",
     "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-VL-7B-Instruct"),
    ("openai", "OpenAI", "OpenAI",
     "https://api.openai.com/v1", "gpt-4o-mini", "gpt-4o-mini"),
    ("groq", "Groq", "Groq",
     "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", ""),
    ("stepfun", "阶跃星辰", "StepFun",
     "https://api.stepfun.com/v1", "step-1-8k", "step-1v-8k"),
    ("hunyuan", "腾讯混元", "Hunyuan",
     "https://api.hunyuan.cloud.tencent.com/v1", "hunyuan-lite", "hunyuan-vision"),
    ("doubao", "豆包（火山方舟）", "Doubao",
     "https://ark.cn-beijing.volces.com/api/v3", "", ""),
    ("openrouter", "OpenRouter", "OpenRouter",
     "https://openrouter.ai/api/v1", "openai/gpt-4o-mini", "openai/gpt-4o-mini"),
    ("ollama", "Ollama 本地", "Ollama (local)",
     "http://127.0.0.1:11434/v1", "qwen2.5", "llava"),
    ("custom", "自定义", "Custom",
     "", "", ""),
)


def preset(pid: str):
    for p in PRESETS:
        if p[0] == pid:
            return p
    return PRESETS[0]


def label(pid: str, en: bool = False) -> str:
    p = preset(pid)
    return p[2] if en else p[1]


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def current_model(pid, base_url, model):
    """Migrate retired built-in model IDs only on that vendor's official API."""
    host = (urlparse(base_url).hostname or "").lower()
    if pid == "deepseek" and host == "api.deepseek.com" and model == "deepseek-chat":
        return "deepseek-flash"
    if pid == "qwen" and host in ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com",
                                  "dashscope-us.aliyuncs.com") and model == "qwen-vl-plus":
        return "qwen3-vl-plus"
    return model


def _current(spec):
    spec["model"] = current_model(spec["id"], spec["base_url"], spec["model"])
    return spec


def text() -> dict:
    """当前文本模型。返回 id / api_key / base_url / model。"""
    explicit = _env("ECHO_LLM_PROVIDER")
    if explicit:
        p = preset(explicit)
        key = _env("ECHO_LLM_API_KEY")
        if not key and p[0] == "deepseek":
            key = _env("DEEPSEEK_API_KEY")
        if not key and p[0] == "qwen":
            key = _env("DASHSCOPE_API_KEY")
        return _current({
            "id": p[0],
            "api_key": key,
            "base_url": _env("ECHO_LLM_BASE_URL") or p[3],
            "model": _env("ECHO_LLM_MODEL") or p[4],
        })
    # 老配置：只有 DEEPSEEK_API_KEY
    p = preset("deepseek")
    return _current({
        "id": "deepseek",
        "api_key": _env("DEEPSEEK_API_KEY"),
        "base_url": _env("DEEPSEEK_BASE_URL") or p[3],
        "model": _env("DEEPSEEK_MODEL") or p[4],
    })


def vision() -> dict:
    """统一视觉设置；仅在未使用新提供商设置时兼容旧百炼配置。"""
    explicit = _env("ECHO_VISION_PROVIDER")
    if explicit and explicit != "same":
        p = preset(explicit)
        key = _env("ECHO_VISION_API_KEY")
        if not key and p[0] == text()["id"]:
            key = text()["api_key"]
        if not key and p[0] == "qwen":
            key = _env("DASHSCOPE_API_KEY")
        if not key and p[0] == "deepseek":
            key = _env("DEEPSEEK_API_KEY") or text()["api_key"]
        return _current({
            "id": p[0],
            "api_key": key,
            "base_url": _env("ECHO_VISION_BASE_URL") or p[3],
            "model": _env("ECHO_VISION_MODEL") or p[5] or p[4],
        })
    if not explicit and not _env("ECHO_LLM_PROVIDER") and _env("DASHSCOPE_API_KEY"):
        p = preset("qwen")
        return _current({
            "id": "qwen",
            "api_key": _env("DASHSCOPE_API_KEY"),
            "base_url": _env("DASHSCOPE_BASE_URL") or p[3],
            "model": _env("ECHO_QWEN_VL_MODEL") or p[5],
        })
    t = text()
    p = preset(t["id"])
    return _current({
        "id": t["id"],
        "api_key": t["api_key"],
        "base_url": t["base_url"],
        # "Same provider" hides the override fields in Settings: stale values from
        # a previous provider must not be sent to this provider's endpoint.
        "model": ("" if explicit == "same" else _env("ECHO_VISION_MODEL")) or p[5] or t["model"],
    })


def vision_extra(spec):
    """Common request options for every visual entry point."""
    return {"thinking": {"type": "disabled"}} if spec["id"] == "deepseek" else {}


def text_extra(spec):
    # These UI flows need a direct answer within a small output budget.
    return {"thinking": {"type": "disabled"}} if spec["id"] == "deepseek" and spec["model"] == "deepseek-flash" else {}


def api_error(error, spec):
    """Actionable diagnostics without displaying raw responses or credentials."""
    detail = f"{label(spec['id'])} · {spec['model']}"
    status = getattr(error, "status_code", None)
    if status == 404:
        return f"模型不可用（{detail}，404）。请在设置检查模型名、接口地址与账号开通区域。"
    if status in (401, 403):
        return f"模型鉴权或权限不足（{detail}，{status}）。请检查对应厂商的 Key 与模型权限。"
    if status in (402, 429):
        return f"模型额度不足或请求过快（{detail}，{status}），请检查余额和限流。"
    return f"AI 暂时连接失败（{detail}）。请检查网络和模型设置后重试。"


def configured(spec: dict = None) -> bool:
    """有 key，或是不需要 key 的本地 Ollama。"""
    spec = text() if spec is None else spec
    if spec["id"] == "ollama":
        return bool(spec["base_url"])
    return bool(spec["api_key"])


def client(spec: dict, retries: int = 0):
    from openai import OpenAI

    from echo.backend import config

    key = spec["api_key"] or ("ollama" if spec["id"] == "ollama" else "")
    if not key:
        return None
    return OpenAI(api_key=key, base_url=spec["base_url"] or None,
                  timeout=config.LLM_TIMEOUT, max_retries=retries)
