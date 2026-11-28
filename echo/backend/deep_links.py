"""Strict browser-to-desktop classroom intent; never execute URI commands."""
from urllib.parse import urlsplit, parse_qs


def classroom_intent(uri):
    if not isinstance(uri, str) or len(uri) > 2048:
        raise ValueError('Echo 链接过长。')
    parsed = urlsplit(uri)
    if parsed.scheme != 'echo' or parsed.netloc != 'classroom' or parsed.path != '/listen' or parsed.fragment:
        raise ValueError('不支持的 Echo 链接。')
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if set(query) - {'title'} or len(query.get('title', [])) != 1:
        raise ValueError('课堂链接参数无效。')
    title = query['title'][0].strip()
    if not 1 <= len(title) <= 160 or any(ord(c) < 32 for c in title):
        raise ValueError('课堂标题无效。')
    return title


def register_windows_protocol():
    import os, sys, subprocess
    from pathlib import Path
    if os.name != 'nt': return
    import winreg
    if getattr(sys, 'frozen', False):
        command = subprocess.list2cmdline([sys.executable])
    else:
        command = subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve().parents[2] / 'main.py')])
    base = r'Software\Classes\echo'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, 'URL:Echo classroom')
        winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r'\shell\open\command') as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, command + ' "%1"')
