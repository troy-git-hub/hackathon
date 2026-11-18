"""Pinned beta signatures and channel separation; no network or real credentials."""
import base64,json,sys,tempfile,hashlib
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from echo import version
from echo.backend import updater,account

def main():
    key=Ed25519PrivateKey.generate();pub=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    package=b'MZisolated-fixture'
    item={'version':'2.5.2','filename':'Echo-Beta-Setup-2.5.2.exe','size':len(package),'sha256':hashlib.sha256(package).hexdigest(),'notes':['fixture'],'published_at':'2026-11-15T00:00:00Z'}
    envelope={**item,'signature':base64.b64encode(key.sign(updater.canonical(item))).decode()}
    with patch.object(version,'CHANNEL','beta',create=True),patch.object(account,'request',return_value=envelope) as call:
        result=updater.check_update('https://update.echo.xhbtroy.cn',current='2.5.1',public_key=pub)
        assert result['available'] and result['release']['channel']=='beta'
        assert call.call_args.args[0]=='/v1/beta/update?format=2'
        assert not updater.check_update('https://update.echo.xhbtroy.cn',current='2.5.2',public_key=pub)['available']
        altered={**envelope,'version':'9.9.9'}
        try:updater.verify_for_client(altered,pub)
        except updater.UpdateError:pass
        else:raise AssertionError('unsigned beta metadata accepted')
        with tempfile.TemporaryDirectory() as folder,patch.object(account,'token',return_value='fixture-session'):
            import io
            with patch.object(updater,'_open',return_value=io.BytesIO(package)) as opened:
                saved=updater.download_update('https://update.echo.xhbtroy.cn',envelope,folder,public_key=pub)
                assert saved.read_bytes()==package
                assert opened.call_args.args[0]==account.API_ORIGIN+'/v1/beta/download'
                assert opened.call_args.kwargs['auth_token']=='fixture-session'
    import io,zipfile
    zipped=io.BytesIO()
    with zipfile.ZipFile(zipped,'w') as archive:archive.writestr('Echo.exe',b'MZfixture');archive.writestr('_internal/fixture.dll',b'fixture')
    package=zipped.getvalue();fast={**item,'filename':'Echo-Beta-Update-2.5.2.zip','size':len(package),'sha256':hashlib.sha256(package).hexdigest()}
    fast={**fast,'signature':base64.b64encode(key.sign(updater.canonical(fast))).decode()}
    with patch.object(version,'CHANNEL','beta',create=True),patch.object(account,'token',return_value='fixture-session'):
        assert updater.verify_for_client(fast,pub)['format']=='echo.update/2'
        with tempfile.TemporaryDirectory() as folder,patch.object(updater,'_open',return_value=io.BytesIO(package)) as opened:
            updater.download_update('https://update.echo.xhbtroy.cn',fast,folder,public_key=pub)
            assert opened.call_args.args[0].endswith('/v1/beta/download?format=2')
    with patch.object(version,'CHANNEL','stable',create=True):
        try:updater.verify_for_client(envelope,pub)
        except updater.UpdateError:pass
        else:raise AssertionError('beta accepted in stable channel')
    print('PASS beta authenticated channel, pinned signature, tamper rejection, no downgrade, stable separation')

if __name__=='__main__':main()
