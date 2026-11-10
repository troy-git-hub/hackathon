"""
Echo - JSON 调用封装

厂商在 providers.py 里选（DeepSeek / 千问 / Kimi / 智谱 / …，都是 OpenAI 兼容接口）。
有的厂商不支持 response_format=json_object，失败就退回普通输出再解析一次。
"""
import json
import logging
import re

from echo.backend import config, providers

log = logging.getLogger("echo.llm")


class LLMError(RuntimeError):
    pass


def _json_mode_unsupported(err: Exception) -> bool:
    msg = str(err).lower()
    return "response_format" in msg or "json_object" in msg or "json mode" in msg


class LLM:
    def __init__(self, api_key=None):
        # 没配 key 就让引擎退回 mock。Ollama 本地不需要 key。
        spec = providers.text()
        if api_key:
            spec = dict(spec, api_key=api_key)
        if not providers.configured(spec):
            raise LLMError("还没配置模型 API key")
        self._override_key = api_key

    def _client_and_model(self):
        spec = providers.text()
        if self._override_key:
            spec = dict(spec, api_key=self._override_key)
        if not providers.configured(spec):
            raise LLMError("还没配置模型 API key")
        client = providers.client(spec, retries=0)
        if client is None:
            raise LLMError("还没配置模型 API key")
        return client, spec["model"]

    def json(self, system: str, user: str, temperature=0.3, max_tokens=1200,
             timeout: float = None, attempts: int = 2) -> dict:
        """调用 LLM 并返回解析后的 JSON dict；网络错误 / JSON 截断时重试一次。"""
        client, model = self._client_and_model()
        last = None
        use_json_mode = True
        attempt = 0
        while attempt < attempts:
            try:
                kwargs = dict(
                    model=model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    temperature=temperature,
                    max_tokens=max_tokens if attempt == 0 else int(max_tokens * 1.5),
                    timeout=timeout or config.LLM_TIMEOUT,
                )
                if use_json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                spec = providers.text()
                kwargs["extra_body"] = providers.text_extra(spec) or None
                resp = client.chat.completions.create(**kwargs)
                return parse_json(resp.choices[0].message.content or "")
            except Exception as e:
                if use_json_mode and _json_mode_unsupported(e):
                    use_json_mode = False
                    log.warning("这家模型不支持 JSON mode，改为普通输出再解析")
                    continue          # 不算一次失败，立刻用不带 json mode 的方式再要一次
                last = e
                attempt += 1
                log.warning("LLM 调用失败（第 %d 次）: %s", attempt, e)
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
