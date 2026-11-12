"""Signed local/Docker update channel. No application data is sent to the server."""
import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
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


def _open(url, timeout=15):
    return urllib.request.build_opener(_NoRedirect()).open(
        urllib.request.Request(url, headers={"User-Agent": "Echo-Updater/1", "Accept-Encoding": "identity"}), timeout=timeout)


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
    if (release["format"] != "echo.update/1" or release["platform"] != "windows-x64" or release["channel"] != "stable"
            or release["filename"] != f"Echo-Setup-{release['version']}.exe"
            or type(release["size"]) is not int or not 1 <= release["size"] <= MAX_PACKAGE
            or not isinstance(release["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", release["sha256"])
            or not isinstance(release["notes"], list) or len(release["notes"]) > 12
            or any(not isinstance(note, str) or len(note) > 400 for note in release["notes"])
            or not isinstance(release["published_at"], str) or len(release["published_at"]) > 40):
        raise UpdateError("更新信息不符合当前平台或安装包约束")
    return release


def check_update(base, current=VERSION, public_key=None):
    base = validate_base_url(base)
    with _open(base + MANIFEST_PATH) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise UpdateError("更新信息过大")
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise UpdateError("更新服务返回了无法读取的信息") from exc
    release = verify_manifest(envelope, public_key)
    return {"available": version_tuple(release["version"]) > version_tuple(current), "release": release, "envelope": envelope}


def verify_package(path, release):
    path = Path(path)
    if path.name != release["filename"] or not path.is_file() or path.stat().st_size != release["size"]:
        raise UpdateError("安装包大小或文件名不匹配")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != release["sha256"]:
        raise UpdateError("安装包校验失败，请重新下载")
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise UpdateError("下载的文件不是 Windows 安装程序")
    return path


def download_update(base, envelope, destination, progress=lambda done, total: None, cancelled=lambda: False, public_key=None):
    base = validate_base_url(base)
    release = verify_manifest(envelope, public_key)
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
            with _open(base + "/artifacts/" + release["filename"], timeout=20) as response:
                received = 0
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
        # Check the same bytes before they become the installable cached file.
        if temporary.stat().st_size != release["size"]:
            raise UpdateError("下载未完成，请重试")
        with temporary.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != release["sha256"]:
                raise UpdateError("下载校验失败，文件未保存为安装包")
        with temporary.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise UpdateError("下载的文件不是 Windows 安装程序")
        os.replace(temporary, target)
        verify_package(target, release)
        return target
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
