"""Isolated security/transaction tests. Never reads the production database or sends mail."""
import os
import re
import tempfile
import unittest
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

os.environ['ECHO_AUTH_SECRET']='test-secret-which-is-long-enough-for-isolated-tests'
os.environ.pop('ECHO_ADMIN_EMAIL',None)
import app
from fastapi.testclient import TestClient

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='echo-accounts-test-')
        app.DB=self.folder.name+'/test.sqlite'
        self.admin_password='isolated-admin-passphrase'
        os.environ['ECHO_ADMIN_EMAIL']='admin@example.com'
        os.environ['ECHO_ADMIN_PASSWORD_HASH']=app.HASHER.hash(self.admin_password)
        self.client=TestClient(app.app,base_url='https://echo.xhbtroy.cn',headers={'X-Echo-CSRF':'1'})
        self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.folder.cleanup()
    def admin(self):
        r=self.client.post('/v1/auth/login',json={'email':'admin@example.com','password':self.admin_password})
        self.assertEqual(r.status_code,200,r.text)
        self.assertIn('HttpOnly',r.headers['set-cookie'])
        self.assertIn('Secure',r.headers['set-cookie'])
    def invite(self,kind='register',credits=75):
        self.admin()
        r=self.client.post('/v1/admin/invitations',json={'kind':kind,'credits':credits,'days':7})
        self.assertEqual(r.status_code,200,r.text)
        code=r.json()['code']
        self.client.post('/v1/auth/logout',json={})
        return code
    def signup(self,email,invite):
        mocked=AsyncMock(return_value={})
        with patch.object(app,'send_mail',mocked):
            r=self.client.post('/v1/auth/code',json={'email':email,'purpose':'register','invite':invite})
        self.assertEqual(r.status_code,200,r.text)
        code=re.search(r'\d{6}',mocked.call_args.args[2]).group()
        return self.client.post('/v1/auth/register',json={'email':email,'code':code,'invite':invite,'name':'测试用户','password':'student-fixture-password','confirm_password':'student-fixture-password','role':'admin','balance':999999})
    def test_invite_registration_credit_and_roles(self):
        invite=self.invite()
        r=self.signup('student@example.com',invite)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['user']['balance'],75)
        self.assertEqual(r.json()['user']['role'],'user')
        self.assertEqual(self.client.get('/v1/admin/overview').status_code,403)
        self.assertEqual(self.client.post('/v1/admin/mail/test',json={'to':'x@example.com','subject':'x','text':'x'}).status_code,403)
        self.assertEqual(len(self.client.get('/v1/me/ledger').json()['items']),1)
        self.client.post('/v1/auth/logout',json={})
        self.assertEqual(self.client.get('/v1/me').status_code,401)
        with app.db() as c:
            item=c.execute('SELECT * FROM invitations').fetchone()
            self.assertNotEqual(item['hash'],invite)
            self.assertIsNotNone(item['used_by'])
    def test_invite_required_and_otp_retry_limit(self):
        self.assertEqual(self.client.post('/v1/auth/code',json={'email':'stranger@example.com','purpose':'register','invite':'bad'}).status_code,400)
        invite=self.invite()
        with patch.object(app,'send_mail',AsyncMock(return_value={})):
            r=self.client.post('/v1/auth/code',json={'email':'s@example.com','purpose':'register','invite':invite})
        self.assertEqual(r.status_code,200,r.text)
        for i in range(5):
            self.assertEqual(self.client.post('/v1/auth/register',json={'email':'s@example.com','code':'bad','invite':invite,'name':'S','password':'fixture-password','confirm_password':'fixture-password'}).status_code,400)
        with app.db() as c:self.assertEqual(c.execute('SELECT attempts FROM codes').fetchone()[0],5)
        self.assertEqual(self.client.post('/v1/auth/code',json={'email':'s@example.com','purpose':'register','invite':invite}).status_code,429)
    def test_credit_code_one_time_and_no_balance_tampering(self):
        invite=self.invite()
        credit=self.invite('credit',20)
        self.assertEqual(self.signup('credit@example.com',invite).status_code,200)
        self.assertEqual(self.client.post('/v1/me/redeem',json={'code':credit,'credits':99999}).status_code,200)
        self.assertEqual(self.client.post('/v1/me/redeem',json={'code':credit}).status_code,400)
        self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],95)
    def test_csrf_size_and_login_limits(self):
        self.assertEqual(self.client.post('/v1/auth/login',json={},headers={'Origin':'https://evil.example'}).status_code,403)
        with TestClient(app.app,base_url='https://echo.xhbtroy.cn') as bare:
            self.assertEqual(bare.post('/v1/auth/login',json={}).status_code,403)
        self.assertEqual(self.client.post('/v1/auth/login',content='x'*66000).status_code,413)
        for i in range(10):
            self.assertEqual(self.client.post('/v1/auth/login',json={'email':'admin@example.com','password':'incorrect'}).status_code,401)
        self.assertEqual(self.client.post('/v1/auth/login',json={'email':'admin@example.com','password':self.admin_password}).status_code,429)
    def test_mail_free_mode_and_unauthorized_ai(self):
        self.admin()
        with patch.dict(os.environ,{'ECHO_MAIL_MODE':'verified','ECHO_MAIL_VERIFIED':'owner@example.com'}):
            r=self.client.post('/v1/admin/mail/test',json={'to':'unverified@example.com','subject':'hello','text':'hello'})
        self.assertEqual(r.status_code,503,r.text)
        self.client.post('/v1/auth/logout',json={})
        self.assertEqual(self.client.post('/v1/chat/completions',json={'model':'echo-text','messages':[]}).status_code,401)

    def test_admin_password_rotation_revokes_other_sessions(self):
        first=self.client.post('/v1/auth/login',json={'email':'admin@example.com','password':self.admin_password,'client':'desktop'}).json()['token']
        second=self.client.post('/v1/auth/login',json={'email':'admin@example.com','password':self.admin_password,'client':'desktop'}).json()['token']
        headers={'Authorization':'Bearer '+first}
        result=self.client.post('/v1/admin/password',json={'current_password':self.admin_password,'new_password':'a-new-isolated-password'},headers=headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.get('/v1/me',headers=headers).status_code,200)
        self.assertEqual(self.client.get('/v1/me',headers={'Authorization':'Bearer '+second}).status_code,401)
        self.assertEqual(self.client.post('/v1/auth/login',json={'email':'admin@example.com','password':self.admin_password}).status_code,401)
        self.assertEqual(self.client.post('/v1/auth/login',json={'email':'admin@example.com','password':'a-new-isolated-password'}).status_code,200)

    def inference_body(self):
        user=self.client.get('/v1/me').json()['user']
        return {'protocol':'echo.inference/1','account_id':user['id'],'request_id':uuid.uuid4().hex,'task':'text','context':{'messages':[{'role':'user','content':'fixture question'}],'max_tokens':10}}

    def test_password_registration_and_registered_only_login(self):
        invite=self.invite()
        self.assertEqual(self.signup('password@example.com',invite).status_code,200)
        self.client.post('/v1/auth/logout',json={})
        self.assertEqual(self.client.post('/v1/auth/login',json={'email':'password@example.com','password':'student-fixture-password'}).status_code,200)
        self.client.post('/v1/auth/logout',json={})
        self.assertEqual(self.client.post('/v1/auth/login',json={'email':'unknown@example.com','password':'student-fixture-password'}).status_code,401)
        with app.db() as c:
            user=c.execute('SELECT * FROM users WHERE email=?',('password@example.com',)).fetchone()
            self.assertTrue(user['password'].startswith('$argon2id$'))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],2)

    def test_codes_list_used_owner_cipher_and_revoke(self):
        invitation=self.invite()
        unused=self.invite('credit',20)
        self.assertEqual(self.signup('codes@example.com',invitation).status_code,200)
        self.assertEqual(self.client.get('/v1/admin/invitations').status_code,403)
        self.client.post('/v1/auth/logout',json={});self.admin()
        listing=self.client.get('/v1/admin/invitations').json()['items']
        used=next(x for x in listing if x['code']==invitation)
        self.assertEqual(used['status'],'used');self.assertEqual(used['used_email'],'codes@example.com');self.assertIsNotNone(used['used_at'])
        self.assertEqual(self.client.post('/v1/admin/invitations/'+used['id']+'/revoke',json={}).status_code,400)
        un=next(x for x in listing if x['code']==unused)
        self.assertEqual(self.client.post('/v1/admin/invitations/'+un['id']+'/revoke',json={}).status_code,200)
        self.assertEqual(self.client.get('/v1/admin/invitations?status=disabled').json()['total'],1)
        with app.db() as c:
            row=c.execute('SELECT code_cipher FROM invitations WHERE hash=?',(app.digest(invitation),)).fetchone()
            self.assertNotIn(invitation,row['code_cipher'])

    def test_inference_debit_idempotency_and_identity(self):
        invite=self.invite();self.assertEqual(self.signup('model@example.com',invite).status_code,200)
        body=self.inference_body()
        mocked=AsyncMock(return_value={'text':'fixture answer','usage':{'prompt_tokens':1000,'completion_tokens':500},'finish_reason':'stop'})
        with patch.object(app,'call_model',mocked):
            first=self.client.post('/v1/echo/inference',json=body)
            second=self.client.post('/v1/echo/inference',json=body)
        self.assertEqual(first.status_code,200,first.text);self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(first.json()['account']['balance'],74.8)
        self.assertEqual(mocked.await_count,1)
        self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],74.8)
        with app.db() as c:
            encrypted=c.execute('SELECT result FROM inference_requests').fetchone()[0]
            self.assertNotIn('fixture answer',encrypted)
        body['context']['messages'][0]['content']='different'
        self.assertEqual(self.client.post('/v1/echo/inference',json=body).status_code,409)
        body['account_id']='someone-else'
        self.assertEqual(self.client.post('/v1/echo/inference',json=body).status_code,403)
        self.assertEqual(self.client.post('/v1/chat/completions',json={}).status_code,410)

    def test_inference_failure_refund_and_insufficient_balance(self):
        invite=self.invite();self.signup('failure@example.com',invite)
        body=self.inference_body()
        with patch.object(app,'call_model',AsyncMock(side_effect=app.HTTPException(503,'fixture failure'))):
            self.assertEqual(self.client.post('/v1/echo/inference',json=body).status_code,503)
        self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],75)
        self.assertEqual(self.client.post('/v1/echo/inference',json=body).status_code,409)
        with app.db(True) as c:c.execute('UPDATE users SET balance=0 WHERE email=?',('failure@example.com',))
        body['request_id']=uuid.uuid4().hex
        with patch.object(app,'call_model',AsyncMock()) as model:
            self.assertEqual(self.client.post('/v1/echo/inference',json=body).status_code,402)
            model.assert_not_awaited()

    def test_concurrent_same_request_only_debits_once(self):
        invite=self.invite();self.signup('race@example.com',invite)
        body=self.inference_body()
        async def model(task,context):
            await asyncio.sleep(.15)
            return {'text':'fixture answer','usage':{'prompt_tokens':1000,'completion_tokens':500}}
        mocked=AsyncMock(side_effect=model)
        with patch.object(app,'call_model',mocked),ThreadPoolExecutor(max_workers=2) as pool:
            replies=list(pool.map(lambda _:self.client.post('/v1/echo/inference',json=body),range(2)))
        self.assertTrue(all(r.status_code in (200,409) for r in replies))
        self.assertTrue(any(r.status_code==200 for r in replies))
        self.assertEqual(mocked.await_count,1)
        self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],74.8)

    def test_user_disable_revokes_sessions_and_ai_access(self):
        invite=self.invite();user=self.signup('disabled@example.com',invite).json()['user']
        token=self.client.post('/v1/auth/login',json={'email':user['email'],'password':'student-fixture-password','client':'desktop'}).json()['token']
        self.admin()
        self.assertEqual(self.client.post('/v1/admin/users/'+user['id']+'/access',json={'disabled':True,'ai_enabled':False}).status_code,200)
        self.assertEqual(self.client.get('/v1/me',headers={'Authorization':'Bearer '+token}).status_code,401)
        self.assertEqual(self.client.post('/v1/auth/login',json={'email':user['email'],'password':'student-fixture-password'}).status_code,401)

    def test_admin_credit_adjustment_ledger_and_negative_guard(self):
        self.admin();ident=self.client.get('/v1/me').json()['user']['id']
        self.assertEqual(self.client.post('/v1/admin/users/'+ident+'/credits',json={'amount':10,'note':'fixture grant'}).status_code,200)
        self.assertEqual(self.client.post('/v1/admin/users/'+ident+'/credits',json={'amount':-20,'note':'invalid'}).status_code,400)
        self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],10)

    def test_restart_refunds_unfinished_request_once(self):
        self.admin();ident=self.client.get('/v1/me').json()['user']['id'];rid=uuid.uuid4().hex
        with app.db(True) as c:
            c.execute('UPDATE users SET balance=9000 WHERE id=?',(ident,))
            c.execute("INSERT INTO inference_requests(user_id,request_id,request_hash,task,state,cost,created) VALUES(?,?,?,'text','pending',1000,?)",(ident,rid,'fixture',app.now()))
        app.initialize();app.initialize()
        self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],10)

    def test_member_password_change(self):
        invite=self.invite();self.signup('change@example.com',invite)
        body={'current_password':'student-fixture-password','new_password':'changed-fixture-password','confirm_password':'changed-fixture-password'}
        self.assertEqual(self.client.post('/v1/me/password',json=body).status_code,200)
        self.client.post('/v1/auth/logout',json={})
        self.assertEqual(self.client.post('/v1/auth/login',json={'email':'change@example.com','password':'changed-fixture-password'}).status_code,200)

    def test_registration_rejects_missing_password_without_consuming_code(self):
        invitation=self.invite()
        mail=AsyncMock(return_value={})
        with patch.object(app,'send_mail',mail):
            self.assertEqual(self.client.post('/v1/auth/code',json={'email':'missing@example.com','purpose':'register','invite':invitation}).status_code,200)
        code=re.search(r'\d{6}',mail.call_args.args[2]).group()
        body={'email':'missing@example.com','code':code,'invite':invitation,'name':'Fixture'}
        self.assertEqual(self.client.post('/v1/auth/register',json=body).status_code,400)
        with app.db() as c:
            self.assertIsNone(c.execute('SELECT used_by FROM invitations WHERE hash=?',(app.digest(invitation),)).fetchone()[0])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)
        body.update(password='fixture-new-password',confirm_password='fixture-new-password')
        self.assertEqual(self.client.post('/v1/auth/register',json=body).status_code,200)

    def test_reissue_legacy_code_preserves_history(self):
        self.admin()
        legacy='ECHO-legacy-fixture';ident=app.digest(legacy)
        with app.db(True) as c:
            c.execute("INSERT INTO invitations(hash,label,email,kind,credits,expires,created) VALUES(?,?,?,'register',10,?,?)",(ident,'legacy','friend@example.com',app.now()+86400,app.now()))
        result=self.client.post('/v1/admin/invitations/'+ident+'/replace',json={})
        self.assertEqual(result.status_code,200,result.text)
        items=self.client.get('/v1/admin/invitations').json()['items']
        self.assertEqual(next(i for i in items if i['id']==ident)['status'],'disabled')
        self.assertEqual(next(i for i in items if i['code']==result.json()['code'])['email'],'friend@example.com')
        self.assertEqual(self.client.post('/v1/admin/invitations/'+ident+'/replace',json={}).status_code,400)

    def test_recipient_management_lists_status_and_sends_verification(self):
        self.admin()
        addresses={'success':True,'result':[{'email':'owner@example.com','verified':'2026-11-14T00:00:00Z'},{'email':'pending@example.com','verified':None}]}
        client=AsyncMock()
        client.get.return_value=SimpleNamespace(json=lambda:addresses)
        client.post.return_value=SimpleNamespace(json=lambda:{'success':True,'result':{'email':'new@example.com'}})
        manager=AsyncMock();manager.__aenter__.return_value=client
        with patch.dict(os.environ,{'ECHO_MAIL_TOKEN':'fixture','ECHO_MAIL_ACCOUNT':'fixture'}),patch.object(app.httpx,'AsyncClient',return_value=manager):
            result=self.client.get('/v1/admin/mail/recipients')
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual([i['status'] for i in result.json()['items']],['verified','pending'])
            result=self.client.post('/v1/admin/mail/verify-recipient',json={'email':'new@example.com'})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(client.post.await_count,1)
            result=self.client.post('/v1/admin/mail/verify-recipient',json={'email':'pending@example.com'})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(client.post.await_count,1)

    def test_model_forwarding_uses_server_credentials_and_allowed_fields(self):
        client=AsyncMock()
        client.post.return_value=SimpleNamespace(status_code=200,content=b'fixture',json=lambda:{'choices':[{'message':{'content':'OK'},'finish_reason':'stop'}]})
        manager=AsyncMock();manager.__aenter__.return_value=client
        with patch.dict(os.environ,{'ECHO_TEXT_ORIGIN':'https://api.deepseek.com/v1','ECHO_TEXT_KEY':'server-fixture-key','ECHO_TEXT_MODEL':'deepseek-flash'}),patch.object(app.httpx,'AsyncClient',return_value=manager):
            result=asyncio.run(app.call_model('text',{'messages':[{'role':'user','content':'fixture'}],'max_tokens':16,'response_format':{'type':'json_object'},'api_key':'untrusted','base_url':'https://untrusted.example'}))
        self.assertEqual(result['text'],'OK')
        self.assertEqual(client.post.call_args.args[0],'https://api.deepseek.com/v1/chat/completions')
        forwarded=client.post.call_args.kwargs['json']
        self.assertEqual(forwarded['thinking'],{'type':'disabled'})
        self.assertEqual(forwarded['response_format'],{'type':'json_object'})
        self.assertNotIn('api_key',forwarded)
        self.assertNotIn('base_url',forwarded)

    def test_invalid_model_reply_is_not_treated_as_success(self):
        client=AsyncMock()
        client.post.return_value=SimpleNamespace(status_code=200,content=b'fixture',json=lambda:{'choices':[{'message':{'content':''}}]})
        manager=AsyncMock();manager.__aenter__.return_value=client
        with patch.dict(os.environ,{'ECHO_TEXT_ORIGIN':'https://example.com/v1','ECHO_TEXT_KEY':'fixture','ECHO_TEXT_MODEL':'fixture'}),patch.object(app.httpx,'AsyncClient',return_value=manager):
            with self.assertRaises(app.HTTPException) as raised:
                asyncio.run(app.call_model('text',{'messages':[{'role':'user','content':'fixture'}]}))
        self.assertEqual(raised.exception.status_code,502)

    def fixture_profile(self):
        import json
        from pathlib import Path
        return json.loads((Path(__file__).resolve().parents[2]/'docs/examples/learning-profile.json').read_text(encoding='utf-8'))

    def test_private_profile_roundtrip_encrypted_and_owner_only(self):
        invite=self.invite()
        self.signup('archive@example.com',invite)
        value=self.fixture_profile()
        response=self.client.post('/v1/me/profiles',json={'label':'演示档案','profile':value,'consent':True})
        self.assertEqual(response.status_code,200,response.text)
        ident=response.json()['id']
        self.assertEqual(self.client.get('/v1/me/profiles/'+ident).json()['profile'],value)
        with app.db() as c:
            cipher=c.execute('SELECT cipher FROM learning_profiles WHERE id=?',(ident,)).fetchone()[0]
            self.assertNotIn('echo.learning-profile',cipher)
        self.assertEqual(self.client.get('/v1/me/profiles/'+ident+'/download').json(),value)
        self.client.post('/v1/auth/logout',json={})
        self.assertEqual(self.client.get('/v1/me/profiles').status_code,401)
        self.admin()
        self.assertEqual(self.client.get('/v1/me/profiles/'+ident).status_code,404)
        self.assertEqual(self.client.delete('/v1/me/profiles/'+ident).status_code,404)
        self.client.post('/v1/auth/logout',json={})
        self.client.post('/v1/auth/login',json={'email':'archive@example.com','password':'student-fixture-password'})
        self.assertEqual(self.client.delete('/v1/me/profiles/'+ident).status_code,200)
        self.assertEqual(self.client.get('/v1/me/profiles').json()['items'],[])

    def test_profile_rejects_secret_fields_consent_and_capacity(self):
        self.admin()
        value=self.fixture_profile()
        self.assertEqual(self.client.post('/v1/me/profiles',json={'label':'test','profile':value}).status_code,400)
        value['learner']['profile']['API_KEY']='never-upload-this'
        self.assertEqual(self.client.post('/v1/me/profiles',json={'label':'test','profile':value,'consent':True}).status_code,400)
        value=self.fixture_profile()
        for i in range(10):
            self.assertEqual(self.client.post('/v1/me/profiles',json={'label':str(i),'profile':value,'consent':True}).status_code,200)
        self.assertEqual(self.client.post('/v1/me/profiles',json={'label':'overflow','profile':value,'consent':True}).status_code,409)

    def test_mail_receipt_logs_metadata_without_body_or_code(self):
        self.admin()
        with patch.object(app,'_deliver_mail',AsyncMock(return_value={'message_id':'provider-id','delivered':['admin@example.com'],'queued':[]})):
            response=self.client.post('/v1/auth/code',json={'email':'admin@example.com','purpose':'login'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('收件箱',response.json()['message'])
        rows=self.client.get('/v1/admin/mail/deliveries').json()['items']
        self.assertEqual(rows[0]['status'],'accepted')
        self.assertNotIn('text',rows[0]);self.assertNotIn('code',rows[0])

    def test_unregistered_otp_is_explicit_error_and_failure_has_receipt(self):
        response=self.client.post('/v1/auth/code',json={'email':'unknown@example.com','purpose':'login'})
        self.assertEqual(response.status_code,400)
        self.admin()
        with patch.object(app,'_deliver_mail',AsyncMock(side_effect=app.HTTPException(503,'邮件暂不可用'))):
            response=self.client.post('/v1/auth/code',json={'email':'admin@example.com','purpose':'login'})
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.client.get('/v1/admin/mail/deliveries').json()['items'][0]['status'],'failed')

    def test_late_mail_after_timeout_keeps_a_valid_code(self):
        self.admin()
        async def provider_timeout(to,subject,text):
            with app.db() as c:
                code=re.search(r'\d{6}',text).group()
                self.assertTrue(app.verify_code(c,to,code,'login'))
            raise app.HTTPException(503,'投递状态未知')
        with patch.object(app,'_deliver_mail',provider_timeout):
            response=self.client.post('/v1/auth/code',json={'email':'admin@example.com','purpose':'login'})
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.client.get('/v1/admin/mail/deliveries').json()['items'][0]['status'],'unknown')

    def sync_fixture(self,device=None,revision=0,profile=None):
        return self.client.post('/v1/me/sync',json={'protocol':'echo.sync/1','account_id':self.client.get('/v1/me').json()['user']['id'],'device_id':device or uuid.uuid4().hex,'device_name':'Isolated device','base_revision':revision,'profile':profile or self.fixture_profile(),'consent':True})

    def test_cloud_devices_are_versioned_idempotent_and_private(self):
        self.admin();device=uuid.uuid4().hex
        first=self.sync_fixture(device)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['revision'],1)
        self.assertFalse(self.sync_fixture(device).json()['changed'])
        changed=self.fixture_profile();changed['learner']['profile']['name']='Changed fixture'
        self.assertEqual(self.sync_fixture(device,profile=changed).status_code,409)
        self.assertEqual(self.sync_fixture(device,1,changed).json()['revision'],2)
        self.assertEqual(self.sync_fixture().status_code,200)
        self.assertEqual(len(self.client.get('/v1/me/workspace').json()['devices']),2)
        with app.db() as c:
            cipher=c.execute('SELECT cipher FROM cloud_devices LIMIT 1').fetchone()[0]
            self.assertNotIn('echo.learning-profile',cipher)
        self.client.post('/v1/auth/logout',json={})
        self.assertEqual(self.client.get('/v1/me/sync').status_code,401)
        invitation=self.invite();self.signup('privatecloud@example.com',invitation)
        self.assertEqual(self.client.get('/v1/me/workspace').json()['points'],[])
        self.assertEqual(self.client.delete('/v1/me/devices/'+device).status_code,404)
        self.assertEqual(self.client.get('/v1/admin/workspace').status_code,403)

    def test_cloud_preferences_pause_and_device_limit(self):
        self.admin()
        response=self.client.post('/v1/me/preferences',json={'name':'Fixture','daily_goal':8,'auto_sync':False})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.sync_fixture().status_code,409)
        self.assertEqual(self.client.get('/v1/me/workspace').json()['preferences']['daily_goal'],8)
        self.client.post('/v1/me/preferences',json={'name':'Fixture','daily_goal':8,'auto_sync':True})
        for _ in range(5):self.assertEqual(self.sync_fixture().status_code,200)
        self.assertEqual(self.sync_fixture().status_code,409)
        self.assertEqual(self.client.post('/v1/me/preferences',json={'name':'Fixture','daily_goal':0,'auto_sync':True}).status_code,400)

    def test_web_review_idempotency_and_sync_return(self):
        self.admin();self.sync_fixture()
        point=self.client.get('/v1/me/workspace').json()['points'][0]
        body={'knowledge_id':point['id'],'result':'clear','request_id':uuid.uuid4().hex}
        self.assertEqual(self.client.post('/v1/me/review',json=body).status_code,200)
        review=next(r for r in self.client.get('/v1/me/sync').json()['reviews'] if r['knowledge_id']==point['id'])
        count=review['review_count']
        self.assertEqual(self.client.post('/v1/me/review',json=body).status_code,200)
        repeated=next(r for r in self.client.get('/v1/me/sync').json()['reviews'] if r['knowledge_id']==point['id'])
        self.assertEqual(repeated['review_count'],count)
        self.assertGreater(repeated['due'],app.now())
        self.assertEqual(self.client.post('/v1/me/review',json={**body,'result':'again'}).status_code,409)
        self.assertEqual(self.client.post('/v1/me/review',json={**body,'knowledge_id':'foreign-topic','request_id':uuid.uuid4().hex}).status_code,404)

    def test_web_quiz_hides_answers_grades_on_server_and_charges_once(self):
        import json
        invite=self.invite(credits=3);self.signup('quizcloud@example.com',invite);self.sync_fixture()
        point=self.client.get('/v1/me/workspace').json()['points'][0]
        body={'knowledge_id':point['id'],'request_id':uuid.uuid4().hex}
        generated={'question':'哪个选项符合此知识点？','options':['正确选项','错误一','错误二','错误三'],'answer':0,'explanation':'这是隔离测试中的参考解释。'}
        with patch.object(app,'call_model',AsyncMock(return_value={'text':json.dumps(generated),'usage':{'prompt_tokens':1000,'completion_tokens':500}})) as model:
            response=self.client.post('/v1/me/practice',json=body)
            self.assertEqual(response.status_code,200,response.text)
            self.assertNotIn('answer',response.json());self.assertNotIn('explanation',response.json())
            self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],2.8)
            self.assertEqual(self.client.post('/v1/me/practice',json=body).status_code,200)
            self.assertEqual(model.await_count,1)
        ident=response.json()['id']
        graded=self.client.post('/v1/me/practice/'+ident+'/answer',json={'choice':0})
        self.assertTrue(graded.json()['correct']);self.assertEqual(graded.json()['answer'],0)
        self.assertEqual(self.client.post('/v1/me/practice/'+ident+'/answer',json={'choice':0}).status_code,200)
        self.assertEqual(self.client.post('/v1/me/practice/'+ident+'/answer',json={'choice':1}).status_code,409)
        self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],2.8)
        self.client.post('/v1/auth/logout',json={});self.admin()
        self.assertEqual(self.client.get('/v1/me/practice/'+ident).status_code,404)

    def test_malformed_quiz_refunds_and_zero_credit_can_self_review(self):
        invite=self.invite(credits=1);self.signup('refundcloud@example.com',invite);self.sync_fixture()
        point=self.client.get('/v1/me/workspace').json()['points'][0]
        with patch.object(app,'call_model',AsyncMock(return_value={'text':'{"question":"bad","options":[]}'})):
            response=self.client.post('/v1/me/practice',json={'knowledge_id':point['id'],'request_id':uuid.uuid4().hex})
        self.assertEqual(response.status_code,502,response.text)
        self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],1)
        with app.db(True) as c:c.execute('UPDATE users SET balance=0 WHERE email=?',('refundcloud@example.com',))
        self.assertEqual(self.client.post('/v1/me/practice',json={'knowledge_id':point['id'],'request_id':uuid.uuid4().hex}).status_code,402)
        self.assertEqual(self.client.post('/v1/me/review',json={'knowledge_id':point['id'],'result':'fuzzy','request_id':uuid.uuid4().hex}).status_code,200)

    def test_session_controls_keep_current_and_do_not_expose_tokens(self):
        self.admin()
        self.client.post('/v1/auth/login',json={'email':'admin@example.com','password':self.admin_password})
        sessions=self.client.get('/v1/me/sessions').json()
        self.assertEqual(sessions['count'],2)
        self.assertTrue(any(s['current'] for s in sessions['items']))
        self.assertTrue(all('token' not in s for s in sessions['items']))
        self.assertEqual(self.client.post('/v1/me/sessions/revoke-others',json={}).status_code,200)
        self.assertEqual(self.client.get('/v1/me/sessions').json()['count'],1)

    def test_token_billing_records_purpose_and_exact_usage(self):
        invite=self.invite();self.signup('tokens@example.com',invite)
        body={**self.inference_body(),'protocol':'echo.inference/2','purpose':'blackboard'}
        with patch.object(app,'call_model',AsyncMock(return_value={'text':'fixture','usage':{'prompt_tokens':1000,'completion_tokens':500}})):
            response=self.client.post('/v1/echo/inference',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['account']['charged_points'],.2)
        item=self.client.get('/v1/me/requests').json()['items'][0]
        self.assertEqual(item['purpose_label'],'AI 黑板');self.assertEqual(item['input_tokens'],1000);self.assertEqual(item['output_tokens'],500);self.assertEqual(item['usage_source'],'provider')
        app.initialize();self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],74.8)

    def test_full_exam_budget_is_allowed_only_for_text_quiz(self):
        invite=self.invite();self.signup('exam-budget@example.com',invite)
        body={**self.inference_body(),'protocol':'echo.inference/2','purpose':'quiz'}
        body['context']['max_tokens']=9500
        with patch.object(app,'call_model',AsyncMock(return_value={'text':'fixture','usage':{'prompt_tokens':100,'completion_tokens':100}})):
            response=self.client.post('/v1/echo/inference',json=body)
        self.assertEqual(response.status_code,200,response.text)
        body['request_id']=uuid.uuid4().hex;body['purpose']='assistant'
        self.assertEqual(self.client.post('/v1/echo/inference',json=body).status_code,400)

        body['purpose']='quiz';body['context']['max_tokens']=10001
        self.assertEqual(self.client.post('/v1/echo/inference',json=body).status_code,400)

    def test_admin_hourly_trends_use_real_completed_denominator(self):
        self.admin()
        initial=self.client.get('/v1/admin/workspace').json()['timeline']
        self.assertEqual(len(initial),24)
        self.assertTrue(all(p['success_rate'] is None for p in initial))
        with app.db(True) as c:
            uid=c.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
            for state in ('succeeded','failed','pending'):
                c.execute('INSERT INTO inference_requests(user_id,request_id,request_hash,task,state,cost,created,input_tokens,output_tokens) VALUES(?,?,?,?,?,?,?,?,?)',(uid,uuid.uuid4().hex,'fixture','text',state,0,app.now(),100 if state=='succeeded' else None,50 if state=='succeeded' else None))
        point=self.client.get('/v1/admin/workspace').json()['timeline'][-1]
        self.assertEqual(point['requests'],3);self.assertEqual(point['success_rate'],50)
        self.assertEqual(point['input_tokens'],100);self.assertEqual(point['output_tokens'],50)
        self.client.post('/v1/auth/logout',json={})
        self.assertEqual(self.client.get('/v1/admin/workspace').status_code,401)

    def test_milli_point_migration_runs_once_and_admin_model_keys_stay_private(self):
        self.admin()
        with app.db(True) as c:
            c.execute('UPDATE users SET balance=7');c.execute("DELETE FROM billing_settings WHERE key='milli_points_v1'")
        app.initialize();app.initialize()
        self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],7)
        with patch.dict(os.environ,{'ECHO_TEXT_KEY':'sentinel-secret-provider-key','ECHO_TEXT_ORIGIN':'https://user:password@example.com/v1?secret=value','ECHO_TEXT_MODEL':'fixture-model'}):
            response=self.client.get('/v1/admin/models')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('sentinel-secret',response.text);self.assertNotIn('password',response.text);self.assertNotIn('secret=value',response.text)
        self.assertTrue(response.json()['models'][0]['key_configured'])
        self.assertEqual(self.client.post('/v1/admin/billing',json={'input_points_per_1000':.15,'output_points_per_1000':.25}).status_code,200)
        self.assertEqual(self.client.get('/v1/public/config').json()['billing']['input_points_per_1000'],.15)

    def test_classroom_archive_owner_only_and_secret_fields_rejected(self):
        self.admin();device=uuid.uuid4().hex;uid=self.client.get('/v1/me').json()['user']['id']
        record={'id':'lesson_'+'a'*24,'title':'隔离课堂','ended_at':'2026-11-12T10:00:00Z','duration_seconds':120,'summary':'只包含课堂回顾','suggestion':'再复习一次','highlights':['重点'],'skills':[{'name':'函数','status':'review','mastery':.4}],'blackboard_notes':'安全文本','truncated':False}
        body={'protocol':'echo.sync/1','account_id':uid,'device_id':device,'device_name':'Fixture','base_revision':0,'profile':self.fixture_profile(),'classroom':{'protocol':'echo.classroom/1','lessons':[record]},'consent':True}
        response=self.client.post('/v1/me/sync',json=body);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/v1/me/workspace').json()['lessons'][0]['title'],'隔离课堂')
        self.assertEqual(self.client.get('/v1/me/lessons/'+record['id']).json()['summary'],record['summary'])
        record['api_key']='no';body['base_revision']=1
        self.assertEqual(self.client.post('/v1/me/sync',json=body).status_code,400)
        self.client.post('/v1/auth/logout',json={});invite=self.invite();self.signup('otherarchive@example.com',invite)
        self.assertEqual(self.client.get('/v1/me/lessons/'+'lesson_'+'a'*24).status_code,404)

    def test_wrong_question_retry_is_free_and_preserves_original(self):
        import json
        self.admin();self.sync_fixture()
        uid=self.client.get('/v1/me').json()['user']['id']
        with app.db(True) as c:c.execute('UPDATE users SET balance=10000 WHERE id=?',(uid,))
        key=self.client.get('/v1/me/workspace').json()['points'][0]['id']
        value={'question':'隔离测试题的正确选项是什么？','options':['正确','错一','错二','错三'],'answer':0,'explanation':'隔离测试参考解释。'}
        with patch.object(app,'call_model',AsyncMock(return_value={'text':json.dumps(value),'usage':{'prompt_tokens':1000,'completion_tokens':500}})):
            created=self.client.post('/v1/me/practice',json={'knowledge_id':key,'request_id':uuid.uuid4().hex}).json()
        first=self.client.post('/v1/me/practice/'+created['id']+'/answer',json={'choice':1});self.assertFalse(first.json()['correct'])
        balance=self.client.get('/v1/me').json()['user']['balance'];retry_id=uuid.uuid4().hex
        second=self.client.post('/v1/me/practice/'+created['id']+'/retry',json={'request_id':retry_id})
        self.assertEqual(second.status_code,200,second.text);self.assertNotIn('answer',second.json())
        self.assertEqual(self.client.post('/v1/me/practice/'+created['id']+'/retry',json={'request_id':retry_id}).status_code,200)
        self.assertTrue(self.client.post('/v1/me/practice/'+retry_id+'/answer',json={'choice':0}).json()['correct'])
        self.assertEqual(self.client.get('/v1/me').json()['user']['balance'],balance)
        self.assertFalse(self.client.get('/v1/me/practice/'+created['id']).json()['correct'])

    def test_beta_download_requires_own_registered_invite(self):
        import json,hashlib
        from pathlib import Path
        root=Path(self.folder.name)/'releases';root.mkdir();name='Echo-Beta-2.5.0-windows-x64.zip';(root/name).write_bytes(b'private fixture')
        (root/'beta.json').write_text(json.dumps({'version':'2.5.0','filename':name,'size':15,'sha256':hashlib.sha256(b'private fixture').hexdigest()}))
        with patch.dict(os.environ,{'ECHO_BETA_DIR':str(root)}):
            self.assertEqual(self.client.get('/v1/beta/download').status_code,401)
            invitation=self.invite();self.signup('betafixture@example.com',invitation)
            response=self.client.get('/v1/beta/release');self.assertEqual(response.status_code,200,response.text)
            download=self.client.get('/v1/beta/download');self.assertEqual(download.status_code,200);self.assertIn('/_protected_echo_beta/',download.headers['x-accel-redirect'])
            self.assertEqual(self.client.post('/v1/beta/verify-invite',json={'invite':invitation}).status_code,200)
            with app.db(True) as c:c.execute('UPDATE invitations SET disabled=1')
            self.assertEqual(self.client.get('/v1/beta/download').status_code,403)

if __name__=='__main__':unittest.main()
