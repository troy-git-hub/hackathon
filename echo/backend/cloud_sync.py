"""Small, account-bound aggregate sync. Never uploads lessons, credentials or media."""
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
def configure(enabled=None,bind=False):
    with _LOCK:
        data=_load();data.setdefault('device_id',uuid.uuid4().hex)
        if enabled is not None:data['enabled']=bool(enabled)
        if bind:
            user=account.current_user()
            if not user:raise account.AccountError('请先登录再关联本机学习资料。')
            data['account_id']=user['id'];data.pop('content_hash',None)
        _save(data)
def enabled():
    with _LOCK:return _load().get('enabled',True)
def status():
    with _LOCK:
        try:data=_load()
        except account.AccountError as exc:return {**_status,'state':'error','message':str(exc),'enabled':False,'bound_account':None}
        return {**_status,'enabled':data.get('enabled',True),'bound_account':data.get('account_id'),'last_success':data.get('last_success',0)}
def _state(state,message):
    with _LOCK:_status.update(state=state,message=message)
def file_signature():
    result=[]
    for name in ('profile.json','lessons.json','review.json','cloud-sync.json'):
        try:
            info=(Path(paths.config_dir())/name).stat();result.append((name,info.st_mtime_ns,info.st_size))
        except OSError:result.append((name,0,0))
    return tuple(result)

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
                item={'topic':topic,'time':remote.get('time') or stamp or time.time(),'source':'cloud_review','missing':str(remote.get('missing',''))[:2000],'reason':str(remote.get('reason',''))[:2000]}
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
        same_account();incoming=remote.get('reviews',[]);merged=_apply_reviews(incoming)
        ambiguous=len(_ambiguous_topics(incoming))
        profile=learning_export.build_export()
        classroom=cloud_archive.build()
        stable={'profile':dict(profile),'classroom':classroom};stable['profile'].pop('exported_at',None)
        content_hash=hashlib.sha256(json.dumps(stable,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        device=next((r for r in remote.get('devices',[]) if r['id']==data['device_id']),None)
        with _LOCK:latest=_load()
        result={'updated':device['updated'] if device else 0,'revision':device['revision'] if device else 0}
        if not device or latest.get('content_hash')!=content_hash:
            same_account()
            result=account.request('/v1/me/sync',{'protocol':'echo.sync/1','account_id':user['id'],'device_id':data['device_id'],'device_name':'Echo Desktop','base_revision':device['revision'] if device else 0,'profile':profile,'classroom':classroom,'consent':True},timeout=45,max_bytes=65536,auth_token=session)
            same_account()
        with _LOCK:
            latest=_load()
            # Do not resurrect a local pause or account rebind that happened in flight.
            if latest.get('account_id')!=user['id'] or not latest.get('enabled',True):return status()
            latest.update(content_hash=content_hash,last_success=int(time.time()),revision=result['revision']);_save(latest)
        _state('synced','学习档案已同步。'+(f'已合并 {merged} 条云端复习进度。' if merged else '网页复习与本机保持连接。')+(f'{ambiguous} 个跨学科同名知识点的复习保留在网页，避免覆盖本机旧格式记录。' if ambiguous else ''))
        return status()
    except Exception as exc:
        _state('error',str(exc) if isinstance(exc,(account.AccountError,ValueError,OSError)) else '同步未完成，请稍后重试。')
        return status()
    finally:_RUN.release()
