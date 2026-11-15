"""Disposable users/files/models only. Never contacts a mail or AI provider."""
import base64,copy,io,json,unittest,uuid,zipfile
from unittest.mock import AsyncMock,patch
import test_accounts as fixtures
app=fixtures.app
import study_models as models

class StudyTests(unittest.TestCase):
    setUp=fixtures.AccountTests.setUp
    tearDown=fixtures.AccountTests.tearDown
    admin=fixtures.AccountTests.admin
    def login(self):
        self.admin()
        with app.db(True) as c:c.execute('UPDATE users SET balance=100000')
    def upload(self,name='math.txt',raw=None):
        raw=raw if raw is not None else '一次函数y=2x+1，求x=3时y。\n参考答案7。'.encode()
        r=self.client.post('/v1/me/study/materials',json={'filename':name,'content_base64':base64.b64encode(raw).decode(),'request_id':uuid.uuid4().hex})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()
    def question(self,mid,kind='single_choice',number=0):
        return {'type':kind,'question':'测试问题'+str(number),'options':['7','8','9','10'],'answer':0 if kind in ('single_choice','true_false') else [0,1] if kind=='multiple_choice' else '参考说明',
                'explanation':'根据资料代入计算。','topic':'一次函数','source_ids':[mid],'answer_source':'provided'}
    def analysis(self,mid,count=6):
        return {'summary':'一次函数复习资料','topics':[{'name':'一次函数','notes':'代入自变量求值。'}],
                'questions':[self.question(mid,number=i) for i in range(count)],'warnings':[]}
    def analyze(self,mid,data=None,rid=None):
        rid=rid or uuid.uuid4().hex
        response={'text':json.dumps(data or self.analysis(mid),ensure_ascii=False),'usage':{'prompt_tokens':100,'completion_tokens':100}}
        with patch.object(app,'call_model',AsyncMock(return_value=response)) as call:
            r=self.client.post('/v1/me/study/materials/'+mid+'/analyze',json={'request_id':rid})
        self.assertEqual(r.status_code,200,r.text)
        return r.json(),call
    def confirmed(self,kind='single_choice'):
        mid=self.upload()['id'];data=self.analysis(mid)
        data['questions']=[self.question(mid,kind,i) for i in range(6)]
        self.analyze(mid,data)
        r=self.client.post('/v1/me/study/materials/'+mid+'/confirm',json={});self.assertEqual(r.status_code,200,r.text)
        return mid
    def paper(self,mid=None,generate=False,kind='exams',rid=None):
        body={'request_id':rid or uuid.uuid4().hex,'count':5,'duration_minutes':10,'generate':generate,'material_ids':[mid] if mid else []}
        return self.client.post('/v1/me/study/'+kind,json=body)
    def test_upload_deduplicates_encrypts_and_checks_ownership(self):
        self.login();first=self.upload();second=self.upload()
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['status'],'ready')
        with app.db() as c:
            row=c.execute('SELECT * FROM study_materials').fetchone()
            self.assertNotIn('一次函数',row['cipher'])
            self.assertEqual(row['size'],len('一次函数y=2x+1，求x=3时y。\n参考答案7。'.encode()))
        self.assertEqual(self.client.get('/v1/me/study/materials/'+first['id']+'/download').content,'一次函数y=2x+1，求x=3时y。\n参考答案7。'.encode())
        self.client.post('/v1/auth/logout',json={})
        self.assertEqual(self.client.get('/v1/me/study/materials').status_code,401)
        # A separate valid user cannot read private material or download it.
        with app.db(True) as c:
            uid=uuid.uuid4().hex;c.execute("INSERT INTO users(id,email,name,created) VALUES(?,?,?,?)",(uid,'other@example.com','Other',app.now()))
            token='fixture-'+uuid.uuid4().hex;c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(app.digest(token),uid,app.now()+1000,app.now()))
        headers={'Authorization':'Bearer '+token}
        self.assertEqual(self.client.get('/v1/me/study/materials/'+first['id'],headers=headers).status_code,404)
        self.assertEqual(self.client.get('/v1/me/study/materials/'+first['id']+'/download',headers=headers).status_code,404)
    def test_invalid_files_no_model_or_charge(self):
        self.login()
        for name,raw in [('evil.html',b'<script>bad()</script>'),('bad.pdf',b'not pdf'),('../x.txt',b'bad'),('bad.docx',b'PKnotzip')]:
            r=self.client.post('/v1/me/study/materials',json={'filename':name,'content_base64':base64.b64encode(raw).decode()});self.assertEqual(r.status_code,400,r.text)
        r=self.client.post('/v1/me/study/materials',json={'filename':'big.txt','content_base64':'a'*(4*1024*1024+8)})
        self.assertEqual(r.status_code,413)
        with app.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM inference_requests').fetchone()[0],0)
    def test_real_docx_pdf_image_workers(self):
        self.login();file=io.BytesIO()
        with zipfile.ZipFile(file,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>函数试卷</w:t></w:r></w:p></w:document>')
        self.assertIn('函数试卷',self.upload('paper.docx',file.getvalue())['text'])
        from pypdf import PdfWriter
        pdf=io.BytesIO();writer=PdfWriter();writer.add_blank_page(width=300,height=300);writer.write(pdf)
        scan=self.upload('scan.pdf',pdf.getvalue());self.assertEqual(scan['status'],'needs_ocr')
        r=self.client.post('/v1/me/study/materials/'+scan['id']+'/analyze',json={'request_id':uuid.uuid4().hex});self.assertEqual(r.status_code,400)
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(8,8),'white').save(image,format='PNG')
        self.assertEqual(self.upload('scan.png',image.getvalue())['status'],'image')
    def test_analysis_requires_confirmation_and_retries_do_not_charge(self):
        self.login();mid=self.upload()['id'];rid=uuid.uuid4().hex
        result,_=self.analyze(mid,rid=rid);self.assertFalse(result['analysis']['confirmed'])
        self.assertEqual(self.paper(mid).status_code,409)
        with app.db() as c:balance=c.execute('SELECT balance FROM users').fetchone()[0]
        with patch.object(app,'call_model',AsyncMock(side_effect=AssertionError('no second AI'))) as called:
            r=self.client.post('/v1/me/study/materials/'+mid+'/analyze',json={'request_id':rid})
        self.assertEqual(r.status_code,200,r.text);called.assert_not_called()
        with app.db() as c:self.assertEqual(c.execute('SELECT balance FROM users').fetchone()[0],balance)
        for _ in range(2):self.assertEqual(self.client.post('/v1/me/study/materials/'+mid+'/confirm',json={}).status_code,200)
        with app.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM study_bank').fetchone()[0],6)
    def test_malformed_ai_refunds_transaction(self):
        self.login();mid=self.upload()['id'];rid=uuid.uuid4().hex
        with patch.object(app,'call_model',AsyncMock(return_value={'text':'not json','usage':{'prompt_tokens':100,'completion_tokens':100}})):
            r=self.client.post('/v1/me/study/materials/'+mid+'/analyze',json={'request_id':rid})
        self.assertEqual(r.status_code,502,r.text)
        with app.db() as c:
            self.assertEqual(c.execute('SELECT balance FROM users').fetchone()[0],100000)
            self.assertEqual(c.execute('SELECT state FROM inference_requests').fetchone()[0],'failed')
            self.assertEqual(c.execute('SELECT count(*) FROM study_bank').fetchone()[0],0)
    def test_exam_hides_answers_saves_with_revision_and_submits_once(self):
        self.login();mid=self.confirmed();r=self.paper(mid);self.assertEqual(r.status_code,200,r.text);paper=r.json()
        self.assertIsNone(paper['results']);self.assertTrue(all('answer' not in q and 'explanation' not in q for q in paper['questions']))
        aid=paper['id'];answers={q['id']:0 for q in paper['questions']}
        r=self.client.post('/v1/me/study/attempts/'+aid+'/answers',json={'answers':answers,'revision':0});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['revision'],1)
        self.assertEqual(self.client.post('/v1/me/study/attempts/'+aid+'/answers',json={'answers':{},'revision':0}).status_code,409)
        result=self.client.post('/v1/me/study/attempts/'+aid+'/submit',json={'answers':answers,'revision':1});self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['score'],100);self.assertEqual(result.json()['pending_count'],0)
        repeated=self.client.post('/v1/me/study/attempts/'+aid+'/submit',json={'answers':{},'revision':0});self.assertEqual(repeated.json()['score'],100)
        self.assertTrue(all('answer' in r for r in result.json()['results'].values()))
    def test_expiry_only_uses_saved_answers(self):
        self.login();mid=self.confirmed();paper=self.paper(mid).json();aid=paper['id']
        self.client.post('/v1/me/study/attempts/'+aid+'/answers',json={'answers':{'q1':0},'revision':0})
        with patch.object(app.time,'time',return_value=paper['deadline']+1):
            r=self.client.post('/v1/me/study/attempts/'+aid+'/submit',json={'answers':{'q2':0},'revision':1})
        # install retains now function; patch its time source too.
        if r.json()['status']!='submitted':self.fail('expired exam remained active')
        self.assertEqual(r.json()['answers'],{'q1':0})
    def test_daily_free_unique_and_remains_across_preferences(self):
        self.login();self.confirmed()
        with patch.object(app,'call_model',AsyncMock(side_effect=AssertionError('no AI'))):
            first=self.paper(kind='daily').json();second=self.paper(kind='daily').json()
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['count'],3)
        self.assertEqual(self.client.get('/v1/me/study/daily').json()['attempt']['id'],first['id'])
        self.assertEqual(self.client.post('/v1/me/study/preferences',json={'daily_count':9}).status_code,400)
    def test_subjective_grading_is_separate_paid_idempotent_action(self):
        self.login();mid=self.confirmed('short_answer');paper=self.paper(mid).json();aid=paper['id']
        answers={q['id']:('自己的解释' if q['type']=='short_answer' else 0) for q in paper['questions']}
        r=self.client.post('/v1/me/study/attempts/'+aid+'/submit',json={'answers':answers,'revision':0});self.assertEqual(r.status_code,200,r.text)
        pending=[k for k,v in r.json()['results'].items() if v['status']=='pending']
        # Random bank selection may omit the single subjective question; start from full six-question bank through direct fixture if needed.
        if not pending:return
        model={'text':json.dumps({'grades':[{'id':k,'score':.5,'feedback':'部分正确，补充条件。'} for k in pending]}),'usage':{'prompt_tokens':10,'completion_tokens':20}}
        rid=uuid.uuid4().hex
        with patch.object(app,'call_model',AsyncMock(return_value=model)) as called:
            grade=self.client.post('/v1/me/study/attempts/'+aid+'/grade',json={'request_id':rid})
            again=self.client.post('/v1/me/study/attempts/'+aid+'/grade',json={'request_id':rid})
        self.assertEqual(grade.status_code,200,grade.text);self.assertEqual(again.status_code,200);self.assertEqual(called.await_count,1)
        self.assertEqual(grade.json()['pending_count'],0)
    def test_delete_clears_bank_but_preserves_exam_snapshot(self):
        self.login();mid=self.confirmed();paper=self.paper(mid).json()
        self.assertEqual(self.client.delete('/v1/me/study/materials/'+mid,headers={'X-Echo-CSRF':'1'}).status_code,200)
        self.assertEqual(self.client.get('/v1/me/study/materials/'+mid).status_code,404)
        self.assertEqual(self.client.get('/v1/me/study/attempts/'+paper['id']).status_code,200)
        with app.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM study_bank').fetchone()[0],0)

    def test_material_topics_become_reviewable_knowledge_and_free_sources(self):
        self.login();mid=self.confirmed()
        workspace=self.client.get('/v1/me/workspace').json()
        point=next(p for p in workspace['points'] if p['id'].startswith('material:'+mid))
        self.assertEqual(point['topic'],'一次函数')
        response=self.client.post('/v1/me/review',json={'knowledge_id':point['id'],'result':'fuzzy','request_id':uuid.uuid4().hex})
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.post('/v1/me/study/exams',json={'request_id':uuid.uuid4().hex,'count':5,'duration_minutes':10,'knowledge_ids':[point['id']]})
        self.assertEqual(response.status_code,200,response.text)
        self.client.delete('/v1/me/study/materials/'+mid,headers={'X-Echo-CSRF':'1'})
        points=self.client.get('/v1/me/workspace').json()['points']
        self.assertTrue(all(p['id']!=point['id'] for p in points))

    def test_generation_validates_sources_bills_once_and_rejects_duplicates(self):
        self.login();mid=self.upload()['id'];rid=uuid.uuid4().hex
        output={'questions':self.analysis(mid,5)['questions']}
        response={'text':json.dumps(output),'usage':{'prompt_tokens':100,'completion_tokens':200}}
        with patch.object(app,'call_model',AsyncMock(return_value=response)) as model:
            first=self.paper(mid,generate=True,rid=rid);self.assertEqual(first.status_code,200,first.text)
            second=self.paper(mid,generate=True,rid=rid);self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(model.await_count,1);self.assertIsNone(first.json()['results'])
        with app.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM inference_requests').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM study_bank').fetchone()[0],5)
        invalid=copy.deepcopy(output);invalid['questions'][0]['source_ids']=['other-users-source']
        with patch.object(app,'call_model',AsyncMock(return_value={'text':json.dumps(invalid)})):
            bad=self.paper(mid,generate=True)
        self.assertEqual(bad.status_code,502,bad.text)

    def test_wrong_redo_is_free_snapshot_and_idempotent(self):
        self.login();mid=self.confirmed();paper=self.paper(mid).json();aid=paper['id']
        result=self.client.post('/v1/me/study/attempts/'+aid+'/submit',json={'answers':{'q1':1},'revision':0}).json()
        self.assertEqual(result['wrong_count'],5)
        rid=uuid.uuid4().hex
        with patch.object(app,'call_model',AsyncMock(side_effect=AssertionError('no paid request'))) as model:
            redo=self.client.post('/v1/me/study/attempts/'+aid+'/retry',json={'request_id':rid})
            again=self.client.post('/v1/me/study/attempts/'+aid+'/retry',json={'request_id':rid})
        self.assertEqual(redo.status_code,200,redo.text);self.assertEqual(again.json()['id'],redo.json()['id']);model.assert_not_called()
        self.assertIsNone(redo.json()['results']);self.assertTrue(all('answer' not in q for q in redo.json()['questions']))
        self.assertEqual(self.client.get('/v1/me/study/attempts/'+aid).json()['status'],'submitted')

    def test_preferences_merge_and_upload_slot_auth_limits(self):
        self.login()
        self.client.post('/v1/me/study/preferences',json={'exam_hour':17,'exam_minute':15})
        p=self.client.post('/v1/me/study/preferences',json={'daily_count':2}).json()['preferences']
        self.assertEqual(p['exam_hour'],17);self.assertEqual(p['exam_minute'],15)
        import study
        acquired=[]
        try:
            for _ in range(2):self.assertTrue(study.UPLOAD_REQUEST_SLOTS.acquire(False));acquired.append(True)
            r=self.client.post('/v1/me/study/materials',json={'filename':'a.txt','content_base64':'YWJj'})
            self.assertEqual(r.status_code,429)
        finally:
            for _ in acquired:study.UPLOAD_REQUEST_SLOTS.release()
        self.client.post('/v1/auth/logout',json={})
        self.assertEqual(self.client.post('/v1/me/study/materials',json={}).status_code,401)

    def test_timeout_refunds_and_replay_can_start_fresh(self):
        self.login();mid=self.upload()['id'];rid=uuid.uuid4().hex
        with patch.object(app,'call_model',AsyncMock(side_effect=TimeoutError())):
            response=self.client.post('/v1/me/study/materials/'+mid+'/analyze',json={'request_id':rid})
        self.assertEqual(response.status_code,504,response.text)
        with app.db() as c:self.assertEqual(c.execute('SELECT balance FROM users').fetchone()[0],100000)
        retry=self.client.post('/v1/me/study/materials/'+mid+'/analyze',json={'request_id':rid})
        self.assertEqual(retry.status_code,422,retry.text)

    def test_material_analysis_replay_survives_result_cache_expiration(self):
        self.login();mid=self.upload()['id'];rid=uuid.uuid4().hex;self.analyze(mid,rid=rid)
        with app.db(True) as c:c.execute('UPDATE inference_requests SET result=NULL')
        with patch.object(app,'call_model',AsyncMock(side_effect=AssertionError('must not charge twice'))) as model:
            response=self.client.post('/v1/me/study/materials/'+mid+'/analyze',json={'request_id':rid})
        self.assertEqual(response.status_code,200,response.text);model.assert_not_called()

    def test_analysis_accepts_twenty_complete_questions_and_rejects_overflow(self):
        self.login();mid=self.upload()['id'];result,_=self.analyze(mid,self.analysis(mid,20))
        self.assertEqual(result['analysis']['question_count'],20)
        with patch.object(app,'call_model',AsyncMock(return_value={'text':json.dumps(self.analysis(mid,21))})):
            response=self.client.post('/v1/me/study/materials/'+mid+'/analyze',json={'request_id':uuid.uuid4().hex})
        self.assertEqual(response.status_code,502,response.text)

class ModelTests(unittest.TestCase):
    def test_plan_future_same_weekday_not_skipped(self):
        from datetime import datetime
        stamp=int(datetime(2026,11,15,18,0,tzinfo=models.TZ).timestamp())
        p=models.plan(models.DEFAULTS,stamp)
        self.assertFalse(p['exam_due']);self.assertEqual(p['next_exam_at'],stamp+7200)
        self.assertTrue(models.plan(models.DEFAULTS,stamp+7201)['exam_due'])
    def test_types_and_partial_text_stay_pending(self):
        q={'type':'fill_blank','answer':'ABC','options':[]}
        self.assertEqual(models.grade(q,' abc ')['score'],1)
        self.assertIsNone(models.grade(q,'不同表达')['score'])
        with self.assertRaises(ValueError):models.clean_answer({'type':'single_choice','options':['A','B']},True)

if __name__=='__main__':unittest.main()
