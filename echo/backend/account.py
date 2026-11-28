"""Echo account client. Session tokens use the operating system credential vault."""
import json
import os
import urllib.request
import urllib.error
import uuid
import copy
import hashlib
import logging

API_ORIGIN = 'https://api.echo.xhbtroy.cn'
USER_CENTER = 'https://echo.xhbtroy.cn/user'
_token = ''
_user = None
_persistence_error=''
_restore_message=''

def _vault_service():
    from echo import version
    return 'Echo.Account.Beta' if getattr(version,'CHANNEL','stable')=='beta' else 'Echo.Account'

class AccountError(RuntimeError):
    def __init__(self,message,status_code=None):
        super().__init__(message)
        self.status_code=status_code

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise AccountError('账户服务发生跳转，已停止请求。')

def token(): return _token
def current_user(): return dict(_user) if _user else None
def persistence_error():return _persistence_error
def restore_message():return _restore_message
def managed_models():
    if os.getenv('ECHO_ACCOUNT_GUEST')=='1':return False
    active=bool(_token) or os.getenv('ECHO_ACCOUNT_ACTIVE')=='1'
    return active and (not _token or os.getenv('ECHO_ACCOUNT_CUSTOM_API','0') != '1')

def request(path, data=None, timeout=25, max_bytes=262144, auth_token=None):
    if not path.startswith('/v1/') or '..' in path: raise AccountError('账户请求路径无效。')
    headers={'Content-Type':'application/json','X-Echo-CSRF':'1','User-Agent':'Echo-Desktop/Account-1',
             'Accept-Encoding':'gzip'}
    session=_token if auth_token is None else auth_token
    if session: headers['Authorization']='Bearer '+session
    body=None
    if data is not None:
        # ensure_ascii=False + 紧凑分隔符：中文 body 先省 30-50%，再进 gzip。
        body=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
        if len(body)>8192:
            # 大请求体（学习档案同步、课堂归档）压缩上传；服务端会解压并按原限额校验。
            import gzip as _gzip_mod
            body=_gzip_mod.compress(body,6)
            headers['Content-Encoding']='gzip'
    req=urllib.request.Request(API_ORIGIN+path,data=body,headers=headers)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req,timeout=timeout) as reply:
            raw=reply.read(max_bytes+1)
            if (reply.headers.get('Content-Encoding') or '').strip().lower()=='gzip':
                import gzip as _gzip_mod
                try:raw=_gzip_mod.decompress(raw)
                except OSError:raise AccountError('账户服务返回内容异常，请稍后重试。') from None
        if len(raw)>max_bytes: raise AccountError('账户服务响应过大。')
        try:return json.loads(raw)
        except (ValueError,TypeError):raise AccountError('账户服务返回内容异常，请稍后重试；登录凭据不会因此删除。') from None
    except urllib.error.HTTPError as e:
        try:detail=json.loads(e.read(65536)).get('detail')
        except (ValueError,AttributeError):detail=None
        raise AccountError(detail if isinstance(detail,str) else '账户请求未完成，请稍后重试。',e.code) from None
    except (urllib.error.URLError,TimeoutError,OSError):
        raise AccountError('无法连接 Echo 账户服务，请检查网络后重试。') from None

def _save():
    global _persistence_error
    if not _token or not _user:return False
    service=_vault_service();record={'schema':'echo.account/1','service':service,'session':_token,
        'user':{k:v for k,v in _user.items() if k in ('id','email','name','balance','role')}}
    saved=False
    try:
        import keyring
        keyring.set_password(service,'session',_token)
        saved=True
        keyring.set_password(service,'identity',json.dumps({'token_hash':hashlib.sha256(_token.encode()).hexdigest(),'user':record['user']}))
    except Exception as exc:logging.getLogger('echo.account').warning('Credential vault save failed (%s)',type(exc).__name__)
    try:
        from echo.backend import credential_backup
        credential_backup.save(service,record);saved=True
    except Exception as exc:logging.getLogger('echo.account').warning('Protected credential backup unavailable (%s)',type(exc).__name__)
    _persistence_error='' if saved else '已登录，但系统安全存储未能保存会话；本次可以使用，关闭后可能需要重新登录。'
    return saved


def _clear_saved():
    for name in ('session','identity'):
        try:
            import keyring
            keyring.delete_password(_vault_service(),name)
        except Exception:pass
    try:
        from echo.backend import credential_backup
        credential_backup.clear(_vault_service())
    except OSError:logging.getLogger('echo.account').warning('Could not clear protected credential backup')

def restore():
    global _token, _user,_restore_message
    _restore_message=''
    _token='';_user=None
    cached=None;service=_vault_service()
    try:
        import keyring
        _token=keyring.get_password(service,'session') or ''
        raw=keyring.get_password(service,'identity')
        if raw and _token:
            identity=json.loads(raw)
            if identity.get('token_hash')==hashlib.sha256(_token.encode()).hexdigest():cached=identity.get('user')
    except Exception:pass
    try:
        from echo.backend import credential_backup
        record=credential_backup.load(service)
        if record and record.get('schema')=='echo.account/1' and record.get('service')==service:
            if not _token:_token=record.get('session') or ''
            if record.get('session')==_token:cached=record.get('user') or cached
    except Exception as exc:logging.getLogger('echo.account').warning('Protected credential restore unavailable (%s)',type(exc).__name__)
    if not _token:return None
    try:
        _user=request('/v1/me')['user']
        _save()
        return current_user()
    except AccountError as exc:
        if exc.status_code in (401,403):
            _restore_message='保存的登录已过期或被服务端撤销，请重新登录。'
            _token='';_user=None;_clear_saved();return None
        if isinstance(cached,dict) and cached.get('id'):
            _user=dict(cached,_session_offline=True)
            return current_user()
        _user=None
        raise AccountError('暂时无法验证登录状态，已保留登录凭据。请点“重试连接”，不需要重新输入密码。',exc.status_code) from None

def login(email, code='', password='', invite='', name='',totp='',recovery_code=''):
    global _token,_user
    data={'email':email,'client':'desktop'}
    if invite:
        data.update(code=code,invite=invite,name=name,password=password,confirm_password=password)
        endpoint='/v1/auth/register'
    else:
        data.update(code=code,password=password,totp=totp,recovery_code=recovery_code)
        endpoint='/v1/auth/login'
    result=request(endpoint,data)
    _token=result['token'];_user=result['user']
    os.environ['ECHO_ACCOUNT_GUEST']='0';os.environ['ECHO_ACCOUNT_ACTIVE']='1'
    _save()
    return current_user()

def refresh():
    global _user
    _user=request('/v1/me')['user']
    _save()
    return current_user()

def send_code(email,invite=''):
    return request('/v1/auth/code',{'email':email,'purpose':'register' if invite else 'login','invite':invite},timeout=45)

def inference(task,context,request_id=None,purpose=None):
    global _user
    if not _token or not _user:raise AccountError('请先登录 Echo 账户。')
    identity=_user['id'];session_token=_token
    from echo.backend.request_purpose import infer
    body={'protocol':'echo.inference/2','account_id':identity,'request_id':request_id or uuid.uuid4().hex,'task':task,'purpose':purpose or infer('vision' if task=='vision' else 'assistant'),'context':copy.deepcopy(context)}
    timeout=115 if task=='vision' else 65
    try:result=request('/v1/echo/inference',body,timeout=timeout,max_bytes=2*1024*1024,auth_token=session_token)
    except AccountError as exc:
        if exc.status_code is not None:raise
        # A transport retry reuses its original ID; it cannot debit twice.
        result=request('/v1/echo/inference',body,timeout=timeout,max_bytes=2*1024*1024,auth_token=session_token)
    if _token!=session_token or not _user or _user['id']!=identity:raise AccountError('当前账户已变化，请重新提问。')
    if result.get('protocol') not in ('echo.inference/1','echo.inference/2') or result.get('account',{}).get('id')!=identity:raise AccountError('Echo 账户响应不匹配。')
    _user=dict(_user,balance=result['account']['balance'])
    return result['result']

def logout():
    global _token,_user
    try:request('/v1/auth/logout',{})
    except AccountError:pass
    _token='';_user=None
    _clear_saved()


def inference_stream(task,context,purpose=None):
    """Yield real upstream events. Never replay a partially displayed answer."""
    global _user
    if not _token or not _user:raise AccountError('请先登录 Echo 账户。')
    identity=_user['id'];session=_token
    from echo.backend.request_purpose import infer
    body={'protocol':'echo.inference/2','account_id':identity,'request_id':uuid.uuid4().hex,
          'task':task,'purpose':purpose or infer('vision' if task=='vision' else 'assistant'),
          'context':copy.deepcopy(context),'stream':True}
    headers={'Content-Type':'application/json','Accept':'text/event-stream','X-Echo-CSRF':'1',
             'Authorization':'Bearer '+session,'User-Agent':'Echo-Desktop/Account-2'}
    body_bytes=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()
    if len(body_bytes)>8192:
        # 长 context / vision 图片的流式请求同样压缩上传（>8KB）；
        # 服务端安全中间件会解压后按原限额校验，与 request() 同一链路。
        import gzip as _gzip_mod
        body_bytes=_gzip_mod.compress(body_bytes,6)
        headers['Content-Encoding']='gzip'
    req=urllib.request.Request(API_ORIGIN+'/v1/echo/inference',data=body_bytes,headers=headers)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req,timeout=130 if task=='vision' else 100) as reply:
            if 'text/event-stream' not in reply.headers.get('Content-Type',''):
                raise AccountError('账户服务暂未支持流式回答，请稍后重试。')
            event='';size=0;completed=False
            for raw in reply:
                size+=len(raw)
                if size>4*1024*1024:raise AccountError('账户响应内容过大。')
                if _token!=session or not _user or _user['id']!=identity:
                    raise AccountError('当前账户已变化，请重新提问。')
                line=raw.decode('utf-8').strip()
                if line.startswith('event:'):event=line[6:].strip()
                elif line.startswith('data:'):
                    value=json.loads(line[5:])
                    if event=='error':raise AccountError(value.get('detail','生成未完成，请重试。'))
                    if event=='done':
                        if value.get('account',{}).get('id')!=identity:raise AccountError('账户响应不匹配。')
                        _user=dict(_user,balance=value['account']['balance']);completed=True
                    yield event,value
            if not completed:raise AccountError('连接已中断，回答尚未完成，请重试。')
    except urllib.error.HTTPError as exc:
        try:detail=json.loads(exc.read(65536)).get('detail')
        except (ValueError,AttributeError):detail=None
        raise AccountError(detail if isinstance(detail,str) else '账户请求未完成，请重试。',exc.code) from None
    except (urllib.error.URLError,TimeoutError,OSError):
        raise AccountError('连接中断或超时，请检查网络后重试。') from None
