"""Account-scoped native answer drafts, never session tokens or provider keys."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from echo.backend import paths


def folder(owner):
    if not owner:raise ValueError('请先登录后使用试卷本。')
    root=Path(paths.config_dir())/'paper-drafts'/hashlib.sha256(owner.encode()).hexdigest()
    root.mkdir(parents=True,exist_ok=True)
    return root


def save(owner,paper,answers):
    ident=paper.get('id','')
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise ValueError('试卷编号无效。')
    raw=json.dumps({'owner':owner,'paper':paper,'answers':answers},ensure_ascii=False,allow_nan=False)
    if len(raw.encode())>2*1024*1024:raise ValueError('本地试卷过大。')
    root=folder(owner);temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=root,delete=False) as stream:
            temporary=Path(stream.name);stream.write(raw)
        os.replace(temporary,root/(ident+'.json'))
    finally:
        if temporary:temporary.unlink(missing_ok=True)


def load(owner,ident):
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise ValueError('试卷编号无效。')
    file=folder(owner)/(ident+'.json')
    if file.stat().st_size>2*1024*1024:raise ValueError('草稿大小异常。')
    data=json.loads(file.read_text(encoding='utf-8'))
    if data.get('owner')!=owner:raise ValueError('草稿不属于当前账户。')
    return data


def list_drafts(owner):
    rows=[]
    for file in sorted(folder(owner).glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:50]:
        try:rows.append(load(owner,file.stem))
        except (OSError,ValueError,KeyError):continue
    return rows
