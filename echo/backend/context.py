"""Bounded local context selection; never spends a model call to summarize."""
import threading
import time


def bounded_text(text, limit=6000):
    text = str(text or "")
    if len(text) <= limit:
        return text
    marker = "\n…（较早内容已省略，以下为最近内容）…\n"
    head = min(800, limit // 5)
    return text[:head] + marker + text[-(limit - head - len(marker)):]


def recent_turns(history, max_chars=6000, max_pairs=4):
    """Retain whole user/assistant pairs. Never retain repeated screenshot payloads."""
    pairs, used = [], 0
    for index in range(len(history) - 2, -1, -2):
        user, answer = history[index:index + 2]
        if user.get("role") != "user" or answer.get("role") != "assistant":
            continue
        content = user.get("content", "")
        if isinstance(content, list):
            content = "\n".join(p.get("text", "") for p in content if p.get("type") == "text")
        pair = [{"role": "user", "content": bounded_text(content, 1200)},
                {"role": "assistant", "content": bounded_text(answer.get("content"), 1800)}]
        size = sum(len(p["content"]) for p in pair)
        if used + size > max_chars or len(pairs) >= max_pairs:
            break
        used += size
        pairs.insert(0, pair)
    return [turn for pair in pairs for turn in pair]


class AutomaticBudget:
    """Fair shared spacing for automatic model requests in one lesson."""
    def __init__(self, interval=50):
        self.interval = max(50, interval)
        self.last = float("-inf")
        self.waiting = []
        self.seen = {}
        self.lock = threading.Lock()

    def reserve(self, kind, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            self.seen[kind] = now
            self.waiting = [k for k in self.waiting if now - self.seen[k] <= 5]
            if kind not in self.waiting:
                self.waiting.append(kind)
            if now - self.last < self.interval or self.waiting[0] != kind:
                return False
            self.waiting.pop(0)
            self.last = now
            return True

    def discard(self, kind):
        with self.lock:
            if kind in self.waiting:
                self.waiting.remove(kind)
