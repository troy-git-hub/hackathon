"""Echo account client. Session tokens use the operating system credential vault."""
import json
import os
import urllib.request
import urllib.error
import uuid
import copy

API_ORIGIN = 'https://api.echo.xhbtroy.cn'
USER_CENTER = 'https://echo.xhbtroy.cn/user'
_token = ''
_user = None

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
def managed_models():
    if os.getenv('ECHO_ACCOUNT_GUEST')=='1':return False
    active=bool(_token) or os.getenv('ECHO_ACCOUNT_ACTIVE')=='1'
    return active and (not _token or os.getenv('ECHO_ACCOUNT_CUSTOM_API','0') != '1')

def request(path, data=None, timeout=25, max_bytes=262144, auth_token=None):
    if not path.startswith('/v1/') or '..' in path: raise AccountError('账户请求路径无效。')
    headers={'Content-Type':'application/json','X-Echo-CSRF':'1','User-Agent':'Echo-Desktop/Account-1'}
    session=_token if auth_token is None else auth_token
    if session: headers['Authorization']='Bearer '+session
    req=urllib.request.Request(API_ORIGIN+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req,timeout=timeout) as reply:
            raw=reply.read(max_bytes+1)
        if len(raw)>max_bytes: raise AccountError('账户服务响应过大。')
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        try:detail=json.loads(e.read(65536)).get('detail')
        except (ValueError,AttributeError):detail=None
        raise AccountError(detail if isinstance(detail,str) else '账户请求未完成，请稍后重试。',e.code) from None
    except (urllib.error.URLError,TimeoutError,OSError):
        raise AccountError('无法连接 Echo 账户服务，请检查网络后重试。') from None

def _save():
    try:
        import keyring
        keyring.set_password(_vault_service(),'session',_token)
        return True
    except Exception:return False

def restore():
    global _token, _user
    try:
        import keyring
        _token=keyring.get_password(_vault_service(),'session') or ''
    except Exception:_token=''
    if not _token:return None
    try:
        _user=request('/v1/me')['user']
        return current_user()
    except AccountError:
        _token='';_user=None
        return None

def login(email, code='', password='', invite='', name=''):
    global _token,_user
    data={'email':email,'client':'desktop'}
    if invite:
        data.update(code=code,invite=invite,name=name,password=password,confirm_password=password)
        endpoint='/v1/auth/register'
    else:
        data.update(code=code,password=password)
        endpoint='/v1/auth/login'
    result=request(endpoint,data)
    _token=result['token'];_user=result['user']
    os.environ['ECHO_ACCOUNT_GUEST']='0';os.environ['ECHO_ACCOUNT_ACTIVE']='1'
    _save()
    return current_user()

def refresh():
    global _user
    _user=request('/v1/me')['user']
    return current_user()

def send_code(email,invite=''):
    return request('/v1/auth/code',{'email':email,'purpose':'register' if invite else 'login','invite':invite},timeout=45)

def inference(task,context,request_id=None,purpose=None):
    global _user
    if not _token or not _user:raise AccountError('请先登录 Echo 账户。')
    identity=_user['id'];session_token=_token
    from echo.backend.request_purpose import infer
    body={'protocol':'echo.inference/2','account_id':identity,'request_id':request_id or uuid.uuid4().hex,'task':task,'purpose':purpose or infer('vision' if task=='vision' else 'assistant'),'context':copy.deepcopy(context)}
    try:result=request('/v1/echo/inference',body,timeout=60,max_bytes=2*1024*1024,auth_token=session_token)
    except AccountError as exc:
        if exc.status_code is not None:raise
        # A transport retry reuses its original ID; it cannot debit twice.
        result=request('/v1/echo/inference',body,timeout=60,max_bytes=2*1024*1024,auth_token=session_token)
    if _token!=session_token or not _user or _user['id']!=identity:raise AccountError('当前账户已变化，请重新提问。')
    if result.get('protocol') not in ('echo.inference/1','echo.inference/2') or result.get('account',{}).get('id')!=identity:raise AccountError('Echo 账户响应不匹配。')
    _user=dict(_user,balance=result['account']['balance'])
    return result['result']

def logout():
    global _token,_user
    try:request('/v1/auth/logout',{})
    except AccountError:pass
    _token='';_user=None
    try:
        import keyring
        keyring.delete_password(_vault_service(),'session')
    except Exception:pass
