"""Small, account-bound aggregate sync. Never uploads lessons, credentials or media."""
import copy
import re
from datetime import datetime
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from echo.backend import account,learning_export,paths,store,cloud_archive

_LOCK=threading.RLock()
_RUN=threading.Lock()
_status={'state':'idle','message':'登录后自动同步学习档案。','last_success':0}

def _path():return Path(paths.config_dir())/'cloud-sync.json'
def _load():
    try:
        data=json.loads(_path().read_text(encoding='utf-8'))
        return data if isinstance(data,dict) else {}
    except FileNotFoundError:return {}
    except (OSError,ValueError) as exc:raise account.AccountError('同步配置无法读取。请先检查本机 cloud-sync.json，未上传学习数据。') from exc
def _save(data):
    temporary=_path().with_name('.cloud-sync-'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        os.replace(temporary,_path())
    finally:
        if temporary.exists():temporary.unlink()
def configure(enabled=None,bind=False,mode=None,source_ids=None,device_name=None):
    with _LOCK:
        data=_load();data.setdefault('device_id',uuid.uuid4().hex)
        if enabled is not None:data['enabled']=bool(enabled)
        if device_name is not None:
            if not isinstance(device_name,str) or not device_name.strip() or len(device_name)>60:raise ValueError('终端名称须为1至60个字符。')
            data['device_name']=device_name.strip()
        if mode is not None:
            if mode not in ('merge','selected'):raise ValueError('同步模式无效。')
            data['mode']=mode
        if source_ids is not None:
            if not isinstance(source_ids,list) or len(source_ids)>5 or any(not isinstance(v,str) or not re.fullmatch(r'[a-f0-9]{32}',v) for v in source_ids):raise ValueError('请选择有效的终端。')
            data['source_ids']=sorted(set(source_ids))
        if data.get('mode')=='selected' and not data.get('source_ids'):raise ValueError('请至少选择一个同步来源，或选择默认合并。')
        if bind:
            user=account.current_user()
            if not user:raise account.AccountError('请先登录再关联本机学习资料。')
            data['account_id']=user['id'];data.pop('content_hash',None);data['mode']='merge';data['source_ids']=[]
        _save(data)
def enabled():
    with _LOCK:return _load().get('enabled',True)
def status():
    with _LOCK:
        try:data=_load()
        except account.AccountError as exc:return {**_status,'state':'error','message':str(exc),'enabled':False,'bound_account':None}
        return {**_status,'enabled':data.get('enabled',True),'bound_account':data.get('account_id'),'last_success':data.get('last_success',0),'mode':data.get('mode','merge'),'source_ids':data.get('source_ids',[]),'devices':data.get('devices',[]),'device_name':data.get('device_name','Echo Desktop')}
def _state(state,message):
    with _LOCK:_status.update(state=state,message=message)
def file_signature():
    result=[]
    for name in ('profile.json','lessons.json','review.json','cloud-sync.json'):
        try:
            info=(Path(paths.config_dir())/name).stat();result.append((name,info.st_mtime_ns,info.st_size))
        except OSError:result.append((name,0,0))
    return tuple(result)

def available_sources(refresh=False):
    user=account.current_user()
    if not user:raise account.AccountError('请先登录，再选择同步终端。')
    if refresh:
        session=account.token();remote=account.request('/v1/me/sync',auth_token=session,timeout=40,max_bytes=4*1024*1024)
        if remote.get('account_id')!=user['id'] or account.token()!=session or (account.current_user() or {}).get('id')!=user['id']:raise account.AccountError('账户已变化，未更新终端列表。')
        with _LOCK:
            data=_load();data['devices']=remote.get('devices',[]);data['devices_account']=user['id'];_save(data)
    with _LOCK:data=_load()
    return data.get('devices',[]) if data.get('devices_account',data.get('account_id'))==user['id'] else []

def _scope(data):return data.get('mode','merge'),tuple(sorted(data.get('source_ids',[])))

def _restore_sources(data,remote,uid,session,guard):
    """Download selected owned snapshots, deduplicate summaries and never echo them back."""
    cache_file=Path(paths.config_dir())/'cloud-terminal-cache.json'
    try:cache=json.loads(cache_file.read_text(encoding='utf-8'))
    except (OSError,ValueError):cache={}
    old=cache.get('snapshots',{}) if cache.get('account_id')==uid else {}
    snapshots={};allowed=set(data.get('source_ids',[]));selected=[]
    for device in remote.get('devices',[]):
        if device['id']==data['device_id']:continue
        if data.get('mode','merge')=='selected' and device['id'] not in allowed:continue
        selected.append(device)
    for device in selected:
        ident=device['id'];saved=old.get(ident)
        if not saved or saved.get('revision')!=device['revision']:
            saved=account.request('/v1/me/devices/'+ident+'/snapshot',timeout=45,max_bytes=2*1024*1024,auth_token=session)
        guard()
        if saved.get('protocol')!='echo.snapshot/1' or saved.get('account_id')!=uid or saved.get('device_id')!=ident or saved.get('revision')!=device['revision']:raise account.AccountError('终端快照身份或版本不符，未覆盖本机。')
        archive=saved.get('classroom',{})
        if archive.get('protocol')!='echo.classroom/1' or not isinstance(archive.get('lessons'),list) or len(archive['lessons'])>50:raise account.AccountError('终端课堂快照格式异常，未覆盖本机。')
        snapshots[ident]=saved
    with _LOCK:
        latest=_load()
        if _scope(latest)!=_scope(data) or not latest.get('enabled',True):raise account.AccountError('同步选择已变化，请再次同步。')
    imported={};knowledge=set()
    for ident,snapshot in snapshots.items():
        knowledge.update(p['id'] for p in snapshot.get('profile',{}).get('knowledge_points',[]) if isinstance(p,dict) and isinstance(p.get('id'),str))
        for item in snapshot['classroom']['lessons']:
            try:stamp=datetime.fromisoformat(item['ended_at'].replace('Z','+00:00')).timestamp()
            except (ValueError,TypeError,KeyError,OverflowError):raise account.AccountError('课堂时间格式异常。')
            if not 0<stamp<=time.time()+300:raise account.AccountError('课堂时间超出范围。')
            key=(stamp,item['title']);record={'time':stamp,'title':item['title'],'duration':item['duration_seconds'],'summary':item['summary'],'suggestion':item['suggestion'],
                'highlights':item['highlights'],'skills_detail':item['skills'],'blackboards':[{'text':item['blackboard_notes']}] if item['blackboard_notes'] else [],
                '_cloud_imported':True,'_cloud_account':uid,'_cloud_device_ids':[ident],'_cloud_truncated':item['truncated']}
            if key in imported:record['_cloud_device_ids']=sorted(set(imported[key]['_cloud_device_ids']+[ident]))
            imported[key]=record
    guard()
    with store._LOCK:
        current=store._load_lessons();local=[r for r in current if not r.get('_cloud_imported')];keys={(r.get('time'),r.get('title')) for r in local}
        restored=local+[row for key,row in sorted(imported.items()) if key not in keys]
        if restored!=current and not store._write_json(store._lessons_path(),restored):raise account.AccountError('课堂回顾未能写入本机，请检查空间后重试。')
    temporary=cache_file.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps({'account_id':uid,'snapshots':snapshots},ensure_ascii=False),encoding='utf-8');os.replace(temporary,cache_file)
    finally:temporary.unlink(missing_ok=True)
    return len(imported),knowledge

def _ambiguous_topics(items):
    identities={}
    for item in items:
        topic=item.get('topic')
        if isinstance(topic,str):identities.setdefault(topic.casefold(),set()).add(item.get('knowledge_id'))
    return {topic for topic,ids in identities.items() if len(ids)>1}

def _apply_reviews(items):
    """Merge only newer review progress; preserve local learning context and newer work."""
    changed=0;ambiguous=_ambiguous_topics(items)
    with store._LOCK:
        current=store.load();by_topic={str(r.get('topic','')).casefold():r for r in current}
        for remote in items:
            topic=remote.get('topic')
            if not isinstance(topic,str) or not topic.strip():continue
            # Legacy desktop records have no subject. Do not apply a maths review
            # to a same-named language topic simply because their text matches.
            if topic.casefold() in ambiguous:continue
            stamp=remote.get('reviewed_at',0)
            if type(stamp) not in (int,float) or stamp<0 or stamp>time.time()+300:continue
            item=by_topic.get(topic.casefold())
            if item and stamp<=float(item.get('reviewed_at') or 0):continue
            if item is None:
                item={'_cloud_account':(account.current_user() or {}).get('id'),'topic':topic,'time':remote.get('time') or stamp or time.time(),'source':'cloud_review','missing':str(remote.get('missing',''))[:2000],'reason':str(remote.get('reason',''))[:2000]}
                current.append(item);by_topic[topic.casefold()]=item
            for key in ('reviewed_at','due','level','review_count','last_result','reviewed'):
                if key in remote:item[key]=remote[key]
            changed+=1
        if changed and not store._write(current):raise account.AccountError('云端复习进度未能写入本机，请检查磁盘空间后重试。')
    return changed

def sync_once():
    if not _RUN.acquire(blocking=False):return {'state':'busy','message':'已有同步正在进行。'}
    try:
        user=account.current_user();session=account.token()
        if not user or not session:
            _state('signed-out','当前未登录，使用自己的 API；云端同步未启用。');return status()
        with _LOCK:
            data=_load()
            if not data.get('enabled',True):
                _state('paused','这台设备的自动同步已暂停。');return status()
            if data.get('account_id') and data['account_id']!=user['id']:
                _state('account-mismatch','本机资料关联了另一个账户。请在用户中心确认关联后再同步。');return status()
            if not data.get('account_id'):
                data.update(account_id=user['id'],device_id=data.get('device_id') or uuid.uuid4().hex);_save(data)
        def same_account():
            current=account.current_user()
            if session!=account.token() or not current or current['id']!=user['id']:raise account.AccountError('账户已切换，本次同步已停止。')
        _state('syncing','正在同步学习档案与复习进度…')
        remote=account.request('/v1/me/sync',timeout=40,max_bytes=4*1024*1024,auth_token=session)
        same_account()
        if remote.get('account_id')!=user['id'] or remote.get('protocol')!='echo.sync/1':raise account.AccountError('同步账户响应不匹配，未上传资料。')
        if not remote.get('preferences',{}).get('auto_sync',True):
            _state('paused','账户已在网页暂停自动同步，可在网页账户设置中恢复。');return status()
        # The account can change while the HTTP request runs. Check before local mutation.
        same_account();restored,source_knowledge=_restore_sources(data,remote,user['id'],session,same_account)
        incoming=remote.get('reviews',[])
        if data.get('mode','merge')=='selected':
            local_ids={p['id'] for p in learning_export.build_export(exclude_cloud=True).get('knowledge_points',[])}
            incoming=[r for r in incoming if r.get('knowledge_id') in source_knowledge|local_ids]
        merged=_apply_reviews(incoming)
        ambiguous=len(_ambiguous_topics(incoming))
        profile=learning_export.build_export(exclude_cloud=True)
        classroom=cloud_archive.build(exclude_cloud=True)
        stable={'profile':dict(profile),'classroom':classroom};stable['profile'].pop('exported_at',None)
        content_hash=hashlib.sha256(json.dumps(stable,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        device=next((r for r in remote.get('devices',[]) if r['id']==data['device_id']),None)
        with _LOCK:latest=_load()
        result={'updated':device['updated'] if device else 0,'revision':device['revision'] if device else 0}
        if not device or latest.get('content_hash')!=content_hash or ('name' in device and device['name']!=data.get('device_name','Echo Desktop')):
            same_account()
            result=account.request('/v1/me/sync',{'protocol':'echo.sync/1','account_id':user['id'],'device_id':data['device_id'],'device_name':data.get('device_name','Echo Desktop'),'base_revision':device['revision'] if device else 0,'profile':profile,'classroom':classroom,'consent':True},timeout=45,max_bytes=65536,auth_token=session)
            same_account()
        with _LOCK:
            latest=_load()
            # Do not resurrect a local pause or account rebind that happened in flight.
            if latest.get('account_id')!=user['id'] or not latest.get('enabled',True):return status()
            latest.update(content_hash=content_hash,last_success=int(time.time()),revision=result['revision'],devices=remote.get('devices',[]),devices_account=user['id']);_save(latest)
        _state('synced',f'学习档案已同步，已载入 {restored} 节其他终端课堂回顾。'+(f'已合并 {merged} 条云端复习进度。' if merged else '网页复习与本机保持连接。')+(f'{ambiguous} 个跨学科同名知识点的复习保留在网页，避免覆盖本机旧格式记录。' if ambiguous else ''))
        return status()
    except Exception as exc:
        _state('error',str(exc) if isinstance(exc,(account.AccountError,ValueError,OSError)) else '同步未完成，请稍后重试。')
        return status()
    finally:_RUN.release()
