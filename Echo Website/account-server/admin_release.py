"""Safe model metadata, pricing, and invite-entitled private beta downloads."""
import json,os,re
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
from fastapi import Request,Response
import billing

def install(app,core):
    db=core['db'];auth=core['session_user'];fail=core['fail']
    @app.get('/v1/admin/models')
    def models(request:Request):
        auth(request,True);items=[]
        for task,prefix in [('text','ECHO_TEXT'),('vision','ECHO_VISION')]:
            url=urlsplit(os.environ.get(prefix+'_ORIGIN',''))
            safe=urlunsplit((url.scheme,url.hostname+(':'+str(url.port) if url.port else '') if url.hostname else '',url.path,'',''))
            items.append({'task':task,'name':'默认文字 API' if task=='text' else '默认视觉 API','model':os.environ.get(prefix+'_MODEL',''),'origin':safe,'key_configured':bool(os.environ.get(prefix+'_KEY'))})
        with db() as c:price=billing.public_pricing(c)
        return {'models':items,'billing':price,'purposes':[{'id':k,'label':v,'task':'vision' if k=='vision' else 'text'} for k,v in billing.PURPOSES.items()]}

    @app.post('/v1/admin/billing')
    async def change_pricing(request:Request):
        user=auth(request,True);data=await core['payload'](request)
        try:incoming=billing.units(data.get('input_points_per_1000'));outgoing=billing.units(data.get('output_points_per_1000'))
        except ValueError as exc:fail(400,str(exc))
        if not 1<=incoming<=1000000 or not 1<=outgoing<=1000000:fail(400,'每千 token 的价格须介于 0.001 和 1000 学习点。')
        with db(True) as c:
            c.execute("UPDATE billing_settings SET value=? WHERE key='input_rate'",(incoming,));c.execute("UPDATE billing_settings SET value=? WHERE key='output_rate'",(outgoing,))
            core['audit'](c,user['id'],'token-pricing-changed',{'input':billing.points(incoming),'output':billing.points(outgoing)})
        return {'ok':True}

    def manifest(required=True):
        root=Path(os.environ.get('ECHO_BETA_DIR','/releases'))
        try:
            path=root/'beta.json'
            if path.stat().st_size>32768:raise ValueError()
            item=json.loads(path.read_text(encoding='utf-8'))
            if not re.fullmatch(r'Echo-Beta-(?:\d+\.\d+\.\d+-windows-x64\.zip|Setup-\d+\.\d+\.\d+\.exe)',item['filename']) or not re.fullmatch(r'\d+\.\d+\.\d+',item['version']) or not re.fullmatch(r'[a-f0-9]{64}',item['sha256']):raise ValueError()
            if type(item['size'])!=int or item['size']<=0 or (root/item['filename']).stat().st_size!=item['size']:raise ValueError()
            return item
        except (OSError,ValueError,KeyError,TypeError):
            if required:fail(503,'内测版本正在准备，请稍后重试。')
            return None
    def entitled(user):
        if user['role']=='admin':return True
        with db() as c:return c.execute("SELECT 1 FROM invitations WHERE used_by=? AND kind='register' AND disabled=0",(user['id'],)).fetchone() is not None

    @app.get('/v1/public/beta')
    def beta_public():
        item=manifest(False)
        return {'available':bool(item),'version':item['version'] if item else None,'requires_invite':True,'channel':'beta'}

    @app.get('/v1/beta/release')
    def beta_release(request:Request):
        user=auth(request)
        if not entitled(user):fail(403,'内测下载仅对持有注册邀请码的账户开放，请先用邀请码注册登录。')
        item=manifest()
        return {**item,'download_url':'/api/account/beta/download','channel':'beta','access':'registered-invite'}

    @app.get('/v1/beta/update')
    def beta_update(request:Request):
        user=auth(request)
        if not entitled(user):fail(403,'当前账户没有内测资格。')
        try:paused=json.loads((Path(os.getenv('ECHO_UPDATE_DIR','/update-data'))/'control.json').read_text()).get('paused') is True
        except (OSError,ValueError):paused=False
        if paused:fail(503,'更新分发已暂停，请稍后检查。')
        return manifest()

    @app.post('/v1/beta/verify-invite')
    async def beta_verify(request:Request):
        user=auth(request);core['rate']('beta-invite:'+user['id'],10,3600)
        data=await core['payload'](request);code=core['field'](data,'invite',100)
        with db() as c:row=c.execute("SELECT * FROM invitations WHERE hash=? AND used_by=? AND kind='register' AND disabled=0",(core['digest'](code),user['id'])).fetchone()
        if not row:fail(400,'请使用当前账户注册时的同一个邀请码，不能借用其他账户已用的邀请码。')
        return {'ok':True,'message':'内测邀请码与当前账户一致。'}

    @app.get('/v1/beta/download')
    def beta_download(request:Request):
        user=auth(request)
        if not entitled(user):fail(403,'此账户没有内测下载资格。')
        core['rate']('beta-download:'+user['id'],20,3600)
        item=manifest()
        return Response(b'',headers={'X-Accel-Redirect':'/_protected_echo_beta/'+item['filename'],'Content-Disposition':'attachment; filename="'+item['filename']+'"','Cache-Control':'private, no-store'},media_type='application/octet-stream')

install.__doc__='Register admin and beta routes without exposing secrets.'
