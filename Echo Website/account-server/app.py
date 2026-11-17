"""Echo invite-only accounts. SQLite is private; email bodies and secrets are never logged."""
import os
import re
import json
import time
import hmac
import hashlib
import secrets
import sqlite3
import threading
import base64
import uuid
import asyncio
from urllib.parse import urlsplit
from contextlib import suppress
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import FastAPI, Request, HTTPException, Response
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jsonschema import Draft202012Validator, FormatChecker
import billing
import study
import storage
import qingjuan

PROFILE_SCHEMA=json.loads(Path(__file__).with_name('learning-profile.schema.json').read_text(encoding='utf-8'))
PROFILE_VALIDATOR=Draft202012Validator(PROFILE_SCHEMA,format_checker=FormatChecker())

DB = os.environ.get('ECHO_DB', '/data/accounts.sqlite')
SECRET = os.environ.get('ECHO_AUTH_SECRET', '')
COOKIE = '__Host-echo_session'
ORIGINS = {'https://echo.xhbtroy.cn', 'https://email.xhbtroy.cn', 'https://api.echo.xhbtroy.cn'}
HASHER = PasswordHasher(time_cost=3, memory_cost=32768, parallelism=1)
AUTH_LOCK = threading.Lock()
DUMMY = HASHER.hash(secrets.token_urlsafe(32))

def now(): return int(time.time())
def fail(status, message): raise HTTPException(status, message)
def digest(value): return hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()

def seal(value, purpose):
    key=hmac.new(SECRET.encode(),b'echo-sealed-storage-v1',hashlib.sha256).digest()
    nonce=secrets.token_bytes(12)
    return base64.urlsafe_b64encode(nonce+AESGCM(key).encrypt(nonce,value.encode(),purpose.encode())).decode()

def unseal(value,purpose):
    raw=base64.urlsafe_b64decode(value)
    key=hmac.new(SECRET.encode(),b'echo-sealed-storage-v1',hashlib.sha256).digest()
    return AESGCM(key).decrypt(raw[:12],raw[12:],purpose.encode()).decode()

def password_field(data,key='password'):
    value=data.get(key)
    if not isinstance(value,str) or not 12<=len(value)<=128:fail(400,'密码需要 12 至 128 个字符。')
    return value

@contextmanager
def db(write=False):
    connection = sqlite3.connect(DB, timeout=8, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        if write: connection.execute('BEGIN IMMEDIATE')
        yield connection
        if write: connection.commit()
    except Exception:
        if write: connection.rollback()
        raise
    finally: connection.close()

def initialize():
    if len(SECRET) < 32: raise RuntimeError('ECHO_AUTH_SECRET must contain at least 32 characters')
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'user',password TEXT,balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0),created INTEGER NOT NULL,disabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires INTEGER NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS codes(email TEXT PRIMARY KEY,hash TEXT NOT NULL,purpose TEXT NOT NULL,expires INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS invitations(hash TEXT PRIMARY KEY,label TEXT NOT NULL,email TEXT NOT NULL DEFAULT '',kind TEXT NOT NULL,credits INTEGER NOT NULL,expires INTEGER NOT NULL,used_by TEXT REFERENCES users(id),created INTEGER NOT NULL,disabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL REFERENCES users(id),amount INTEGER NOT NULL,note TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS limits(key TEXT PRIMARY KEY,count INTEGER NOT NULL,reset INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS ledger_user ON ledger(user_id,id);
        CREATE TABLE IF NOT EXISTS inference_requests(user_id TEXT NOT NULL REFERENCES users(id),request_id TEXT NOT NULL,request_hash TEXT NOT NULL,task TEXT NOT NULL,state TEXT NOT NULL,cost INTEGER NOT NULL,result TEXT,error TEXT,created INTEGER NOT NULL,finished INTEGER,PRIMARY KEY(user_id,request_id));
        CREATE TABLE IF NOT EXISTS learning_profiles(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),label TEXT NOT NULL,cipher TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,summary TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS profiles_owner ON learning_profiles(user_id,created);
        CREATE TABLE IF NOT EXISTS mail_deliveries(id TEXT PRIMARY KEY,recipient TEXT NOT NULL,category TEXT NOT NULL,status TEXT NOT NULL,message_id TEXT,error TEXT,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS cloud_preferences(user_id TEXT PRIMARY KEY REFERENCES users(id),daily_goal INTEGER NOT NULL DEFAULT 5,auto_sync INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS cloud_devices(user_id TEXT NOT NULL REFERENCES users(id),id TEXT NOT NULL,name TEXT NOT NULL,cipher TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,revision INTEGER NOT NULL,updated INTEGER NOT NULL,PRIMARY KEY(user_id,id));
        CREATE TABLE IF NOT EXISTS cloud_reviews(user_id TEXT NOT NULL REFERENCES users(id),knowledge_id TEXT NOT NULL,cipher TEXT NOT NULL,updated INTEGER NOT NULL,PRIMARY KEY(user_id,knowledge_id));
        CREATE TABLE IF NOT EXISTS cloud_events(user_id TEXT NOT NULL REFERENCES users(id),id TEXT NOT NULL,knowledge_id TEXT NOT NULL,result TEXT NOT NULL,created INTEGER NOT NULL,PRIMARY KEY(user_id,id));
        CREATE INDEX IF NOT EXISTS cloud_events_date ON cloud_events(user_id,created);
        CREATE TABLE IF NOT EXISTS practice_questions(user_id TEXT NOT NULL REFERENCES users(id),id TEXT NOT NULL,knowledge_id TEXT NOT NULL,cipher TEXT NOT NULL,choice INTEGER,correct INTEGER,created INTEGER NOT NULL,answered INTEGER,PRIMARY KEY(user_id,id));
        ''')
        migrations={'users':{'ai_enabled':'INTEGER NOT NULL DEFAULT 1'},'invitations':{'code_cipher':'TEXT','used_at':'INTEGER'},'ledger':{'reference':'TEXT'},'cloud_devices':{'classroom_cipher':'TEXT'},'practice_questions':{'parent_id':'TEXT'},'inference_requests':{'purpose':"TEXT NOT NULL DEFAULT 'assistant'",'model':"TEXT NOT NULL DEFAULT ''",'api_origin':"TEXT NOT NULL DEFAULT ''",'input_tokens':'INTEGER','output_tokens':'INTEGER','usage_source':'TEXT','input_rate':'INTEGER NOT NULL DEFAULT 100','output_rate':'INTEGER NOT NULL DEFAULT 200'}}
        for table,columns in migrations.items():
            existing={row['name'] for row in c.execute('PRAGMA table_info('+table+')')}
            for name,definition in columns.items():
                if name not in existing:c.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+definition)
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS ledger_reference ON ledger(reference) WHERE reference IS NOT NULL')
    with db(True) as c:billing.initialize(c)
    with db() as c:study.initialize(c)
    with db() as c:qingjuan.initialize(c)
    # Never overwrite a persisted administrator's password during a restart.
    admin = os.environ.get('ECHO_ADMIN_EMAIL', '').strip().lower()
    encoded = os.environ.get('ECHO_ADMIN_PASSWORD_HASH', '')
    if admin and encoded:
        with db(True) as c:
            c.execute("INSERT OR IGNORE INTO users(id,email,name,role,password,created) VALUES(?,?,?,'admin',?,?)", (secrets.token_hex(16), admin, 'Echo 管理员', encoded, now()))
    with db(True) as c:
        c.execute('DELETE FROM sessions WHERE expires<?', (now(),))
        c.execute('DELETE FROM codes WHERE expires<?', (now(),))
        c.execute('DELETE FROM limits WHERE reset<?', (now(),))
        # A single worker is used. Pending calls from a terminated worker cannot finish.
        for item in c.execute("SELECT * FROM inference_requests WHERE state='pending'").fetchall():
            refund_inference(c,item['user_id'],item['request_id'],'服务重启，学习点已返还。')
        c.execute('UPDATE inference_requests SET result=NULL WHERE finished<?',(now()-600,))

@asynccontextmanager
async def lifespan(app):
    initialize()
    async def maintenance():
        while True:
            await asyncio.sleep(60)
            with db(True) as c:
                c.execute('UPDATE inference_requests SET result=NULL WHERE finished<?',(now()-600,))
                c.execute('DELETE FROM codes WHERE expires<?',(now(),))
                c.execute('DELETE FROM audit WHERE created<?',(now()-90*86400,))
                c.execute('DELETE FROM mail_deliveries WHERE created<?',(now()-30*86400,))
                c.execute('DELETE FROM practice_questions WHERE created<?',(now()-90*86400,))
                c.execute('DELETE FROM cloud_events WHERE created<?',(now()-90*86400,))
    task=asyncio.create_task(maintenance())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):await task

app = FastAPI(title='Echo Account API', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

def rate(key, maximum, seconds):
    stamp = now()
    key = digest(key)
    with db(True) as c:
        c.execute('DELETE FROM limits WHERE reset<?', (stamp,))
        row = c.execute('SELECT * FROM limits WHERE key=?', (key,)).fetchone()
        if row and row['count'] >= maximum:
            remaining=max(1,row['reset']-stamp)
            raise HTTPException(429,f'请求太频繁，请在 {remaining} 秒后重试。',headers={'Retry-After':str(remaining)})
        c.execute('INSERT INTO limits(key,count,reset) VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, stamp+seconds))

@app.middleware('http')
async def protect(request, call_next):
    origin = request.headers.get('origin')
    if origin and origin not in ORIGINS:
        return Response('Origin not allowed', 403)
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('x-echo-csrf') != '1':
        return Response('Missing request header', 403)
    max_size = 5*1024*1024 if request.url.path=='/v1/me/study/materials' else 512*1024 if request.url.path.startswith(('/v1/me/study/','/v1/me/qingjuan/')) else 2*1024*1024 if request.url.path in ('/v1/echo/inference','/v1/me/profiles','/v1/me/sync') else 65536
    try:
        if int(request.headers.get('content-length', '0')) > max_size: return Response('Request too large', 413)
    except ValueError: return Response('Bad length', 400)
    upload_slot=False
    if request.url.path=='/v1/me/study/materials' and request.method=='POST':
        try:session_user(request)
        except HTTPException as exc:return Response(json.dumps({'detail':exc.detail}),exc.status_code,media_type='application/json')
        if not study.UPLOAD_REQUEST_SLOTS.acquire(False):return Response(json.dumps({'detail':'资料上传繁忙，请稍后重试。'}),429,media_type='application/json',headers={'Retry-After':'5'})
        upload_slot=True
    try:
        if request.method not in ('GET','HEAD','OPTIONS'):
            chunks=[];size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>max_size:return Response('Request too large',413)
                chunks.append(chunk)
            request._body=b''.join(chunks)
        response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'",'Referrer-Policy':'no-referrer'})
        return response
    finally:
        if upload_slot:study.UPLOAD_REQUEST_SLOTS.release()

def ip(request):
    # Only Nginx/our reverse proxy can reach this container port.
    return request.headers.get('x-real-ip') or request.client.host

async def payload(request):
    try: value = await request.json()
    except Exception: fail(400, '请发送 JSON 请求。')
    if not isinstance(value, dict): fail(400, '请求格式不正确。')
    return value

def field(data, key, maximum=256, required=True):
    value=data.get(key,'')
    if not isinstance(value,str) or len(value)>maximum or (required and not value.strip()): fail(400,'请检查 '+key+'。')
    return value.strip()

def email_address(value):
    if not isinstance(value,str): fail(400,'邮箱格式不正确。')
    value=value.strip().lower()
    if len(value)>254 or not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}',value): fail(400,'邮箱格式不正确。')
    return value

def public_user(row):
    return {**{k:row[k] for k in ('id','email','name','role','created')},'balance':billing.points(row['balance']),'ai_enabled':bool(row['ai_enabled']),'has_password':bool(row['password'])}

def session_user(request, admin=False):
    auth=request.headers.get('authorization','')
    token=auth[7:] if auth.startswith('Bearer ') else request.cookies.get(COOKIE,'')
    if len(token)>256: fail(401,'请重新登录。')
    with db() as c:
        row=c.execute('SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.disabled=0',(digest(token),now())).fetchone()
    if row is None: fail(401,'请先登录 Echo。')
    if admin and row['role']!='admin': fail(403,'此功能仅限管理员。')
    return row

def audit(c, actor, event, detail):
    c.execute('INSERT INTO audit(actor,event,detail,created) VALUES(?,?,?,?)',(actor,event,json.dumps(detail,ensure_ascii=False),now()))

def new_session(c, user, response, desktop=False):
    token=secrets.token_urlsafe(48)
    c.execute('DELETE FROM sessions WHERE expires<?',(now(),))
    c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(digest(token),user['id'],now()+7*86400,now()))
    # Bound the number of active sessions, keeping the most recent eight.
    c.execute('DELETE FROM sessions WHERE user_id=? AND token NOT IN (SELECT token FROM sessions WHERE user_id=? ORDER BY created DESC LIMIT 8)',(user['id'],user['id']))
    response.set_cookie(COOKIE,token,max_age=7*86400,secure=True,httponly=True,samesite='strict',path='/')
    return {'user':public_user(user),**({'token':token} if desktop else {})}

def validate_invite(c, code, email, kind='register'):
    item=c.execute('SELECT * FROM invitations WHERE hash=?',(digest(code),)).fetchone()
    if not item or item['disabled'] or item['used_by'] or item['expires']<=now() or item['kind']!=kind or (item['email'] and item['email']!=email): fail(400,'邀请码或激活码无效、已使用或已过期。')
    return item

def verify_code(c,email,code,purpose,limit=5):
    item=c.execute('SELECT * FROM codes WHERE email=?',(email,)).fetchone()
    return bool(item and item['purpose']==purpose and item['expires']>now() and item['attempts']<limit and hmac.compare_digest(item['hash'],digest(email+':'+purpose+':'+code)))

async def verified_recipients():
    token=os.environ.get('ECHO_MAIL_TOKEN','')
    account=os.environ.get('ECHO_MAIL_ACCOUNT','')
    if not token or not account:return [v.strip().lower() for v in os.environ.get('ECHO_MAIL_VERIFIED','').split(',') if v.strip()]
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r=await client.get(f'https://api.cloudflare.com/client/v4/accounts/{account}/email/routing/addresses?per_page=100',headers={'Authorization':'Bearer '+token})
            data=r.json()
        except (httpx.HTTPError,ValueError):fail(503,'无法检查邮箱验证状态，请稍后重试。')
    if not data.get('success'):fail(503,'无法读取收件人验证状态，请管理员检查邮件凭证。')
    return [item['email'].lower() for item in data.get('result',[]) if item.get('verified')]

async def _deliver_mail(to, subject, text):
    allowed={v.strip().lower() for v in os.environ.get('ECHO_MAIL_VERIFIED','').split(',') if v.strip()}
    if os.environ.get('ECHO_MAIL_MODE','verified')=='verified':
        allowed=await verified_recipients()
    if os.environ.get('ECHO_MAIL_MODE','verified')=='verified' and to not in allowed:
        fail(503,'免费发信模式：此收件邮箱需先在 Cloudflare 完成验证；请联系管理员。')
    token=os.environ.get('ECHO_MAIL_TOKEN','')
    account=os.environ.get('ECHO_MAIL_ACCOUNT','')
    if not token or not account: fail(503,'邮件服务尚未配置。')
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            result=await client.post(f'https://api.cloudflare.com/client/v4/accounts/{account}/email/sending/send',headers={'Authorization':'Bearer '+token},json={'from':'Echo <UserCenter@xhbtroy.cn>','to':to,'subject':subject,'text':text})
            data=result.json()
        except httpx.TimeoutException:fail(503,'邮件服务响应超时，投递状态未知；若稍后收到验证码，仍可在 5 分钟内使用。请勿立即重复申请。')
        except (httpx.HTTPError, ValueError): fail(503,'邮件服务暂时不可用，请稍后重试。')
    if not data.get('success'): fail(503,'邮件服务拒绝发送，请管理员检查收件人验证和发信权限。')
    info=data.get('result') or {}
    if info.get('permanent_bounces') or info.get('suppressed_recipients'): fail(502,'邮件投递失败，请检查收件地址。')
    return {'message_id':info.get('message_id'),'delivered':info.get('delivered',[]),'queued':info.get('queued',[])}

async def send_mail(to, subject, text, category='test'):
    receipt=uuid.uuid4().hex
    try:
        result=await _deliver_mail(to,subject,text)
    except HTTPException as exc:
        with db(True) as c:
            status='unknown' if '状态未知' in str(exc.detail) else 'failed'
            c.execute('INSERT INTO mail_deliveries VALUES(?,?,?,?,?,?,?)',(receipt,to,category,status,None,str(exc.detail)[:300],now()))
        raise
    status='accepted' if result.get('delivered') else 'queued'
    with db(True) as c:
        c.execute('INSERT INTO mail_deliveries VALUES(?,?,?,?,?,?,?)',(receipt,to,category,status,result.get('message_id'),None,now()))
    return {**result,'receipt':receipt,'status':status}

@app.get('/v1/admin/mail/deliveries')
def mail_deliveries(request:Request):
    session_user(request,True)
    with db() as c: rows=c.execute('SELECT * FROM mail_deliveries ORDER BY created DESC LIMIT 100').fetchall()
    return {'items':[dict(row) for row in rows]}

@app.get('/healthz')
def health(): return {'ok':True}

def profile_metadata(row):
    return {k:json.loads(row[k]) if k=='summary' else row[k] for k in ('id','label','size','sha256','summary','created')}

def validate_profile(value):
    if not isinstance(value,dict): fail(400,'请选择 Echo 导出的学习档案 JSON。')
    count=0
    forbidden={'apikey','apikeys','password','token','secret','authorization','rawaudio','screenshots','avatar','providerconfiguration','importeddocuments','htmlcode','lessondetails','lessonsummaries'}
    def walk(item,depth=0):
        nonlocal count
        count+=1
        if depth>25 or count>40000: fail(400,'档案结构过于复杂。')
        if isinstance(item,dict):
            for key,child in item.items():
                normalized=re.sub(r'[^a-z0-9]','',key.lower())
                if normalized in forbidden or normalized.endswith(('apikey','password','secret','token')): fail(400,'档案包含不允许上传的凭证或原始资料字段。')
                walk(child,depth+1)
        elif isinstance(item,list):
            for child in item:walk(child,depth+1)
    walk(value)
    error=next(PROFILE_VALIDATOR.iter_errors(value),None)
    if error:fail(400,'档案不符合 Echo 学习档案格式，请从 Echo 的学习档案导出功能重新导出。')
    try:raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    except (ValueError,TypeError):fail(400,'档案包含无效的 JSON 数值。')
    if len(raw.encode('utf-8'))>1024*1024:fail(413,'单份档案最大 1 MB。')
    return raw

@app.get('/v1/me/profiles')
def list_profiles(request:Request):
    user=session_user(request)
    with db() as c: rows=c.execute('SELECT * FROM learning_profiles WHERE user_id=? ORDER BY created DESC,rowid DESC',(user['id'],)).fetchall()
    return {'items':[profile_metadata(row) for row in rows],'limits':{'count':10,'file_bytes':1048576,'total_bytes':10485760},'used_bytes':sum(row['size'] for row in rows)}

@app.post('/v1/me/profiles')
async def upload_profile(request:Request):
    user=session_user(request)
    rate('profile-upload:'+user['id'],20,3600)
    data=await payload(request)
    if data.get('consent') is not True:fail(400,'请先确认上传这份学习档案。')
    label=field(data,'label',80)
    value=data.get('profile')
    raw=validate_profile(value)
    size=len(raw.encode('utf-8')); ident=uuid.uuid4().hex
    summary={'sections':value['selected_sections'],'exported_at':value['exported_at'],'saved_lessons':value['coverage']['saved_lesson_count']}
    cipher=seal(raw,'profile:'+user['id']+':'+ident)
    with db(True) as c:
        count,total=c.execute('SELECT count(*),coalesce(sum(size),0) FROM learning_profiles WHERE user_id=?',(user['id'],)).fetchone()
        global_total=storage.used(c)
        if count>=10 or total+size>10*1024*1024:fail(409,'云端最多保存 10 份、合计 10 MB，请先删除旧档案。')
        if global_total+size>storage.LIMIT:fail(503,'云端128 MiB存储额度已满，请先删除旧资料。')
        c.execute('INSERT INTO learning_profiles VALUES(?,?,?,?,?,?,?,?)',(ident,user['id'],label,cipher,size,hashlib.sha256(raw.encode()).hexdigest(),json.dumps(summary),now()))
        audit(c,user['id'],'profile-uploaded',{'id':ident,'size':size})
    return {'ok':True,'id':ident}

def owned_profile(request,ident):
    user=session_user(request)
    with db() as c:row=c.execute('SELECT * FROM learning_profiles WHERE id=? AND user_id=?',(ident,user['id'])).fetchone()
    if row is None:fail(404,'档案不存在。')
    return row,user

@app.get('/v1/me/profiles/{ident}')
def read_profile(request:Request,ident:str):
    row,user=owned_profile(request,ident)
    return {**profile_metadata(row),'profile':json.loads(unseal(row['cipher'],'profile:'+user['id']+':'+ident))}

@app.get('/v1/me/profiles/{ident}/download')
def download_profile(request:Request,ident:str):
    row,user=owned_profile(request,ident)
    return Response(unseal(row['cipher'],'profile:'+user['id']+':'+ident),media_type='application/json',headers={'Content-Disposition':'attachment; filename="echo-learning-profile.json"','Cache-Control':'no-store'})

@app.delete('/v1/me/profiles/{ident}')
def delete_profile(request:Request,ident:str):
    row,user=owned_profile(request,ident)
    with db(True) as c:
        c.execute('DELETE FROM learning_profiles WHERE id=? AND user_id=?',(ident,user['id']))
        audit(c,user['id'],'profile-deleted',{'id':ident})
    return {'ok':True}

@app.get('/v1/public/config')
def public_config():
    with db() as c:price=billing.public_pricing(c)
    return {'registration':'invite-only','mail_mode':os.environ.get('ECHO_MAIL_MODE','verified'),'balance_unit':'学习点','payments':False,'password_required':True,'billing':price,'protocol':'echo.inference/2'}

@app.post('/v1/auth/code')
async def request_code(request:Request):
    rate('code-ip:'+ip(request),8,3600)
    data=await payload(request)
    email=email_address(data.get('email'))
    purpose=field(data,'purpose',20)
    if purpose not in ('login','register','password'): fail(400,'验证码用途不正确。')
    rate('code-address:'+email,1,60)
    rate('code-day:'+email,10,86400)
    with db() as c:
        if purpose=='register':
            validate_invite(c,field(data,'invite',100),email)
            if c.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone(): fail(400,'请改用登录。')
        elif not c.execute('SELECT 1 FROM users WHERE email=? AND disabled=0',(email,)).fetchone():
            fail(400,'此邮箱尚未注册或账户不可用，请先使用邀请码注册。')
    code=f'{secrets.randbelow(1000000):06d}'
    # Persist the hash first: the provider can accept a message but time out its reply.
    # A late-arriving email must still contain a usable code. No plaintext is stored.
    subject={'login':'Echo 登录验证码','register':'Echo 注册验证码','password':'Echo 密码设置验证码'}[purpose]
    with db(True) as c:
        c.execute('INSERT INTO codes(email,hash,purpose,expires,attempts) VALUES(?,?,?,?,0) ON CONFLICT(email) DO UPDATE SET hash=excluded.hash,purpose=excluded.purpose,expires=excluded.expires,attempts=0',(email,digest(email+':'+purpose+':'+code),purpose,now()+300))
    receipt=await send_mail(email,subject,f'你的 Echo 验证码是：{code}\n\n5 分钟内有效，请使用最后一次收到的验证码，请勿转发。若非本人操作，请忽略此邮件。',category='otp:'+purpose)
    state='收件服务器已接受邮件' if receipt.get('delivered') else '邮件已提交投递队列'
    return {'ok':True,'receipt':receipt.get('receipt'),'status':receipt.get('status'),'message':state+'，不代表已进入收件箱。请检查垃圾邮件和订阅邮件，5 分钟内使用最新验证码；仍未收到请将回执编号交给管理员：'+(receipt.get('receipt') or '测试模式')}

@app.post('/v1/auth/login')
async def login(request:Request,response:Response):
    rate('login-ip:'+ip(request),15,900)
    data=await payload(request)
    email=email_address(data.get('email'))
    rate('login-account:'+email,10,900)
    password=data.get('password','')
    if not isinstance(password,str) or len(password)>128:fail(400,'密码格式不正确。')
    code=field(data,'code',6,False)
    with db() as c: user=c.execute('SELECT * FROM users WHERE email=? AND disabled=0',(email,)).fetchone()
    valid=False
    if password:
        with AUTH_LOCK:
            try: valid=HASHER.verify(user['password'] if user and user['password'] else DUMMY,password)
            except (VerificationError,InvalidHashError): pass
    else:
        with db(True) as c:
            valid=bool(user and verify_code(c,email,code,'login'))
            c.execute('UPDATE codes SET attempts=attempts+1 WHERE email=?',(email,))
            if valid: c.execute('DELETE FROM codes WHERE email=?',(email,))
    if not valid or not user: fail(401,'邮箱、密码或验证码不正确。')
    with db(True) as c:
        audit(c,user['id'],'login',{'method':'password' if password else 'email-code'})
        return new_session(c,user,response,data.get('client')=='desktop')

@app.post('/v1/auth/register')
async def register(request:Request,response:Response):
    rate('register-ip:'+ip(request),10,3600)
    data=await payload(request)
    email=email_address(data.get('email'))
    name=field(data,'name',40)
    code=field(data,'code',6)
    password=password_field(data)
    if data.get('confirm_password')!=password:fail(400,'两次输入的密码不一致。')
    with db(True) as c:
        valid=verify_code(c,email,code,'register')
        c.execute('UPDATE codes SET attempts=attempts+1 WHERE email=?',(email,))
    if not valid: fail(400,'验证码错误、已过期或尝试过多。')
    with AUTH_LOCK: encoded=HASHER.hash(password)
    with db(True) as c:
        if not verify_code(c,email,code,'register',6): fail(400,'验证码已失效。')
        invite=validate_invite(c,field(data,'invite',100),email)
        ident=secrets.token_hex(16)
        try:c.execute('INSERT INTO users(id,email,name,balance,password,created) VALUES(?,?,?,?,?,?)',(ident,email,name,invite['credits'],encoded,now()))
        except sqlite3.IntegrityError: fail(400,'此邮箱已注册，请登录。')
        c.execute('UPDATE invitations SET used_by=?,used_at=? WHERE hash=?',(ident,now(),invite['hash']))
        c.execute('DELETE FROM codes WHERE email=?',(email,))
        c.execute('INSERT INTO ledger(user_id,amount,note,created) VALUES(?,?,?,?)',(ident,invite['credits'],'注册邀请赠送',now()))
        user=c.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone()
        audit(c,ident,'register',{})
        return new_session(c,user,response,data.get('client')=='desktop')

@app.get('/v1/me')
def me(request:Request): return {'user':public_user(session_user(request))}

@app.get('/v1/me/ledger')
def my_ledger(request:Request):
    user=session_user(request)
    with db() as c:rows=c.execute('SELECT id,amount,note,created FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 100',(user['id'],)).fetchall()
    return {'items':[{**dict(r),'amount':billing.points(r['amount'])} for r in rows]}

@app.post('/v1/me/redeem')
async def redeem(request:Request):
    user=session_user(request)
    rate('redeem:'+user['id'],10,3600)
    data=await payload(request)
    with db(True) as c:
        item=validate_invite(c,field(data,'code',100),user['email'],'credit')
        c.execute('UPDATE invitations SET used_by=?,used_at=? WHERE hash=?',(user['id'],now(),item['hash']))
        c.execute('UPDATE users SET balance=balance+? WHERE id=?',(item['credits'],user['id']))
        c.execute('INSERT INTO ledger(user_id,amount,note,created) VALUES(?,?,?,?)',(user['id'],item['credits'],'激活码赠送',now()))
        audit(c,user['id'],'redeem',{'credits':item['credits']})
    return {'ok':True}

@app.post('/v1/auth/logout')
def logout(request:Request,response:Response):
    token=request.headers.get('authorization','').removeprefix('Bearer ') or request.cookies.get(COOKIE,'')
    with db(True) as c:c.execute('DELETE FROM sessions WHERE token=?',(digest(token),))
    response.delete_cookie(COOKIE,path='/',secure=True,httponly=True,samesite='strict')
    return {'ok':True}

@app.get('/v1/admin/overview')
async def overview(request:Request):
    session_user(request,True)
    with db() as c:
        stats={'users':c.execute('SELECT COUNT(*) FROM users').fetchone()[0],'balance':c.execute('SELECT COALESCE(SUM(balance),0) FROM users').fetchone()[0],'unused_invites':c.execute('SELECT COUNT(*) FROM invitations WHERE used_by IS NULL AND disabled=0 AND expires>?',(now(),)).fetchone()[0]}
        users=c.execute('SELECT id,email,name,role,balance,created,disabled,ai_enabled FROM users ORDER BY created DESC LIMIT 100').fetchall()
        audit_items=c.execute('SELECT event,detail,created FROM audit ORDER BY id DESC LIMIT 50').fetchall()
    try:verified=await verified_recipients();mail_error=''
    except HTTPException:verified=[];mail_error='暂时无法检查邮箱开通状态，请刷新重试。'
    with db() as c:
        stats['ai_requests']=c.execute('SELECT COUNT(*) FROM inference_requests').fetchone()[0]
        stats['consumed_points']=c.execute("SELECT COALESCE(SUM(cost),0) FROM inference_requests WHERE state='succeeded'").fetchone()[0]
    stats['balance']=billing.points(stats['balance']);stats['consumed_points']=billing.points(stats['consumed_points'])
    return {'stats':stats,'users':[{**dict(r),'balance':billing.points(r['balance'])} for r in users],'audit':[dict(r) for r in audit_items],'mail':{'mode':os.environ.get('ECHO_MAIL_MODE','verified'),'sender':'Echo <UserCenter@xhbtroy.cn>','verified_recipients':verified,'error':mail_error}}

@app.post('/v1/admin/mail/verify-recipient')
async def verify_recipient(request:Request):
    user=session_user(request,True)
    rate('verify-mail:'+user['id'],10,3600)
    data=await payload(request)
    email=email_address(data.get('email'))
    token=os.environ.get('ECHO_MAIL_TOKEN','')
    account=os.environ.get('ECHO_MAIL_ACCOUNT','')
    if not token or not account:fail(503,'邮件服务尚未配置。')
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r=await client.get(f'https://api.cloudflare.com/client/v4/accounts/{account}/email/routing/addresses?per_page=100',headers={'Authorization':'Bearer '+token})
            addresses=r.json()
            if not addresses.get('success'):fail(503,'无法读取邮箱验证状态。')
            existing=next((a for a in addresses.get('result',[]) if a['email'].lower()==email),None)
            if existing:return {'ok':True,'message':'此邮箱已验证，可以发信。' if existing.get('verified') else '验证邮件已发送过，请收件人检查收件箱或垃圾邮件并点击验证。'}
            rate('verify-destination:'+email,1,86400)
            r=await client.post(f'https://api.cloudflare.com/client/v4/accounts/{account}/email/routing/addresses',headers={'Authorization':'Bearer '+token},json={'email':email})
            result=r.json()
        except (httpx.HTTPError,ValueError):fail(503,'邮件服务暂时不可用。')
    if not result.get('success'):fail(503,'无法创建收件邮箱验证，请检查服务权限。')
    with db(True) as c:audit(c,user['id'],'mail-verification-requested',{'email':email})
    return {'ok':True,'message':'验证邮件已发出。请收件人点击 Cloudflare 验证链接，再发送测试邮件。'}

@app.post('/v1/admin/invitations')
async def create_invite(request:Request):
    user=session_user(request,True)
    rate('invite-create:'+user['id'],30,3600)
    data=await payload(request)
    kind=data.get('kind','register')
    if kind not in ('register','credit'):fail(400,'无效的激活码类型。')
    credits=data.get('credits',0);days=data.get('days',7)
    try:credits=billing.units(credits)
    except ValueError as exc:fail(400,str(exc))
    if not 0<=credits<=1000000000 or type(days)!=int or not 1<=days<=365:fail(400,'额度或有效期不正确。')
    email=email_address(data['email']) if data.get('email') else ''
    label=field(data,'label',80,False)
    code='ECHO-'+secrets.token_urlsafe(18)
    with db(True) as c:
        code_hash=digest(code)
        c.execute('INSERT INTO invitations(hash,label,email,kind,credits,expires,created,code_cipher) VALUES(?,?,?,?,?,?,?,?)',(code_hash,label,email,kind,credits,now()+days*86400,now(),seal(code,'invite:'+code_hash)))
        audit(c,user['id'],'invitation-created',{'kind':kind,'credits':credits,'email':email})
    return {'code':code,'kind':kind,'credits':billing.points(credits),'expires':now()+days*86400,'message':'已保存，可在后台码列表查看状态。'}

@app.post('/v1/admin/mail/test')
async def mail_test(request:Request):
    user=session_user(request,True)
    rate('mail-admin:'+user['id'],5,3600)
    rate('mail-global-day',30,86400)
    data=await payload(request)
    to=email_address(data.get('to'))
    subject=field(data,'subject',160)
    text=field(data,'text',50000)
    if '\n' in subject or '\r' in subject:fail(400,'邮件标题不能换行。')
    info=await send_mail(to,subject,text)
    with db(True) as c:audit(c,user['id'],'mail-test',{'to':to,'subject':subject,'message_id':info['message_id'],'queued':bool(info['queued'])})
    return {'ok':True,**info}

@app.post('/v1/admin/password')
async def change_admin_password(request:Request):
    user=session_user(request,True)
    rate('admin-password:'+user['id'],5,3600)
    data=await payload(request)
    current=data.get('current_password','')
    if not isinstance(current,str) or not current or len(current)>128:fail(400,'请填写当前密码。')
    new=password_field(data,'new_password')
    with AUTH_LOCK:
        try:valid=HASHER.verify(user['password'] or DUMMY,current)
        except (VerificationError,InvalidHashError):valid=False
        if not valid:fail(401,'当前密码不正确。')
        encoded=HASHER.hash(new)
    auth=request.headers.get('authorization','')
    current_token=auth[7:] if auth.startswith('Bearer ') else request.cookies.get(COOKIE,'')
    with db(True) as c:
        c.execute('UPDATE users SET password=? WHERE id=?',(encoded,user['id']))
        c.execute('DELETE FROM sessions WHERE user_id=? AND token<>?',(user['id'],digest(current_token)))
        audit(c,user['id'],'admin-password-changed',{})
    return {'ok':True}

# Extended account controls and Echo-specific inference protocol.
@app.get('/v1/admin/invitations')
def list_invitations(request:Request,kind:str='',status:str='',q:str='',page:int=1):
    session_user(request,True)
    if kind not in ('','register','credit') or status not in ('','unused','used','expired','disabled') or not 1<=page<=10000 or len(q)>100:fail(400,'筛选条件不正确。')
    clauses=[];args=[]
    if kind:clauses.append('i.kind=?');args.append(kind)
    if q:
        clauses.append('(i.label LIKE ? OR i.email LIKE ? OR u.email LIKE ? OR i.hash=?)')
        args.extend(['%'+q+'%']*3+[digest(q)])
    conditions={'unused':'i.used_by IS NULL AND i.disabled=0 AND i.expires>?','used':'i.used_by IS NOT NULL','expired':'i.used_by IS NULL AND i.disabled=0 AND i.expires<=?','disabled':'i.used_by IS NULL AND i.disabled=1'}
    if status:
        clauses.append(conditions[status])
        if status in ('unused','expired'):args.append(now())
    where=' WHERE '+' AND '.join(clauses) if clauses else ''
    query=' FROM invitations i LEFT JOIN users u ON u.id=i.used_by'
    with db() as c:
        total=c.execute('SELECT COUNT(*)'+query+where,args).fetchone()[0]
        rows=c.execute('SELECT i.*,u.email AS used_email,u.name AS used_name'+query+where+' ORDER BY i.created DESC,i.hash LIMIT 50 OFFSET ?',args+[(page-1)*50]).fetchall()
    items=[]
    for row in rows:
        state='used' if row['used_by'] else 'disabled' if row['disabled'] else 'expired' if row['expires']<=now() else 'unused'
        code=None
        if row['code_cipher']:
            try:code=unseal(row['code_cipher'],'invite:'+row['hash'])
            except Exception:pass
        items.append({'id':row['hash'],'code':code,'label':row['label'],'email':row['email'],'kind':row['kind'],'credits':billing.points(row['credits']),'expires':row['expires'],'created':row['created'],'status':state,'used_email':row['used_email'],'used_name':row['used_name'],'used_at':row['used_at']})
    return {'items':items,'total':total,'page':page,'page_size':50}

@app.post('/v1/admin/invitations/{ident}/revoke')
def revoke_invite(ident:str,request:Request):
    admin=session_user(request,True)
    with db(True) as c:
        row=c.execute('SELECT * FROM invitations WHERE hash=?',(ident,)).fetchone()
        if not row:fail(404,'找不到此码。')
        if row['used_by']:fail(400,'此码已使用，不能再次修改或兑换。')
        c.execute('UPDATE invitations SET disabled=1 WHERE hash=?',(ident,))
        audit(c,admin['id'],'invitation-revoked',{'id':ident})
    return {'ok':True}

@app.post('/v1/admin/invitations/{ident}/replace')
def replace_invite(ident:str,request:Request):
    admin=session_user(request,True)
    rate('invite-create:'+admin['id'],30,3600)
    code='ECHO-'+secrets.token_urlsafe(18);code_hash=digest(code)
    with db(True) as c:
        old=c.execute('SELECT * FROM invitations WHERE hash=?',(ident,)).fetchone()
        if not old or old['used_by'] or old['disabled'] or old['expires']<=now():fail(400,'只能补发未使用且仍有效的码。')
        c.execute('UPDATE invitations SET disabled=1 WHERE hash=?',(ident,))
        c.execute('INSERT INTO invitations(hash,label,email,kind,credits,expires,created,code_cipher) VALUES(?,?,?,?,?,?,?,?)',(code_hash,(old['label'] or '')[:72]+'（补发）',old['email'],old['kind'],old['credits'],old['expires'],now(),seal(code,'invite:'+code_hash)))
        audit(c,admin['id'],'invitation-reissued',{'previous_id':ident,'new_id':code_hash})
    return {'code':code,'message':'旧码已停用，请把新码重新发给受邀人。'}

@app.get('/v1/admin/users')
def list_users(request:Request,q:str='',page:int=1):
    session_user(request,True)
    if len(q)>100 or not 1<=page<=10000:fail(400,'查询条件不正确。')
    with db() as c:
        args=['%'+q+'%']*2
        total=c.execute('SELECT COUNT(*) FROM users WHERE email LIKE ? OR name LIKE ?',args).fetchone()[0]
        users=c.execute('SELECT id,email,name,role,balance,created,disabled,ai_enabled FROM users WHERE email LIKE ? OR name LIKE ? ORDER BY created DESC,id LIMIT 50 OFFSET ?',args+[(page-1)*50]).fetchall()
    return {'items':[{**dict(r),'balance':billing.points(r['balance'])} for r in users],'total':total,'page':page}

@app.post('/v1/admin/users/{ident}/access')
async def user_access(ident:str,request:Request):
    admin=session_user(request,True)
    data=await payload(request)
    disabled=data.get('disabled');enabled=data.get('ai_enabled')
    if type(disabled)!=bool or type(enabled)!=bool:fail(400,'账户权限设置不正确。')
    if ident==admin['id'] and disabled:fail(400,'不能停用当前管理员自己。')
    with db(True) as c:
        if not c.execute('SELECT 1 FROM users WHERE id=?',(ident,)).fetchone():fail(404,'找不到用户。')
        c.execute('UPDATE users SET disabled=?,ai_enabled=? WHERE id=?',(int(disabled),int(enabled),ident))
        if disabled:c.execute('DELETE FROM sessions WHERE user_id=?',(ident,))
        audit(c,admin['id'],'user-access-changed',{'user_id':ident,'disabled':disabled,'ai_enabled':enabled})
    return {'ok':True}

@app.post('/v1/admin/users/{ident}/sessions/revoke')
def revoke_sessions(ident:str,request:Request):
    admin=session_user(request,True)
    if ident==admin['id']:fail(400,'请使用退出登录或修改密码管理自己的会话。')
    with db(True) as c:
        c.execute('DELETE FROM sessions WHERE user_id=?',(ident,))
        audit(c,admin['id'],'user-sessions-revoked',{'user_id':ident})
    return {'ok':True}

@app.post('/v1/admin/users/{ident}/credits')
async def adjust_credits(ident:str,request:Request):
    admin=session_user(request,True)
    rate('credit-adjust:'+admin['id'],30,3600)
    data=await payload(request)
    amount=data.get('amount');note=field(data,'note',120)
    try:amount=billing.units(amount)
    except ValueError as exc:fail(400,str(exc))
    if amount==0 or abs(amount)>1000000000:fail(400,'学习点调整值应非零，最多 100 万。')
    with db(True) as c:
        changed=c.execute('UPDATE users SET balance=balance+? WHERE id=? AND balance+?>=0',(amount,ident,amount))
        if changed.rowcount!=1:fail(400,'用户不存在或余额不足，不能调整为负数。')
        c.execute('INSERT INTO ledger(user_id,amount,note,created) VALUES(?,?,?,?)',(ident,amount,'管理员调整：'+note,now()))
        audit(c,admin['id'],'credits-adjusted',{'user_id':ident,'amount':amount,'note':note})
    return {'ok':True}

@app.get('/v1/admin/mail/recipients')
async def mail_recipients(request:Request):
    session_user(request,True)
    token=os.environ.get('ECHO_MAIL_TOKEN','');account=os.environ.get('ECHO_MAIL_ACCOUNT','')
    if not token or not account:return {'items':[]}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r=await client.get(f'https://api.cloudflare.com/client/v4/accounts/{account}/email/routing/addresses?per_page=100',headers={'Authorization':'Bearer '+token})
            data=r.json()
        except (httpx.HTTPError,ValueError):fail(503,'无法读取收件邮箱状态。')
    if not data.get('success'):fail(503,'无法读取收件邮箱状态。')
    return {'items':[{'email':r['email'],'status':'verified' if r.get('verified') else 'pending','verified_at':r.get('verified'),'created':r.get('created')} for r in data.get('result',[])]}

@app.post('/v1/me/password')
async def member_password(request:Request):
    user=session_user(request)
    rate('member-password:'+user['id'],5,3600)
    data=await payload(request)
    new=password_field(data,'new_password')
    if data.get('confirm_password')!=new:fail(400,'两次输入的新密码不一致。')
    current=data.get('current_password','')
    valid=False
    if isinstance(current,str) and current:
        with AUTH_LOCK:
            try:valid=HASHER.verify(user['password'] or DUMMY,current)
            except (VerificationError,InvalidHashError):pass
    else:
        with db(True) as c:
            valid=verify_code(c,user['email'],field(data,'code',6,False),'password')
            c.execute('UPDATE codes SET attempts=attempts+1 WHERE email=?',(user['email'],))
            if valid:c.execute('DELETE FROM codes WHERE email=?',(user['email'],))
    if not valid:fail(401,'当前密码或密码设置验证码不正确。')
    with AUTH_LOCK:encoded=HASHER.hash(new)
    auth=request.headers.get('authorization','')
    current_token=auth[7:] if auth.startswith('Bearer ') else request.cookies.get(COOKIE,'')
    with db(True) as c:
        c.execute('UPDATE users SET password=? WHERE id=?',(encoded,user['id']))
        c.execute('DELETE FROM sessions WHERE user_id=? AND token<>?',(user['id'],digest(current_token)))
        audit(c,user['id'],'password-changed',{})
    return {'ok':True}

def inference_cost():
    try:return max(1,min(1000,int(os.environ.get('ECHO_INFERENCE_COST','1'))))
    except ValueError:return 1

def refund_inference(c,user_id,request_id,message):
    item=c.execute('SELECT * FROM inference_requests WHERE user_id=? AND request_id=?',(user_id,request_id)).fetchone()
    if not item or item['state']!='pending':return
    c.execute('UPDATE users SET balance=balance+? WHERE id=?',(item['cost'],user_id))
    ref='inference-refund:'+user_id+':'+request_id
    c.execute('INSERT INTO ledger(user_id,amount,note,created,reference) VALUES(?,?,?,?,?)',(user_id,item['cost'],'AI 请求失败返还',now(),ref))
    c.execute("UPDATE inference_requests SET state='failed',error=?,finished=? WHERE user_id=? AND request_id=?",(message,now(),user_id,request_id))

async def call_model(task,context):
    prefix='ECHO_VISION' if task=='vision' else 'ECHO_TEXT'
    origin=os.environ.get(prefix+'_ORIGIN','');key=os.environ.get(prefix+'_KEY','');model=os.environ.get(prefix+'_MODEL','')
    if not origin.startswith('https://') or not key or not model:fail(503,'账户模型服务尚未配置。')
    body={'model':model,'messages':context['messages'],'max_tokens':context.get('max_tokens',1200),'stream':False}
    if urlsplit(origin).hostname=='api.deepseek.com' and model=='deepseek-flash':body['thinking']={'type':'disabled'}
    if task=='vision' and model.startswith('qwen3-vl') and urlsplit(origin).hostname in ('dashscope.aliyuncs.com','dashscope-intl.aliyuncs.com'):body['enable_thinking']=False
    if context.get('response_format')=={'type':'json_object'}:body['response_format']={'type':'json_object'}
    body['temperature']=context.get('temperature',0.3)
    async with httpx.AsyncClient(timeout=50) as client:
        try:r=await client.post(origin.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+key},json=body)
        except httpx.HTTPError:fail(503,'账户模型暂时不可用，学习点将返还。')
    if r.status_code!=200:fail(503,'账户模型暂时不可用，学习点将返还。')
    if len(r.content)>2*1024*1024:fail(502,'模型返回过大。')
    try:result=r.json()
    except ValueError:fail(502,'模型返回格式异常。')
    choices=result.get('choices') if isinstance(result,dict) else None
    message=choices[0].get('message') if isinstance(choices,list) and choices and isinstance(choices[0],dict) else None
    if not isinstance(message,dict) or not isinstance(message.get('content'),str) or not message['content'].strip():fail(502,'模型未返回有效内容。')
    return {'text':message['content'],'finish_reason':choices[0].get('finish_reason','stop'),'usage':result.get('usage',{})}

def inference_reply(c,item,protocol='echo.inference/2'):
    if item['state']=='pending':fail(409,'此请求正在处理，请勿重复提交。')
    if item['state']=='failed':fail(409,'此请求未完成且已返还学习点，请创建新请求重试。')
    if not item['result'] or not item['finished'] or item['finished']<now()-600:fail(409,'此请求已处理，缓存结果已过期，不会重复扣点。')
    result=json.loads(unseal(item['result'],'result:'+item['user_id']+':'+item['request_id']))
    balance=c.execute('SELECT balance FROM users WHERE id=?',(item['user_id'],)).fetchone()[0]
    return {'protocol':protocol,'request_id':item['request_id'],'purpose':item['purpose'],'result':result,'billing':{'input_tokens':item['input_tokens'],'output_tokens':item['output_tokens'],'usage_source':item['usage_source']},'account':{'id':item['user_id'],'balance':billing.points(balance),'charged_points':billing.points(item['cost'])}}

@app.post('/v1/echo/inference')
async def echo_inference(request:Request):
    user=session_user(request)
    data=await payload(request)
    protocol=data.get('protocol')
    if protocol not in ('echo.inference/1','echo.inference/2'):fail(400,'Echo 协议版本不正确。')
    purpose=data.get('purpose','assistant')
    if purpose not in billing.PURPOSES:fail(400,'请求用途不正确。')
    if data.get('account_id')!=user['id']:fail(403,'请求账户与登录会话不一致。')
    request_id=field(data,'request_id',36)
    try:request_id=uuid.UUID(request_id).hex
    except ValueError:fail(400,'请求编号必须是 UUID。')
    task=data.get('task');context=data.get('context')
    if task not in ('text','vision') or not isinstance(context,dict):fail(400,'Echo 请求任务不正确。')
    messages=context.get('messages');length=context.get('max_tokens',1200);temperature=context.get('temperature',0.3)
    if context.get('reasoning_effort','low') not in ('none','low','high','max'):fail(400,'思考强度不正确。')
    output_limit=10000 if purpose=='quiz' and task=='text' else 4096
    if not isinstance(messages,list) or not 1<=len(messages)<=60 or type(length)!=int or not 1<=length<=output_limit or type(temperature) not in (int,float) or not 0<=temperature<=2:fail(400,'模型请求超出限制。')
    for msg in messages:
        if not isinstance(msg,dict) or msg.get('role') not in ('system','user','assistant') or not isinstance(msg.get('content'),(str,list)):fail(400,'消息内容不正确。')
    try:request_hash=digest(json.dumps({'task':task,'purpose':purpose,'context':context},ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')))
    except (ValueError,TypeError):fail(400,'请求数据不正确。')
    rate('ai-user:'+user['id'],15,60);rate('ai-user-day:'+user['id'],200,86400);rate('ai-global-minute',30,60)
    with db(True) as c:
        existing=c.execute('SELECT * FROM inference_requests WHERE user_id=? AND request_id=?',(user['id'],request_id)).fetchone()
        if existing:
            if existing['request_hash']!=request_hash:fail(409,'同一请求编号不能用于不同内容。')
            return inference_reply(c,existing,protocol)
        if c.execute("SELECT COUNT(*) FROM inference_requests WHERE state='pending' AND user_id=?",(user['id'],)).fetchone()[0]>=2 or c.execute("SELECT COUNT(*) FROM inference_requests WHERE state='pending'").fetchone()[0]>=8:
            fail(429,'已有请求正在处理，请稍后再试。')
        context=billing.reserve(c,globals(),user,request_id,request_hash,task,purpose,context)
        c.execute('UPDATE inference_requests SET result=NULL WHERE finished<?',(now()-600,))
    if data.get('stream') is True:
        from model_stream import response
        return response(globals(),user,request_id,task,context,protocol)
    try:
        async with asyncio.timeout(55):result=await call_model(task,context)
        encoded=seal(json.dumps(result,ensure_ascii=False),'result:'+user['id']+':'+request_id)
        with db(True) as c:
            receipt=billing.settle(c,globals(),user['id'],request_id,result,context)
            c.execute("UPDATE inference_requests SET state='succeeded',result=?,finished=? WHERE user_id=? AND request_id=? AND state='pending'",(encoded,now(),user['id'],request_id))
            audit(c,user['id'],'ai-request',{'request_id':request_id,'task':task,'purpose':purpose,**receipt})
            item=c.execute('SELECT * FROM inference_requests WHERE user_id=? AND request_id=?',(user['id'],request_id)).fetchone()
            return inference_reply(c,item,protocol)
    except BaseException as exc:
        with db(True) as c:refund_inference(c,user['id'],request_id,'请求失败，学习点已返还。')
        if isinstance(exc,TimeoutError):fail(504,'模型请求超时，学习点已返还。')
        raise

@app.post('/v1/chat/completions')
def retired_generic_api(request:Request):
    session_user(request)
    fail(410,'此通用接口已关闭，请升级 Echo 客户端使用专用账户协议。')

@app.get('/v1/me/requests')
def member_requests(request:Request):
    user=session_user(request)
    with db() as c:rows=c.execute('SELECT request_id,task,purpose,model,input_tokens,output_tokens,usage_source,state,cost,created,finished FROM inference_requests WHERE user_id=? ORDER BY created DESC LIMIT 100',(user['id'],)).fetchall()
    return {'items':[{**dict(r),'cost':billing.points(r['cost']),'purpose_label':billing.PURPOSES.get(r['purpose'],'通用辅助')} for r in rows]}

@app.get('/v1/admin/requests')
def admin_requests(request:Request):
    session_user(request,True)
    with db() as c:rows=c.execute('SELECT r.request_id,r.task,r.purpose,r.model,r.api_origin,r.input_tokens,r.output_tokens,r.usage_source,r.state,r.cost,r.created,r.finished,u.email FROM inference_requests r JOIN users u ON u.id=r.user_id ORDER BY r.created DESC LIMIT 200').fetchall()
    return {'items':[{**dict(r),'cost':billing.points(r['cost']),'purpose_label':billing.PURPOSES.get(r['purpose'],'通用辅助')} for r in rows]}

from cloud import install as install_cloud
install_cloud(app,globals())
study.install(app,globals())
qingjuan.install(app,globals())
from personal_summary import install as install_personal_summary
install_personal_summary(app,globals())
from admin_release import install as install_admin_release
install_admin_release(app,globals())
from release_manager import install as install_release_manager
install_release_manager(app,globals())
