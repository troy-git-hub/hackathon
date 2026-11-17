"""Desktop account integration checks with isolated storage and a fake credential vault."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['ECHO_OFFLINE']='1'

def main():
    from echo.backend import account,paths,providers
    fake_user={'id':'fixture','email':'fixture@example.com','name':'Fixture','balance':100,'role':'user'}
    vault={}
    fake_vault=SimpleNamespace(set_password=lambda service,name,value:vault.update({name:value}),get_password=lambda service,name:vault.get(name),delete_password=lambda service,name:vault.pop(name,None))
    with tempfile.TemporaryDirectory(prefix='echo-account-client-') as d,patch.object(paths,'config_dir',return_value=d),patch.dict(sys.modules,{'keyring':fake_vault}),patch.dict(os.environ,{'ECHO_ACCOUNT_ACTIVE':'1','ECHO_ACCOUNT_CUSTOM_API':'0'}):
        with patch.object(account,'request',return_value={'token':'fixture-session','user':fake_user}):
            account.login('fixture@example.com',code='123456')
        assert vault['session']=='fixture-session'
        assert providers.text()['id']=='echo' and providers.vision()['model']=='echo-vision'
        assert providers.text()['base_url']=='https://api.echo.xhbtroy.cn/v1'
        reply={'protocol':'echo.inference/1','account':{'id':'fixture','balance':99,'charged_points':1},'result':{'text':'fixture result','usage':{}}}
        with patch.object(account,'request',return_value=reply) as call:
            result=providers.client(providers.text()).chat.completions.create(model='echo-text',messages=[{'role':'user','content':'fixture'}])
            assert result.choices[0].message.content=='fixture result'
            assert call.call_args.args[0]=='/v1/echo/inference'
            assert call.call_args.args[1]['account_id']=='fixture'
            assert call.call_args.args[1]['protocol']=='echo.inference/2'
            assert call.call_args.args[1]['purpose']=='assistant'
        with patch.object(account,'request',side_effect=[account.AccountError('temporary network'),reply]) as call:
            account.inference('text',{'messages':[{'role':'user','content':'fixture'}]})
            assert call.call_args_list[0].args[1]['request_id']==call.call_args_list[1].args[1]['request_id']
        events=iter([('reasoning',{'text':'fixture thought'}),('delta',{'text':'stream '}),('delta',{'text':'fixture'})])
        with patch.object(account,'inference_stream',return_value=(item for item in events)) as call:
            stream=providers.client(providers.vision()).chat.completions.create(model='echo-vision',messages=[{'role':'user','content':'fixture'}],stream=True)
            chunks=list(stream)
            assert ''.join(chunk.choices[0].delta.content or '' for chunk in chunks)=='stream fixture'
            assert chunks[0].choices[0].delta.reasoning_content=='fixture thought'
            assert call.call_args.args[0]=='vision'
            stream.close()
        with patch.dict(os.environ,{'ECHO_ACCOUNT_CUSTOM_API':'1'}):assert providers.text()['id']!='echo'
        with patch.object(account,'request',return_value={'ok':True}):account.logout()
        assert not account.token() and 'session' not in vault
        assert providers.text()['id']=='echo' and not providers.configured()
        from PyQt5.QtWidgets import QApplication
        qt=QApplication.instance() or QApplication([])
        from echo.widgets.account_login import AccountLogin
        login=AccountLogin()
        assert login.invite.isHidden() and not login.password.isHidden() and login.code.isHidden()
        login.password_login.setChecked(False)
        assert login.password.isHidden() and not login.code.isHidden()
        login.register.setChecked(True)
        assert not login.invite.isHidden() and not login.name.isHidden() and not login.password.isHidden() and not login.confirm_password.isHidden()
        login.close()
        from echo.widgets import settings
        example=Path(d)/'.env';example.write_text('ECHO_LLM_PROVIDER=deepseek\nECHO_LLM_API_KEY=fixture\n',encoding='utf-8')
        with patch.object(settings,'ENV_PATH',str(example)):
            dialog=settings.SettingsDialog()
            assert dialog.advanced_widget.isHidden()
            assert dialog.custom_api.isChecked() is False
            dialog.advanced_toggle.setChecked(True)
            assert not dialog.advanced_widget.isHidden()
            dialog.close()
        assert not list(Path(d).glob('*session*'))
        from echo.backend import cloud_sync
        from echo.widgets.cloud_sync import CloudSyncController
        from PyQt5.QtWidgets import QWidget,QLabel
        from PyQt5.QtTest import QTest
        import time
        window=QWidget();window.home_account_card=QWidget(window);window.home_account_card.sub_lbl=QLabel(window)
        controller=CloudSyncController(window)
        with patch.object(cloud_sync,'sync_once',return_value={'state':'synced','message':'isolated sync complete'}):
            controller.sync_now()
            deadline=time.monotonic()+2
            while controller.busy and time.monotonic()<deadline:qt.processEvents();QTest.qWait(10)
        assert not controller.busy and window.home_account_card.sub_lbl.text()=='isolated sync complete'
        controller.stop();window.close()
        guest=AccountLogin(allow_skip=True)
        assert not guest.skip.isHidden()
        guest.skip.click()
        assert guest.skipped and os.getenv('ECHO_ACCOUNT_GUEST')=='1'
        assert not account.managed_models() and not account.token()
        guest.close()
    print('PASS desktop vault sessions, managed models, logout gating, invitation UI and advanced settings')

if __name__=='__main__':main()
