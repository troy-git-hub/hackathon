"""Verified ZIP updates: stage an entire distribution, then swap after Echo exits."""
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

def inspect_archive(package):
    with zipfile.ZipFile(package) as archive:
        entries=archive.infolist()
        if not entries or len(entries)>20000:raise ValueError('更新包文件数量异常')
        total=0;seen=set()
        for info in entries:
            name=info.orig_filename
            parts=PurePosixPath(name).parts
            if name.rstrip('/')!=PurePosixPath(name).as_posix():raise ValueError('更新包包含非规范文件路径')
            if (not parts or name.startswith('/') or chr(92) in name or ':' in name or any(ord(ch)<32 for ch in name) or any(p in ('.','..') or p.endswith((' ','.')) or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:[.]|$)',p,re.I) for p in parts)
                    or stat.S_ISLNK(info.external_attr>>16)):
                raise ValueError('更新包包含不安全的文件路径')
            key=name.rstrip('/').casefold()
            if key in seen:raise ValueError('更新包含重复路径')
            seen.add(key)
            if any(p.lower() in ('.env','models','lessons.json','profile.json','review.json','account.env') for p in parts):raise ValueError('更新包不得携带用户数据或私密配置')
            total+=info.file_size
            if total>2*1024**3 or info.file_size>1024**3:raise ValueError('解压后的更新包过大')
        if 'echo.exe' not in seen or not any(n.startswith('_internal/') for n in seen):raise ValueError('需要完整的 Echo 目录版更新包')
        exe=next(i for i in entries if i.filename.casefold()=='echo.exe')
        with archive.open(exe) as stream:
            if stream.read(2)!=b'MZ':raise ValueError('Echo.exe 格式不正确')
        if archive.testzip():raise ValueError('更新压缩包已损坏')
        return total

def stage(package,target):
    target=Path(target).resolve()
    if not (target/'Echo.exe').is_file():raise ValueError('找不到当前安装目录中的 Echo.exe')
    total=inspect_archive(package)
    if shutil.disk_usage(target.parent).free<total+100*1024**2:raise ValueError('安装磁盘空间不足')
    folder=Path(tempfile.mkdtemp(prefix='.echo-stage-',dir=target.parent)).resolve()
    try:
        with zipfile.ZipFile(package) as archive:
            for info in archive.infolist():
                dest=folder.joinpath(*PurePosixPath(info.filename).parts)
                if not dest.resolve().is_relative_to(folder):raise ValueError('更新路径越界')
                if info.is_dir():dest.mkdir(parents=True,exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(info) as source,dest.open('wb') as output:shutil.copyfileobj(source,output)
        # Preserve installer registration so the existing uninstall entry still works.
        for item in target.glob('unins*'):
            if item.is_file() and item.suffix.lower() in ('.exe','.dat','.msg'):shutil.copy2(item,folder/item.name)
        return folder
    except Exception:
        if folder.parent==target.parent and folder.name.startswith('.echo-stage-'):shutil.rmtree(folder)
        raise

def launch(stage_dir,target,work_dir):
    if os.name!='nt':raise ValueError('快速更新目前仅支持 Windows')
    target=Path(target).resolve();stage_dir=Path(stage_dir).resolve()
    if stage_dir.parent!=target.parent or not stage_dir.name.startswith('.echo-stage-') or not (stage_dir/'Echo.exe').is_file():raise ValueError('暂存目录无效')
    work=Path(work_dir).resolve();work.mkdir(parents=True,exist_ok=True)
    config=work/('apply-'+os.urandom(8).hex()+'.json')
    config.write_text(json.dumps({'target':str(target),'stage':str(stage_dir),'parent_id':os.getpid()}),encoding='utf-8')
    from echo.backend import paths
    helper=work/(config.stem+'.ps1')
    shutil.copyfile(paths.asset('assets','apply-update.ps1'),helper)
    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.Popen([str(powershell),'-NoProfile','-NonInteractive','-WindowStyle','Hidden','-ExecutionPolicy','RemoteSigned','-File',str(helper),'-ConfigFile',str(config)],cwd=str(work),close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW)
