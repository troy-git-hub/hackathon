import unittest,uuid,copy
import test_accounts as fixtures
import test_qingjuan
app=fixtures.app
class SummaryTests(unittest.TestCase):
 setUp=fixtures.AccountTests.setUp
 tearDown=fixtures.AccountTests.tearDown
 admin=fixtures.AccountTests.admin
 def test_empty_and_unauthorized(self):
  self.assertEqual(self.client.get('/v1/me/summary').status_code,401);self.admin();r=self.client.get('/v1/me/summary');self.assertEqual(r.status_code,200,r.text);d=r.json();self.assertEqual(d['study']['answered'],0);self.assertIsNone(d['study']['average_score']);self.assertEqual(len(d['daily']),7)
 def test_weighted_scores_pending_exclusion_usage_and_isolation(self):
  self.admin();p=test_qingjuan.sample();q=copy.deepcopy(p['sections'][0]['questions'][0]);q['score']=1;p['sections'][0]['questions'].append(q)
  pid=uuid.uuid4().hex;r=self.client.post('/v1/me/qingjuan/papers',json={'request_id':pid,'paper':p});self.assertEqual(r.status_code,200,r.text)
  aid=uuid.uuid4().hex;self.client.post('/v1/me/qingjuan/papers/'+pid+'/start',json={'request_id':aid});self.client.post('/v1/me/study/attempts/'+aid+'/submit',json={'answers':{'q1':0,'q2':1},'revision':0})
  p['sections'][0]['questions']=[{'type':'short','stem':'说明原因','answer':'参考','analysis':'解释','score':2}];pid2=uuid.uuid4().hex;self.client.post('/v1/me/qingjuan/papers',json={'request_id':pid2,'paper':p});aid2=uuid.uuid4().hex;self.client.post('/v1/me/qingjuan/papers/'+pid2+'/start',json={'request_id':aid2});self.client.post('/v1/me/study/attempts/'+aid2+'/submit',json={'answers':{'q1':'我的解释'},'revision':0})
  with app.db(True) as c:
   uid=c.execute('SELECT id FROM users').fetchone()[0]
   for state,cost,age in [('succeeded',2000,0),('pending',5000,0),('failed',0,0),('succeeded',9000,9*86400)]:c.execute('INSERT INTO inference_requests(user_id,request_id,request_hash,task,state,cost,created,input_tokens,output_tokens) VALUES(?,?,?,?,?,?,?,?,?)',(uid,uuid.uuid4().hex,'fixture','text',state,cost,app.now()-age,100,200))
  d=self.client.get('/v1/me/summary').json();s=d['study'];self.assertEqual(s['answered'],3);self.assertEqual(s['submitted'],2);self.assertEqual(s['graded'],1);self.assertEqual(s['average_score'],66.7);self.assertEqual(s['pending'],1);self.assertEqual(s['papers'],2);self.assertEqual(d['usage_7d']['points'],2);self.assertEqual(d['usage_7d']['input_tokens'],100);self.assertEqual(sum(i['answered'] for i in d['daily']),3)
  with app.db(True) as c:
   uid2=uuid.uuid4().hex;c.execute('INSERT INTO users(id,email,name,created) VALUES(?,?,?,?)',(uid2,'summary-other@example.com','Other',app.now()));token=uuid.uuid4().hex;c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(app.digest(token),uid2,app.now()+600,app.now()))
  d=self.client.get('/v1/me/summary',headers={'Authorization':'Bearer '+token}).json();self.assertEqual(d['study']['papers'],0);self.assertEqual(d['recent_attempts'],[]);self.assertEqual(d['usage_7d']['requests'],0);self.assertEqual(d['storage']['used_bytes'],0)
if __name__=='__main__':unittest.main()
