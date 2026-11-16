"""Private account integration, no real model or mail calls."""
import copy,json,unittest,uuid
from unittest.mock import patch,AsyncMock
import test_accounts as fixtures
import qingjuan,storage
app=fixtures.app

def sample():
 return {'meta':{'title':'清卷验收','subject':'数学','duration':30},'sections':[{'title':'选择','questions':[{'type':'choice','stem':'2+2等于？','options':['4','5'],'answer':'A','analysis':'计算相加','score':2,'figure':{'kind':'coord','xRange':[-2,2],'yRange':[-2,2],'functions':[{'expr':'x*x'}]}}]}]}
class QingjuanTests(unittest.TestCase):
 setUp=fixtures.AccountTests.setUp
 tearDown=fixtures.AccountTests.tearDown
 admin=fixtures.AccountTests.admin
 def store(self,paper=None):
  r=self.client.post('/v1/me/qingjuan/papers',json={'request_id':uuid.uuid4().hex,'paper':paper or sample()});self.assertEqual(r.status_code,200,r.text);return r.json()['id']
 def test_private_import_attempt_grading_and_replay(self):
  self.admin();pid=self.store();aid=uuid.uuid4().hex
  with app.db() as c:
   row=c.execute('SELECT * FROM qingjuan_papers').fetchone();self.assertNotIn('清卷验收',row['cipher']);self.assertGreater(storage.used(c),0)
  base='/v1/me/qingjuan/papers/'+pid
  r=self.client.post(base+'/start',json={'request_id':aid});self.assertEqual(r.status_code,200,r.text);a=r.json();self.assertNotIn('answer',a['questions'][0]);self.assertIn('figure',a['questions'][0])
  self.assertEqual(self.client.post(base+'/start',json={'request_id':aid}).json()['id'],aid)
  other=self.store();self.assertEqual(self.client.post('/v1/me/qingjuan/papers/'+other+'/start',json={'request_id':aid}).status_code,409)
  r=self.client.post('/v1/me/study/attempts/'+aid+'/submit',json={'answers':{'q1':0},'revision':0});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['score'],100)
  self.client.delete(base);self.assertEqual(self.client.get('/v1/me/study/attempts/'+aid).status_code,200)
  self.client.post('/v1/auth/logout',json={});self.assertEqual(self.client.get(base).status_code,401)
 def test_ownership(self):
  self.admin();pid=self.store()
  with app.db(True) as c:
   uid=uuid.uuid4().hex;c.execute('INSERT INTO users(id,email,name,created) VALUES(?,?,?,?)',(uid,'qingjuan-other@example.com','Other',app.now()));token=uuid.uuid4().hex;c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(app.digest(token),uid,app.now()+600,app.now()))
  h={'Authorization':'Bearer '+token};self.assertEqual(self.client.get('/v1/me/qingjuan/papers/'+pid,headers=h).status_code,404)
  self.assertEqual(self.client.get('/v1/me/qingjuan/papers',headers=h).json()['items'],[])
 def test_invalid_remote_images_and_shape(self):
  self.admin()
  for raw in [{}, {'meta':{'title':'x'},'sections':[1]}]:
   self.assertEqual(self.client.post('/v1/me/qingjuan/papers',json={'request_id':uuid.uuid4().hex,'paper':raw}).status_code,400)
  p=sample();p['sections'][0]['questions'][0]['figure']={'kind':'image','src':'http://127.0.0.1/private'}
  self.assertEqual(self.client.post('/v1/me/qingjuan/papers',json={'request_id':uuid.uuid4().hex,'paper':p}).status_code,400)
 def test_generate_once_actual_usage(self):
  self.admin()
  with app.db(True) as c:c.execute('UPDATE users SET balance=100000')
  p=sample();p['sections'][0]['questions']*=5;data={'request_id':uuid.uuid4().hex,'knowledge':'加法','count':5}
  response={'text':json.dumps(p,ensure_ascii=False),'usage':{'prompt_tokens':100,'completion_tokens':200}}
  with patch.object(app,'call_model',AsyncMock(return_value=response)) as call:
   r=self.client.post('/v1/me/qingjuan/generate',json=data);self.assertEqual(r.status_code,200,r.text)
   self.assertEqual(self.client.post('/v1/me/qingjuan/generate',json=data).status_code,200);self.assertEqual(call.call_count,1)
  with app.db() as c:
   row=c.execute('SELECT * FROM inference_requests').fetchone();self.assertEqual(row['purpose'],'qingjuan_generate');self.assertEqual(row['input_tokens'],100)
 def test_shared_quota(self):
  self.admin();self.assertEqual(storage.LIMIT,128*1024*1024)
  with patch.object(storage,'used',return_value=storage.LIMIT):
   self.assertEqual(self.client.post('/v1/me/qingjuan/papers',json={'request_id':uuid.uuid4().hex,'paper':sample()}).status_code,409)
 def test_reading_conversion_preserves_context(self):
  p=sample();q=p['sections'][0]['questions'][0];p['sections'][0]['questions']=[{'type':'reading','stem':'阅读材料','passage':'材料内容','questions':[q]}]
  out=qingjuan.convert(qingjuan.normalize(p),'fixture');self.assertIn('材料内容',out[0]['question']);self.assertEqual(out[0]['answer'],0)
if __name__=='__main__':unittest.main()
