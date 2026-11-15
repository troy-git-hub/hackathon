"""Admin activates offline-signed, pre-uploaded releases; never accepts a URL/key."""
import base64
import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from fastapi import Request
from cryptography.hazmat.primitives.serialization import load_pem_public_key

_lock=threading.Lock()


def install(app,core):
    auth,fail=core['session_user'],core['fail']
    stable=Path(os.getenv('ECHO_UPDATE_DIR','/update-data'))
    beta=Path(os.getenv('ECHO_BETA_DIR','/releases'))
    public=Path(os.getenv('ECHO_RELEASE_PUBLIC_KEY','/app/update-public-key.pem'))

    def read(file):
        if file.stat().st_size>32768:raise ValueError('发布清单过大。')
        return json.loads(file.read_text(encoding='utf-8'))

    def validate(data,channel,verify_bytes=False):
        if channel=='beta':
            release={k:v for k,v in data.items() if k!='signature'};signature=data['signature'];root=beta
            pattern=r'Echo-Beta-(?:Setup-\d+\.\d+\.\d+\.exe|\d+\.\d+\.\d+-windows-x64\.zip)'
        else:
            release=data['release'];signature=data['signature'];root=stable/'artifacts'
            pattern=r'Echo-(?:Setup-\d+\.\d+\.\d+\.exe|Update-\d+\.\d+\.\d+\.zip)'
            if release.get('channel')!='stable' or release.get('platform')!='windows-x64':raise ValueError('渠道或平台无效。')
        load_pem_public_key(public.read_bytes()).verify(base64.b64decode(signature,validate=True),json.dumps(release,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
        if not re.fullmatch(pattern,release['filename']) or not re.fullmatch(r'\d+\.\d+\.\d+',release['version']) or not re.fullmatch(r'[0-9a-f]{64}',release['sha256']):raise ValueError('文件名、版本或哈希格式无效。')
        file=root/release['filename']
        if type(release['size'])!=int or release['size']<=0 or file.is_symlink() or file.stat().st_size!=release['size']:raise ValueError('文件缺失或大小不符。')
        if verify_bytes:
            with file.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
            if sha!=release['sha256']:raise ValueError('安装包哈希不匹配，不能发布。')
        return release

    def atomic(file,data):
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=file.parent,mode='w',encoding='utf-8',delete=False) as f:
                temporary=Path(f.name);json.dump(data,f,ensure_ascii=False,indent=2)
            os.replace(temporary,file)
        finally:
            if temporary:temporary.unlink(missing_ok=True)

    @app.get('/v1/admin/releases')
    def releases(request:Request):
        auth(request,True);items=[]
        for channel,root,names in [('stable',stable,['stable.json','stable-v2.json']),('beta',beta,['beta.json'])]:
            for name in names:
                try:items.append({'channel':channel,'slot':name,'release':validate(read(root/name),channel),'state':'published'})
                except Exception:pass
            for file in sorted((root/'candidates').glob('*.json'))[:50]:
                try:items.append({'channel':channel,'candidate':file.name,'release':validate(read(file),channel),'state':'prepared'})
                except Exception:pass
        try:paused=read(stable/'control.json').get('paused',False) is True
        except (OSError,ValueError):paused=False
        return {'items':items,'paused':paused,'source_updates':False,'policy':'安装包必须在本机签名并通过 SSH 预上传；后台只激活已验证的发布清单。'}

    @app.post('/v1/admin/releases/pause')
    async def pause(request:Request):
        user=auth(request,True);data=await core['payload'](request)
        if type(data.get('paused'))!=bool:fail(400,'暂停状态无效。')
        with _lock:atomic(stable/'control.json',{'paused':data['paused']})
        with core['db'](True) as c:core['audit'](c,user['id'],'update-pause',{'paused':data['paused']})
        return {'ok':True}

    @app.post('/v1/admin/releases/publish')
    async def publish(request:Request):
        user=auth(request,True);core['rate']('release:'+user['id'],10,3600);data=await core['payload'](request)
        channel=data.get('channel');name=data.get('candidate','')
        if channel not in ('stable','beta') or not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}\.json',name):fail(400,'候选版本无效。')
        with _lock:
            root=stable if channel=='stable' else beta
            try:
                envelope=read(root/'candidates'/name);release=validate(envelope,channel,True)
                target='beta.json' if channel=='beta' else 'stable-v2.json' if release.get('format')=='echo.update/2' else 'stable.json'
                if (root/target).exists():
                    old=validate(read(root/target),channel)
                    version=lambda v:tuple(map(int,v.split('.')))
                    if version(old['version'])>version(release['version']):raise ValueError('不允许回退到旧版本。')
                    if old['version']==release['version'] and old['sha256']!=release['sha256']:raise ValueError('同版本不可替换文件，请增加版本号。')
                atomic(root/target,envelope)
            except Exception as exc:fail(400,'发布失败：'+str(exc)[:200])
        with core['db'](True) as c:core['audit'](c,user['id'],'release-published',{'channel':channel,'version':release['version'],'sha256':release['sha256']})
        return {'ok':True,'version':release['version']}
