"""Temporary signed artifacts: no real release files, database, or network."""
import base64,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import release_manager

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'artifacts').mkdir();(self.root/'candidates').mkdir()
        key=Ed25519PrivateKey.generate();self.key=key
        (self.root/'key.pem').write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        self.env=patch.dict(os.environ,{'ECHO_UPDATE_DIR':str(self.root),'ECHO_BETA_DIR':str(self.root),'ECHO_RELEASE_PUBLIC_KEY':str(self.root/'key.pem')});self.env.start()
        app=FastAPI()
        def fail(status,message):raise HTTPException(status,message)
        def auth(request,admin=False):
            if request.headers.get('Authorization')!='fixture-admin':fail(403,'denied')
            return {'id':'fixture'}
        async def payload(request):return await request.json()
        class DB:
            def __enter__(self):return None
            def __exit__(self,*args):pass
        release_manager.install(app,{'session_user':auth,'fail':fail,'payload':payload,'db':lambda *a:DB(),'audit':lambda *a:None,'rate':lambda *a:None})
        self.client=TestClient(app,headers={'Authorization':'fixture-admin'})
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def candidate(self,version='2.4.1',payload=b'MZfixture'):
        import hashlib
        filename='Echo-Setup-'+version+'.exe';(self.root/'artifacts'/filename).write_bytes(payload)
        release={'version':version,'filename':filename,'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'channel':'stable','platform':'windows-x64','format':'echo.update/1'}
        signature=base64.b64encode(self.key.sign(json.dumps(release,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())).decode()
        item={'release':release,'signature':signature};(self.root/'candidates'/'fixture.json').write_text(json.dumps(item));return item
    def test_signature_hash_and_version_immutability(self):
        item=self.candidate()
        r=self.client.post('/v1/admin/releases/publish',json={'channel':'stable','candidate':'fixture.json'});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(json.loads((self.root/'stable.json').read_text()),item)
        self.candidate(payload=b'MZchanged')
        self.assertEqual(self.client.post('/v1/admin/releases/publish',json={'channel':'stable','candidate':'fixture.json'}).status_code,400)
        self.candidate('2.4.0')
        self.assertEqual(self.client.post('/v1/admin/releases/publish',json={'channel':'stable','candidate':'fixture.json'}).status_code,400)
    def test_tampering_traversal_pause_and_auth(self):
        item=self.candidate();(self.root/'artifacts'/item['release']['filename']).write_bytes(b'MZtamper')
        self.assertEqual(self.client.post('/v1/admin/releases/publish',json={'channel':'stable','candidate':'fixture.json'}).status_code,400)
        self.assertEqual(self.client.post('/v1/admin/releases/publish',json={'channel':'stable','candidate':'../fixture.json'}).status_code,400)
        self.assertEqual(self.client.post('/v1/admin/releases/pause',json={'paused':True}).status_code,200)
        self.assertTrue(self.client.get('/v1/admin/releases').json()['paused'])
        self.assertEqual(self.client.get('/v1/admin/releases',headers={'Authorization':'user'}).status_code,403)

if __name__=='__main__':unittest.main()
