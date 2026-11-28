"""Bounded, portable assistant practice cards; never HTML or executable code."""
import json
import re

PROTOCOL = 'echo.assistant.quiz/1'
_LETTERS = 'ABCDEF'


def _option_text(value):
    if isinstance(value, dict):
        for key in ('text', 'label', 'content', 'option'):
            if value.get(key):
                return str(value[key])[:100]
        return ''
    return str(value or '')[:100]


def _answer_index(answer, options):
    if isinstance(answer, bool):
        return None
    if isinstance(answer, int) and 0 <= answer < len(options):
        return answer
    if isinstance(answer, float) and answer == int(answer) and 0 <= int(answer) < len(options):
        return int(answer)
    text = str(answer or '').strip()
    if not text:
        return None
    letter = text.upper()
    if letter in _LETTERS and _LETTERS.index(letter) < len(options):
        return _LETTERS.index(letter)
    match = re.match(r'^([A-F])[\.、．\)]\s*', text, re.I)
    if match and _LETTERS.index(match.group(1).upper()) < len(options):
        return _LETTERS.index(match.group(1).upper())
    for index, option in enumerate(options):
        if text == option or text.endswith(option):
            return index
    return None


def pack_quiz(topic, questions):
    items = []
    for raw in questions[:5] if isinstance(questions, list) else []:
        if not isinstance(raw, dict):
            continue
        stem = str(raw.get('question') or raw.get('stem') or '')[:240]
        if not stem:
            continue
        kind = str(raw.get('type') or '').lower()
        raw_options = raw.get('options') if isinstance(raw.get('options'), list) else []
        options = []
        if kind not in ('fill_blank', 'short_answer', 'blank'):
            for value in raw_options[:6]:
                text = _option_text(value)
                if text:
                    options.append(text)
        answer = raw.get('answer', raw.get('correct', ''))
        if options:
            index = _answer_index(answer, options)
            # 有选项就保留选项。对不上也不改成填空，避免界面和题型错位。
            answer = index if index is not None else 0
        elif not isinstance(answer, str):
            answer = str(answer or '')[:240]
        else:
            answer = answer[:240]
        items.append({
            'question': stem,
            'options': options,
            'answer': answer,
            'explanation': str(raw.get('explanation') or raw.get('explain') or raw.get('analysis') or '')[:240],
        })
    return json.dumps({'protocol': PROTOCOL, 'topic': str(topic)[:80], 'questions': items}, ensure_ascii=False)


def load_quiz(text):
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) and data.get('protocol') == PROTOCOL and isinstance(data.get('questions'), list) else None
    except (TypeError, ValueError):
        return None
