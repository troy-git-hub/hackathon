"""Real local HTTP, signatures, tampering, cancellation and update UI checks."""
import copy
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['ECHO_OFFLINE'] = '1'


def wait(app, predicate, timeout=8):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        app.processEvents()
        if predicate(): return
        time.sleep(.01)
    raise AssertionError('operation timed out')


def main():
    with tempfile.TemporaryDirectory(prefix='echo-update-test-') as directory:
        base = Path(directory)
        from echo.backend import paths, updater
        paths.config_dir = lambda: directory
        from scripts.publish_update import generate_keys, publish
        private, public = base/'key.pem', base/'public.pem'
        generate_keys(private, public)
        pub = public.read_bytes()
        file = base/'Echo-Setup-9.4.1.exe'
        file.write_bytes(b'MZ' + b'TEST PACKAGE' * 40000)
        data = base/'server'
        envelope = publish(file, '9.4.1', private, data, ['测试更新；不是真实安装程序'], pub, validate_pe=False)
        from scripts.update_http_fixture import create_server
        server = create_server(data, host='127.0.0.1', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            result = updater.check_update(url, public_key=pub)
            assert result['available'] and result['release']['version'] == '9.4.1'
            assert not updater.check_update(url, current='9.4.1', public_key=pub)['available']
            assert not updater.check_update(url, current='9.5.0', public_key=pub)['available']
            progress = []
            package = updater.download_update(url, envelope, base/'downloads', lambda n,t: progress.append(n), public_key=pub)
            assert package.read_bytes() == file.read_bytes() and progress[-1] == file.stat().st_size
            altered = copy.deepcopy(envelope)
            altered['release']['version'] = '9.9.9'
            try:
                updater.verify_manifest(altered, pub)
                raise AssertionError('unsigned metadata accepted')
            except updater.UpdateError: pass
            for address in ('http://example.com', 'file:///tmp/a', 'https://user:pass@example.com', 'https://example.com/a?key=secret'):
                try:
                    updater.validate_base_url(address)
                    raise AssertionError('unsafe update origin accepted')
                except updater.UpdateError: pass
            try:
                updater.download_update(url, envelope, base/'cancel', cancelled=lambda: True, public_key=pub)
                raise AssertionError('cancel ignored')
            except updater.Cancelled: pass
            cancel_calls = []
            def cancel_midway(n,t): cancel_calls.append(n)
            try:
                updater.download_update(url, envelope, base/'cancel-mid', cancel_midway, lambda: bool(cancel_calls), pub)
                raise AssertionError('mid-stream cancel ignored')
            except updater.Cancelled: pass
            assert not list((base/'cancel-mid').glob('*'))
            (data/'artifacts'/file.name).write_bytes(b'MZ'+b'X'*(file.stat().st_size-2))
            try:
                updater.download_update(url, envelope, base/'tampered', public_key=pub)
                raise AssertionError('tampered package accepted')
            except updater.UpdateError: pass
            assert not list((base/'tampered').glob('*'))
            try:
                updater._open(url+'/artifacts/../key.pem')
                raise AssertionError('path traversal served')
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
            (data/'artifacts'/file.name).write_bytes(file.read_bytes())

            from PyQt5.QtCore import QSettings, Qt
            from PyQt5.QtWidgets import QApplication
            QSettings.setDefaultFormat(QSettings.IniFormat)
            QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, directory)
            app = QApplication([])
            from echo.theme import apply_theme
            apply_theme(app)
            from echo.widgets.update_center import UpdateController
            controller = UpdateController()
            controller.configure(url, True)
            original_check, original_download = updater.check_update, updater.download_update
            with patch.object(updater, 'check_update', side_effect=lambda address: original_check(address, public_key=pub)), \
                 patch.object(updater, 'download_update', side_effect=lambda *a,**k: original_download(*a, **k, public_key=pub)):
                controller.show()
                with patch.object(paths,'is_frozen',return_value=True):controller.check()
                wait(app, lambda: controller.state == 'available')
                assert controller.dialog.primary.text() == '下载更新'
                if '--shots' in sys.argv:
                    (ROOT/'artifacts').mkdir(exist_ok=True)
                    controller.dialog.grab().save(str(ROOT/'artifacts/echo-update-available.png'))
                with patch.object(paths,'is_frozen',return_value=True):controller.download()
                wait(app, lambda: controller.state == 'ready')
                assert not controller.dialog.primary.isEnabled()  # source mode cannot replace itself
                original_verify = updater.verify_manifest
                with patch.object(paths, 'is_frozen', return_value=True), \
                     patch.object(updater, 'verify_for_client', side_effect=lambda value: original_verify(value, pub)), \
                     patch('subprocess.Popen') as launch, patch.object(app, 'quit') as quit_app:
                    controller.package.write_bytes(b'corrupted after download')
                    controller.install()
                    launch.assert_not_called()
                    assert controller.state == 'error'
                    controller.package.write_bytes(file.read_bytes())
                    controller.state = 'ready'
                    controller.install()
                    launch.assert_called_once()
                    assert '/UPDATE=1' in launch.call_args.args[0]
                    quit_app.assert_called_once()
                with patch.object(controller, 'in_class', return_value=True), patch('subprocess.Popen') as launch:
                    controller.install()
                    launch.assert_not_called()
                controller.state = 'checking'
                generation = controller.generation
                controller.cancel()
                controller._finished(generation, 'check', result, '')
                assert controller.state == 'cancelled'  # stale result cannot revive cancelled work
                controller.dialog.close()
            controller.state = 'idle'
            with patch.object(updater,'check_update') as network:
                controller.start();controller.auto_check();controller.check();controller.download()
                network.assert_not_called()
                assert controller.state=='disabled' and not controller.poll.isActive()
            with patch.object(controller, 'in_class', return_value=True), patch.object(controller, 'check') as check:
                controller.auto_check()
                check.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
    print('PASS HTTP updates, pinned signatures, checksums, cancellation, traversal, UI states and lecture deferral')


if __name__ == '__main__':
    main()
