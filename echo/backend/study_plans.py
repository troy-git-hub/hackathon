"""Assistant-written study plans. Separate from 小本 (notes)."""
import json
import time
import uuid
from pathlib import Path
from echo.backend import paths

_FILE = 'study_plans.json'


def _path():
    return Path(paths.config_dir()) / _FILE


def save(goal, days, text):
    items = list_plans()
    record = {
        'id': uuid.uuid4().hex,
        'goal': str(goal or '')[:80],
        'days': int(days or 7),
        'text': str(text or '')[:20000],
        'created': time.time(),
    }
    items = [record] + [it for it in items if isinstance(it, dict)][:19]
    _path().write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
    return record


def list_plans():
    file = _path()
    if not file.exists():
        return []
    try:
        data = json.loads(file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [it for it in data if isinstance(it, dict)] if isinstance(data, list) else []


def latest():
    items = list_plans()
    return items[0] if items else None
