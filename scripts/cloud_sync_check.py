"""Isolated cloud sync checks. No real user files, credentials, or network are used."""
import copy,json,os,sys,tempfile,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from echo.backend import account,cloud_sync,paths,store

class SyncTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='echo-sync-fixture-');self.path_patch=patch.object(paths,'config_dir',return_value=self.temp.name);self.path_patch.start()
  self.user_patch=patch.object(account,'_user',{'id':'fixture-owner','name':'Fixture'});self.user_patch.start();self.token_patch=patch.object(account,'_token','fixture-session');self.token_patch.start()
  self.profile=json.loads((ROOT/'docs/examples/learning-profile.json').read_text(encoding='utf-8'))
  self.export_patch=patch.object(cloud_sync.learning_export,'build_export',side_effect=lambda **kw:copy.deepcopy(self.profile));self.export_patch.start()
  self.uploads=[];self.remote={'protocol':'echo.sync/1','account_id':'fixture-owner','preferences':{'auto_sync':True},'devices':[],'reviews':[]}
 def tearDown(self):
  self.export_patch.stop();self.token_patch.stop();self.user_patch.stop();self.path_patch.stop();self.temp.cleanup()
 def request(self,path,data=None,**kw):
  self.assertEqual(path,'/v1/me/sync')
  self.assertEqual(kw.get('auth_token'),'fixture-session')
  if data is None:return copy.deepcopy(self.remote)
  self.uploads.append(data);self.remote['devices']=[{'id':data['device_id'],'revision':data['base_revision']+1,'updated':int(time.time())}]
  return {'ok':True,'revision':data['base_revision']+1,'updated':int(time.time())}
 def test_default_upload_and_unchanged_data_is_not_reuploaded(self):
  with patch.object(account,'request',side_effect=self.request):
   self.assertEqual(cloud_sync.sync_once()['state'],'synced')
   self.assertEqual(cloud_sync.sync_once()['state'],'synced')
  self.assertEqual(len(self.uploads),1)
  self.assertEqual(self.uploads[0]['profile']['format'],'echo.learning-profile')
  self.assertNotIn('token',self.uploads[0]);self.assertNotIn('api_key',self.uploads[0])
  state=json.loads((Path(self.temp.name)/'cloud-sync.json').read_text(encoding='utf-8'))
  self.assertNotIn('fixture-session',json.dumps(state))
 def test_skip_and_local_pause_never_upload(self):
  with patch.object(account,'_token',''),patch.object(account,'request') as call:
   self.assertEqual(cloud_sync.sync_once()['state'],'signed-out');call.assert_not_called()
  cloud_sync.configure(enabled=False)
  with patch.object(account,'request') as call:
   self.assertEqual(cloud_sync.sync_once()['state'],'paused');call.assert_not_called()
 def test_other_account_cannot_receive_existing_local_library(self):
  cloud_sync.configure(bind=True)
  with patch.object(account,'_user',{'id':'another-user','name':'Other'}),patch.object(account,'request') as call:
   self.assertEqual(cloud_sync.sync_once()['state'],'account-mismatch');call.assert_not_called()
 def test_account_switch_during_fetch_does_not_merge_or_upload(self):
  def changed(*args,**kw):
   account._user={'id':'other','name':'Other'};return self.remote
  with patch.object(account,'request',side_effect=changed),patch.object(cloud_sync,'_apply_reviews') as merge:
   self.assertEqual(cloud_sync.sync_once()['state'],'error');merge.assert_not_called()
 def test_server_pause_and_network_failure_keep_local_data(self):
  self.remote['preferences']['auto_sync']=False
  with patch.object(account,'request',side_effect=self.request):self.assertEqual(cloud_sync.sync_once()['state'],'paused')
  self.assertFalse(self.uploads)
  with patch.object(account,'request',side_effect=account.AccountError('fixture offline')):
   self.assertEqual(cloud_sync.sync_once()['state'],'error')
  self.assertEqual(cloud_sync.status()['last_success'],0)
 def test_new_web_progress_merges_once_and_newer_local_progress_wins(self):
  stamp=int(time.time())-30
  review={'knowledge_id':'fixture-topic','topic':'测试知识','reviewed_at':stamp,'due':stamp+86400,'level':2,'review_count':3,'last_result':'clear','reviewed':True}
  self.assertEqual(cloud_sync._apply_reviews([review]),1)
  self.assertEqual(cloud_sync._apply_reviews([review]),0)
  self.assertEqual(store.load()[0]['review_count'],3)
  store.grade('测试知识','again',now=stamp+10)
  self.assertEqual(cloud_sync._apply_reviews([review]),0)
  self.assertEqual(store.load()[0]['last_result'],'again')
 def test_corrupt_state_stops_sync_instead_of_rebinding(self):
  (Path(self.temp.name)/'cloud-sync.json').write_text('{broken',encoding='utf-8')
  with patch.object(account,'request') as call:
   self.assertEqual(cloud_sync.sync_once()['state'],'error');call.assert_not_called()
 def test_same_named_cross_subject_reviews_do_not_overwrite_legacy_local_topic(self):
  stamp=int(time.time())-20
  base={'topic':'关系','reviewed_at':stamp,'due':stamp+86400,'level':2,'review_count':3,'last_result':'clear','reviewed':True}
  self.assertEqual(cloud_sync._apply_reviews([{**base,'knowledge_id':'math-relation'},{**base,'knowledge_id':'language-relation'}]),0)
  self.assertEqual(store.load(),[])

 def test_multiple_terminals_merge_selected_no_echo_or_cross_account(self):
  from datetime import datetime,timezone
  a,b=uuid.uuid4().hex,uuid.uuid4().hex;stamp=int(time.time())-300
  def archive(title,when):return {'id':'lesson_'+'a'*24,'title':title,'ended_at':datetime.fromtimestamp(when,timezone.utc).isoformat(),'duration_seconds':60,'summary':'回顾','suggestion':'','highlights':[],'skills':[{'name':title,'status':'ok','mastery':.8}],'blackboard_notes':'','truncated':False}
  sources={a:{'protocol':'echo.snapshot/1','account_id':'fixture-owner','device_id':a,'revision':1,'profile':self.profile,'classroom':{'protocol':'echo.classroom/1','lessons':[archive('数学·来自A',stamp)]}},b:{'protocol':'echo.snapshot/1','account_id':'fixture-owner','device_id':b,'revision':1,'profile':self.profile,'classroom':{'protocol':'echo.classroom/1','lessons':[archive('英语·来自B',stamp+1)]}}}
  self.remote['devices']=[{'id':a,'name':'A','revision':1,'updated':stamp},{'id':b,'name':'B','revision':1,'updated':stamp}]
  store._write_json(store._lessons_path(),[{'time':stamp-1,'title':'本机课程','duration':10,'skills_detail':[]}])
  reads=[]
  def request(path,data=None,**kw):
   if '/snapshot' in path:
    ident=path.split('/')[-2];reads.append(ident);return copy.deepcopy(sources[ident])
   if data is None:return copy.deepcopy(self.remote)
   self.uploads.append(data);existing=[d for d in self.remote['devices'] if d['id']!=data['device_id']]
   self.remote['devices']=existing+[{'id':data['device_id'],'revision':data['base_revision']+1,'updated':stamp,'name':data['device_name']}]
   return {'revision':data['base_revision']+1,'updated':stamp}
  with patch.object(account,'request',side_effect=request):
   self.assertEqual(cloud_sync.sync_once()['state'],'synced');self.assertEqual(len(store.list_lessons()),3)
   self.assertEqual(len(self.uploads[0]['classroom']['lessons']),1)
   self.assertEqual(cloud_sync.sync_once()['state'],'synced');self.assertEqual(len(reads),2);self.assertEqual(len(self.uploads),1)
   cloud_sync.configure(mode='selected',source_ids=[a]);self.assertEqual(cloud_sync.sync_once()['state'],'synced')
   self.assertEqual({v['title'] for v in store.list_lessons()},{'本机课程','数学·来自A'})
  account._user={'id':'another-account'}
  self.assertEqual([v['title'] for v in store.list_lessons()],['本机课程'])
 def test_snapshot_wrong_owner_never_overwrites_local(self):
  ident=uuid.uuid4().hex;self.remote['devices']=[{'id':ident,'name':'remote','revision':1,'updated':1}]
  def request(path,*a,**kw):return self.remote if path=='/v1/me/sync' else {'protocol':'echo.snapshot/1','account_id':'wrong','device_id':ident,'revision':1,'classroom':{'protocol':'echo.classroom/1','lessons':[]}}
  with patch.object(account,'request',side_effect=request):self.assertEqual(cloud_sync.sync_once()['state'],'error')
  self.assertEqual(store.list_lessons(),[])

if __name__=='__main__':unittest.main()
