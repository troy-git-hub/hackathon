"""
Echo - DeepSeek JSON 调用封装
"""
import json
import logging
import re

from echo.backend import config

log = logging.getLogger("echo.llm")


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, api_key=None):
        from openai import OpenAI
        key = api_key or config.DEEPSEEK_API_KEY
        if not key:
            raise LLMError("缺少 DEEPSEEK_API_KEY")
        self.client = OpenAI(api_key=key, base_url=config.DEEPSEEK_BASE_URL,
                             timeout=config.LLM_TIMEOUT, max_retries=0)  # 重试由 json() 自己做

    def json(self, system: str, user: str, temperature=0.3, max_tokens=1200,
             timeout: float = None, attempts: int = 2) -> dict:
        """调用 LLM 并返回解析后的 JSON dict；网络错误 / JSON 截断时重试一次。"""
        last = None
        for attempt in range(attempts):
            try:
                resp = self.client.chat.completions.create(
                    model=config.DEEPSEEK_MODEL,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    response_format={"type": "json_object"},
                    temperature=temperature,
                    max_tokens=max_tokens if attempt == 0 else int(max_tokens * 1.5),
                    timeout=timeout or config.LLM_TIMEOUT,
                )
                return parse_json(resp.choices[0].message.content or "")
            except Exception as e:
                last = e
                log.warning("LLM 调用失败（第 %d 次）: %s", attempt + 1, e)
        raise last if isinstance(last, LLMError) else LLMError(f"LLM 调用失败: {last}")


def parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMError(f"LLM 返回不是合法 JSON: {text[:200]}")
