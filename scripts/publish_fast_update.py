"""Publish a signed complete-directory ZIP on the v2 update channel; never ship signing keys."""
import argparse
import base64
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from echo.backend.updater import canonical,verify_manifest,version_tuple
from echo.backend.fast_update import inspect_archive

def publish(folder,version,data,private_key,public_key,notes):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    version_tuple(version)
    folder=Path(folder).resolve();data=Path(data).resolve()
    if not (folder/'Echo.exe').is_file():raise ValueError('需要已验证的独立构建目录版 Echo')
    data.mkdir(parents=True,exist_ok=True)
    artifacts=data/'artifacts';artifacts.mkdir(exist_ok=True)
    target=artifacts/f'Echo-Update-{version}.zip'
    if target.exists():raise ValueError('此版本已发布，请增加版本号')
    stable=data/'stable-v2.json'
    if stable.exists():
        old=verify_manifest(json.loads(stable.read_text(encoding='utf-8')),public_key)
        if version_tuple(old['version'])>=version_tuple(version):raise ValueError('快速更新渠道不允许回退或覆盖')
    temporary=artifacts/(target.name+'.upload')
    try:
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for file in sorted(folder.rglob('*')):
                if file.is_symlink():raise ValueError('构建目录不能包含符号链接')
                if not file.is_file():continue
                relative=file.relative_to(folder)
                if any(p.lower() in ('.env','models','lessons.json','profile.json','review.json','account.env') for p in relative.parts):raise ValueError('构建目录中发现私密配置或用户数据')
                if file.name.lower().startswith('unins'):continue
                archive.write(file,relative.as_posix())
        inspect_archive(temporary)
        with temporary.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        release={'format':'echo.update/2','version':version,'platform':'windows-x64','channel':'stable','filename':target.name,'size':temporary.stat().st_size,'sha256':sha,'notes':notes,'published_at':datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')}
        key=load_pem_private_key(Path(private_key).read_bytes(),password=None)
        envelope={'release':release,'signature':base64.b64encode(key.sign(canonical(release))).decode()}
        verify_manifest(envelope,public_key)
        os.replace(temporary,target)
        with tempfile.NamedTemporaryFile(dir=data,mode='w',encoding='utf-8',delete=False) as stream:
            json.dump(envelope,stream,ensure_ascii=False,indent=2);name=stream.name
        os.replace(name,stable)
        return target
    finally:temporary.unlink(missing_ok=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--folder',required=True,type=Path);p.add_argument('--version',required=True);p.add_argument('--data',type=Path,default=ROOT/'update-server/data');p.add_argument('--private-key',type=Path,default=ROOT/'.build/update-secrets/release-private-key.pem');p.add_argument('--notes',type=Path)
    a=p.parse_args();notes=a.notes.read_text(encoding='utf-8').splitlines() if a.notes else ['Echo 快速目录更新，保留学习资料。']
    result=publish(a.folder,a.version,a.data,a.private_key,(ROOT/'assets/update-public-key.pem').read_bytes(),[n.strip() for n in notes if n.strip()]);print('Published signed fast update:',result)

if __name__=='__main__':main()
