"""Signed local/Docker update channel. No application data is sent to the server."""
import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import time
from pathlib import Path

from echo.backend import paths
from echo.version import VERSION

MANIFEST_PATH = "/v1/releases/stable/windows-x64"
MAX_PACKAGE = 1024 * 1024 * 1024


class UpdateError(ValueError):
    pass


class Cancelled(UpdateError):
    pass


def canonical(release):
    return json.dumps(release, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def version_tuple(version):
    if not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version):
        raise UpdateError("更新版本号格式无效")
    return tuple(map(int, version.split(".")))


def validate_base_url(base):
    base = (base or "").strip().rstrip("/")
    value = urllib.parse.urlsplit(base)
    if (value.scheme not in ("https", "http") or not value.hostname or value.username or value.password
            or value.query or value.fragment or value.path not in ("", "/")):
        raise UpdateError("请填写更新服务的 HTTPS 根地址；本机可使用 http://127.0.0.1:8787")
    if value.scheme == "http" and value.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise UpdateError("远程更新地址必须使用 HTTPS，本机测试地址除外")
    return base


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise UpdateError("更新服务发生跳转，请检查已配置的服务地址")


def _open(url, timeout=15, auth_token=None):
    headers={"User-Agent": "Echo-Updater/1", "Accept-Encoding": "identity"}
    if auth_token:headers['Authorization']='Bearer '+auth_token
    import urllib.error,logging
    try:
        return urllib.request.build_opener(_NoRedirect()).open(
            urllib.request.Request(url, headers=headers), timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError,OSError,TimeoutError):
        logging.getLogger('echo.updater').exception('Update connection failed')
        raise UpdateError('无法连接更新服务，请检查网络或代理后重试。') from None


def verify_for_client(envelope, public_key=None):
    from echo import version
    if getattr(version,'CHANNEL','stable')!='beta':return verify_manifest(envelope,public_key)
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        item=dict(envelope);signature=item.pop('signature')
        key=load_pem_public_key(public_key or Path(paths.asset('assets','update-public-key.pem')).read_bytes())
        if not isinstance(key,Ed25519PublicKey):raise ValueError()
        key.verify(base64.b64decode(signature,validate=True),canonical(item))
        version_tuple(item['version'])
        if (item['filename'] not in ('Echo-Beta-Setup-'+item['version']+'.exe','Echo-Beta-Update-'+item['version']+'.zip') or type(item['size'])!=int
            or not 1<=item['size']<=MAX_PACKAGE or not re.fullmatch('[a-f0-9]{64}',item['sha256'])
            or not isinstance(item['notes'],list) or len(item['notes'])>12
            or any(not isinstance(n,str) or len(n)>400 for n in item['notes'])):raise ValueError()
        return {**item,'format':'echo.update/2' if item['filename'].endswith('.zip') else 'echo.update/1','channel':'beta','platform':'windows-x64'}
    except Exception as exc:raise UpdateError('内测更新签名或安装包信息无效。') from exc


def verify_manifest(envelope, public_key=None):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if not isinstance(envelope, dict) or set(envelope) != {"release", "signature"}:
        raise UpdateError("更新信息格式无效")
    release = envelope.get("release")
    required = {"format", "version", "platform", "channel", "filename", "size", "sha256", "notes", "published_at"}
    if not isinstance(release, dict) or set(release) != required:
        raise UpdateError("更新信息字段不完整")
    try:
        key = load_pem_public_key(public_key or Path(paths.asset("assets", "update-public-key.pem")).read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Wrong key type")
        signature = base64.b64decode(envelope["signature"], validate=True)
        key.verify(signature, canonical(release))
    except Exception as exc:
        raise UpdateError("更新签名校验失败，请勿安装该文件") from exc
    version_tuple(release["version"])
    expected_filename = f"Echo-Update-{release['version']}.zip" if release["format"] == "echo.update/2" else f"Echo-Setup-{release['version']}.exe"
    if (release["format"] not in ("echo.update/1", "echo.update/2") or release["platform"] != "windows-x64" or release["channel"] != "stable"
            or release["filename"] != expected_filename
            or type(release["size"]) is not int or not 1 <= release["size"] <= MAX_PACKAGE
            or not isinstance(release["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", release["sha256"])
            or not isinstance(release["notes"], list) or len(release["notes"]) > 12
            or any(not isinstance(note, str) or len(note) > 400 for note in release["notes"])
            or not isinstance(release["published_at"], str) or len(release["published_at"]) > 40):
        raise UpdateError("更新信息不符合当前平台或安装包约束")
    return release


def check_update(base, current=VERSION, public_key=None):
    from echo import version
    if getattr(version,'CHANNEL','stable')=='beta':
        from echo.backend import account
        envelope=account.request('/v1/beta/update?format=2')
        release=verify_for_client(envelope,public_key)
        return {'available':version_tuple(release['version'])>version_tuple(current),'release':release,'envelope':envelope}
    base = validate_base_url(base)
    import urllib.error
    try:
        response = _open(base + '/v2/releases/stable/windows-x64')
    except urllib.error.HTTPError as exc:
        if exc.code != 404: raise
        response = _open(base + MANIFEST_PATH)
    with response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise UpdateError("更新信息过大")
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise UpdateError("更新服务返回了无法读取的信息") from exc
    release = verify_for_client(envelope, public_key)
    return {"available": version_tuple(release["version"]) > version_tuple(current), "release": release, "envelope": envelope}


def verify_package(path, release):
    path = Path(path)
    if path.name != release["filename"] or not path.is_file() or path.stat().st_size != release["size"]:
        raise UpdateError("安装包大小或文件名不匹配")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != release["sha256"]:
        raise UpdateError("安装包校验失败，请重新下载")
    _verify_header(path, release)
    return path


def _verify_header(path, release):
    if release['format']=='echo.update/2':
        from echo.backend.fast_update import inspect_archive
        try: inspect_archive(path)
        except (ValueError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise UpdateError('快速更新包校验失败：'+str(exc)) from exc
    else:
        with Path(path).open('rb') as stream:
            if stream.read(2)!=b'MZ':raise UpdateError('下载的文件不是 Windows 安装程序')


def _open_range(url, start, end, timeout=20, auth_token=None):
    """带 Range 头打开一个下载流；返回 (response, supports_ranges)。"""
    import urllib.error
    headers = {"User-Agent": "Echo-Updater/1", "Accept-Encoding": "identity",
               "Range": f"bytes={start}-{end}"}
    if auth_token:
        headers["Authorization"] = "Bearer " + auth_token
    try:
        response = urllib.request.build_opener(_NoRedirect()).open(
            urllib.request.Request(url, headers=headers), timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError):
        raise UpdateError("无法连接更新服务，请检查网络或代理后重试。") from None
    code = getattr(response, "status", None) or response.getcode()
    if code == 206:
        return response, True
    with response:
        pass
    return None, False


def _download_threads(url, target, release, progress, cancelled, threads=12,
                      auth_token=None, max_bytes_per_second=0):
    """多线程分段下载：先探测 Range 支持，支持就 12 路并发拉，最后按序拼回。

    慢的主因是单连接吞吐（到美西的劣质路由单连接只有几 KB/s）；
    实测多连接近似线性放大（12 路 ≈ 单路 ×10）。服务器不支持 Range
    （没回 206）就返回 False，调用方退回单流。"""
    import concurrent.futures
    total = release["size"]
    probe, ok = _open_range(url, 0, 0, auth_token=auth_token)
    if not ok:
        return False
    with probe:
        probe.read(2)
    chunk = (total + threads - 1) // threads
    ranges = [(i, i * chunk, min((i + 1) * chunk - 1, total - 1))
              for i in range(threads) if i * chunk < total]
    parts = {i: target.with_name(target.name + f".part{i}") for i, _s, _e in ranges}
    received = {"bytes": 0}
    lock = threading.Lock()
    started = [time.monotonic()]

    def pull(item):
        index, start, end = item
        response, ok = _open_range(url, start, end, auth_token=auth_token)
        if not ok:
            raise UpdateError("下载服务器不支持分段续传")
        expected = end - start + 1
        got = 0
        with response, open(parts[index], "wb") as out:
            while True:
                if cancelled():
                    raise Cancelled("已取消下载")
                piece = response.read(128 * 1024)
                if not piece:
                    break
                got += len(piece)
                if got > expected:
                    raise UpdateError("分段下载超出声明范围")
                out.write(piece)
                with lock:
                    received["bytes"] += len(piece)
                    progress(received["bytes"], total)
                    if max_bytes_per_second:
                        while received["bytes"] / max_bytes_per_second - (time.monotonic() - started[0]) > 0:
                            if cancelled():
                                raise Cancelled("已取消下载")
                            time.sleep(max(0, min(.1, received["bytes"] / max_bytes_per_second - (time.monotonic() - started[0]))))
        return got == expected

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as pool:
            for ok in list(pool.map(pull, ranges)):
                if not ok:
                    raise UpdateError("分段下载未完成，请重试")
        with open(target, "wb") as out:
            for index, _s, _e in ranges:
                with open(parts[index], "rb") as piece:
                    shutil.copyfileobj(piece, out, 1024 * 1024)
        return True
    finally:
        for path in parts.values():
            try:
                path.unlink()
            except OSError:
                pass


def download_update(base, envelope, destination, progress=lambda done, total: None, cancelled=lambda: False, public_key=None,max_bytes_per_second=0):
    base = validate_base_url(base)
    release = verify_for_client(envelope, public_key)
    folder = Path(destination).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / release["filename"]
    if cancelled():
        raise Cancelled("已取消下载")
    try:
        verify_package(target, release)
        progress(release["size"], release["size"])
        return target
    except UpdateError:
        pass
    if shutil.disk_usage(folder).free < release["size"] + 100 * 1024 * 1024:
        raise UpdateError("磁盘空间不足，请清理后重试")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".echo-update-", suffix=".part", delete=False) as output:
            temporary = Path(output.name)
        url = None
        auth = None
        if release['channel']=='beta':
            from echo.backend import account
            if not account.token():raise UpdateError('请先登录内测账户再下载更新。')
            url=account.API_ORIGIN+'/v1/beta/download'+('?format=2' if release['format']=='echo.update/2' else '')
            auth=account.token()
        else:
            url=base + '/artifacts/' + release['filename']
        threaded = False
        if release["size"] > 4 * 1024 * 1024:
            # 大包走多线程分段下载（服务器支持 Range 时）；异常一律退回单流。
            try:
                threaded = _download_threads(url, temporary, release, progress, cancelled,
                                             auth_token=auth, max_bytes_per_second=max_bytes_per_second)
            except Cancelled:
                raise
            except (UpdateError, OSError, urllib.error.URLError, ValueError, RuntimeError):
                threaded = False
        if not threaded:
            response = _open(url, timeout=20, auth_token=auth)
            with response, open(temporary, "wb") as output:
                received = 0;started=time.monotonic()
                while True:
                    if cancelled():
                        raise Cancelled("已取消下载")
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > release["size"]:
                        raise UpdateError("下载内容超出声明大小")
                    output.write(chunk)
                    progress(received, release["size"])
                    if max_bytes_per_second:
                        while received/max_bytes_per_second-(time.monotonic()-started)>0:
                            if cancelled():raise Cancelled('已取消下载')
                            time.sleep(max(0,min(.1,received/max_bytes_per_second-(time.monotonic()-started))))
        # Check the same bytes before they become the installable cached file.
        if temporary.stat().st_size != release["size"]:
            raise UpdateError("下载未完成，请重试")
        with temporary.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != release["sha256"]:
                raise UpdateError("下载校验失败，文件未保存为安装包")
        _verify_header(temporary, release)
        os.replace(temporary, target)
        verify_package(target, release)
        return target
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
