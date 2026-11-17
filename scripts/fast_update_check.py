"""Signed ZIP-channel tests and path safety, using isolated fake distributions only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from echo.backend import updater,fast_update
from scripts.publish_update import generate_keys
from scripts.publish_fast_update import publish

def main():
    with tempfile.TemporaryDirectory(prefix='echo-fast-update-test-') as d:
        root=Path(d);built=root/'built';built.mkdir();(built/'_internal').mkdir();(built/'_internal/runtime.dll').write_bytes(b'fixture');(built/'Echo.exe').write_bytes(b'MZ'+b'fixture'*400)
        private=root/'private.pem';public=root/'public.pem';generate_keys(private,public)
        data=root/'data';package=publish(built,'2.4.1',data,private,public.read_bytes(),['Fixture'])
        from scripts.update_http_fixture import create_server
        server=create_server(data,host='127.0.0.1',port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            info=updater.check_update('http://127.0.0.1:'+str(server.server_port),current='2.4.0',public_key=public.read_bytes())
            assert info['available'] and info['release']['format']=='echo.update/2'
            got=updater.download_update('http://127.0.0.1:'+str(server.server_port),info['envelope'],root/'downloads',public_key=public.read_bytes())
            assert got.read_bytes()==package.read_bytes()
            installed=root/'app';installed.mkdir();(installed/'Echo.exe').write_bytes(b'MZold');(installed/'unins000.exe').write_bytes(b'MZuninstaller')
            staged=fast_update.stage(got,installed)
            assert (staged/'Echo.exe').read_bytes()==(built/'Echo.exe').read_bytes()
            assert (installed/'Echo.exe').read_bytes()==b'MZold'
            assert (staged/'unins000.exe').is_file()
            for name in ('../escape.txt','/absolute.txt','C:/evil.txt','a\\evil.txt','CON','folder/../bad','folder/x.','.env'):
                bad=root/'bad.zip'
                with zipfile.ZipFile(bad,'w') as z:
                    z.writestr('Echo.exe',b'MZfixture');z.writestr('_internal/a',b'a')
                    unsafe=zipfile.ZipInfo('unsafe');unsafe.filename=name
                    z.writestr(unsafe,b'bad')
                try:fast_update.inspect_archive(bad)
                except ValueError:pass
                else:raise AssertionError('Unsafe ZIP accepted: '+name)
            print('PASS signed ZIP channel, HTTP download, staging, uninstall preservation, traversal and reserved paths')
        finally:server.shutdown();server.server_close()

if __name__=='__main__':main()
