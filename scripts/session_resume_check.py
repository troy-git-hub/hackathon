"""Upgrade/restart session persistence with fake vault, real current-user DPAPI."""
import copy,json,os,sys,tempfile,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from echo.backend import account,credential_backup,paths
from echo import version


def main():
    vault={};who={'id':'fixture-user','name':'测试同学','email':'fixture@example.com','balance':5,'role':'user'}
    fake=SimpleNamespace(set_password=lambda s,k,v:vault.__setitem__((s,k),v),get_password=lambda s,k:vault.get((s,k)),delete_password=lambda s,k:vault.pop((s,k),None))
    with tempfile.TemporaryDirectory(prefix='echo-resume-') as folder,patch.object(paths,'config_dir',return_value=folder),patch.dict(sys.modules,{'keyring':fake}),patch.object(version,'CHANNEL','stable'):
        with patch.object(account,'request',return_value={'token':'test-session-secret','user':who}):account.login(who['email'],password='test-password')
        assert account._vault_service()=='Echo.Account'
        backup=credential_backup._file(account._vault_service())
        if os.name=='nt':
            assert backup.exists() and b'test-session-secret' not in backup.read_bytes() and b'fixture@example.com' not in backup.read_bytes()
            encrypted=backup.read_bytes()
        with patch.object(account,'request',side_effect=account.AccountError('temporary network')):
            restored=account.restore()
        assert restored['id']==who['id'] and restored['_session_offline'] and account.token()=='test-session-secret'
        assert vault[('Echo.Account','session')]=='test-session-secret'
        if os.name=='nt':assert backup.read_bytes()==encrypted
        # A new process, updated executable or temporary unavailable vault still
        # has the same OS user-bound backup; do not use any real vault entries.
        if os.name=='nt':
            vault.clear();account._token='';account._user=None
            with patch.object(account,'request',return_value={'user':who}):assert account.restore()['id']==who['id']
            assert account.token()=='test-session-secret'
            from echo.backend.fast_update import stage
            install=Path(folder)/'app';install.mkdir();(install/'Echo.exe').write_bytes(b'MZ-old')
            archive=Path(folder)/'update.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('Echo.exe',b'MZ-new');z.writestr('_internal/test.dll',b'fixture')
            before=backup.read_bytes();snapshot=dict(vault);stage(archive,install)
            assert backup.read_bytes()==before and vault==snapshot
        # A legacy session without an identity cache stays saved on outage and
        # can be retried without asking for the user's password again.
        credential_backup.clear('Echo.Account');vault.clear();vault[('Echo.Account','session')]='legacy-session'
        with patch.object(account,'request',side_effect=account.AccountError('temporary network')):
            try:account.restore()
            except account.AccountError as exc:assert '重试连接' in str(exc)
            else:raise AssertionError('missing identity should request retry')
        assert vault[('Echo.Account','session')]=='legacy-session'
        with patch.object(account,'request',return_value={'user':who}):assert account.restore()['id']==who['id']
        # Stable and beta remain separate, while version-number changes do not
        # affect either vault name.
        with patch.object(version,'CHANNEL','beta'):
            assert account.restore() is None
            with patch.object(account,'request',return_value={'token':'beta-session','user':who}):account.login(who['email'])
        with patch.object(account,'request',return_value={'user':who}):assert account.restore()['id']==who['id']
        assert account.token()=='legacy-session'
        with patch.object(account,'request',side_effect=account.AccountError('expired',401)):assert account.restore() is None
        assert not account.token() and not account.current_user() and '过期' in account.restore_message()
        assert ('Echo.Account','session') not in vault and not credential_backup._file('Echo.Account').exists()
        assert vault[('Echo.Account.Beta','session')]=='beta-session'
        with patch.object(version,'CHANNEL','beta'),patch.object(account,'request',return_value={'user':who}):assert account.restore()['id']==who['id']
        with patch.object(version,'CHANNEL','beta'),patch.object(account,'request',return_value={'ok':True}):account.logout()
        assert not vault and not list(Path(folder).glob('*.dpapi'))
    print('PASS vault/DPAPI restart and update staging, offline retention, legacy retry, channel isolation, expiry and explicit logout')


if __name__=='__main__':main()
