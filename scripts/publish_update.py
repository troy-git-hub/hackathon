"""Generate the project release key or publish a signed local update."""
import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echo.backend.updater import canonical, verify_manifest, version_tuple


def generate_keys(private_file, public_file):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    private_file, public_file = Path(private_file), Path(public_file)
    if private_file.exists() or public_file.exists():
        raise ValueError("密钥文件已存在；不会覆盖已有的客户端信任密钥")
    key = Ed25519PrivateKey.generate()
    private_file.parent.mkdir(parents=True, exist_ok=True)
    public_file.parent.mkdir(parents=True, exist_ok=True)
    private_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    os.chmod(private_file, 0o600)
    public_file.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))


def publish(installer, version, private_file, data_dir, notes, public_key=None, validate_pe=True):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    version_tuple(version)
    source, data_dir = Path(installer).resolve(), Path(data_dir).resolve()
    if source.name != f"Echo-Setup-{version}.exe":
        raise ValueError("安装包文件名和发布版本不一致")
    if validate_pe:
        from scripts.build_release import verify_installer
        valid, reason = verify_installer(source)
        if not valid: raise ValueError(reason)
    key = load_pem_private_key(Path(private_file).read_bytes(), password=None)
    with source.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    release = {"format": "echo.update/1", "version": version, "platform": "windows-x64", "channel": "stable",
               "filename": source.name, "size": source.stat().st_size, "sha256": sha, "notes": notes,
               "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    envelope = {"release": release, "signature": base64.b64encode(key.sign(canonical(release))).decode("ascii")}
    verify_manifest(envelope, public_key)
    artifacts = data_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    stable = data_dir / "stable.json"
    if stable.exists():
        previous = json.loads(stable.read_text(encoding="utf-8"))
        old = verify_manifest(previous, public_key)
        if version_tuple(old["version"]) > version_tuple(version):
            raise ValueError("稳定渠道不允许回退到旧版本")
    target = artifacts / source.name
    if target.exists():
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != sha:
                raise ValueError("此版本已发布不同文件，请增加版本号")
    else:
        temporary = target.with_suffix(".upload")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    temp_manifest = None
    try:
        with tempfile.NamedTemporaryFile(dir=data_dir, mode="w", encoding="utf-8", delete=False) as stream:
            temp_manifest = Path(stream.name)
            json.dump(envelope, stream, ensure_ascii=False, indent=2)
        os.replace(temp_manifest, stable)
    finally:
        if temp_manifest: temp_manifest.unlink(missing_ok=True)
    return envelope


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["keys", "publish"])
    parser.add_argument("--private-key", type=Path, default=ROOT / ".build/update-secrets/release-private-key.pem")
    parser.add_argument("--public-key", type=Path, default=ROOT / "assets/update-public-key.pem")
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--data", type=Path, default=ROOT / "update-server/data")
    parser.add_argument("--notes", type=Path, help="UTF-8 file, one release note per line")
    args = parser.parse_args()
    if args.action == "keys":
        generate_keys(args.private_key, args.public_key)
        print("Created project signing key. Private key stays in .build/update-secrets; only the public key ships.")
    else:
        if not args.installer or not args.version:
            parser.error("publish requires --installer and --version")
        notes = args.notes.read_text(encoding="utf-8").splitlines() if args.notes else ["Echo 版本更新"]
        publish(args.installer, args.version, args.private_key, args.data, [n.strip() for n in notes if n.strip()], args.public_key.read_bytes())
        print(f"Published signed release {args.version} to {args.data}")


if __name__ == "__main__":
    main()
