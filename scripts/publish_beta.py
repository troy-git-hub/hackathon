"""Sign and stage a beta release manifest (installer EXE or fast-update ZIP).

Build artifacts with scripts/build_release.py --beta first, then:

    python scripts/publish_beta.py --installer dist/Echo-Beta-Setup-2.6.8.exe \
        --version 2.6.8 --notes-file docs/beta-notes-2.6.8.md

Beta manifest format (matches account-server release_manager.validate, channel=beta):
top-level {version, filename, size, sha256, notes, published_at, signature}; the
signature covers the canonical JSON of everything except "signature". The private
key never leaves this machine; the server only re-verifies.
"""
import argparse
import base64
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echo.backend.updater import canonical, version_tuple  # noqa: E402

PUBLIC_KEY = ROOT / "assets" / "update-public-key.pem"
PRIVATE_KEY = ROOT / ".build" / "update-secrets" / "release-private-key.pem"
STAGING = ROOT / "artifacts" / "beta-candidates"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", type=Path, default=None, help="Echo-Beta-Setup-x.y.z.exe")
    ap.add_argument("--zip", type=Path, default=None, help="Echo-Beta-Update-x.y.z.zip")
    ap.add_argument("--version", required=True)
    ap.add_argument("--notes-file", type=Path, default=None)
    ap.add_argument("--notes", default="")
    ap.add_argument("--out", type=Path, default=STAGING, help="候选清单输出目录")
    args = ap.parse_args()
    if bool(args.installer) == bool(args.zip):
        raise SystemExit("──installer 或 ──zip 二选一")
    source = Path(args.installer or args.zip).resolve()
    version_tuple(args.version)
    expected = source.name
    if args.installer and expected != f"Echo-Beta-Setup-{args.version}.exe":
        raise SystemExit(f"安装包文件名应为 Echo-Beta-Setup-{args.version}.exe，实际 {source.name}")
    if args.zip and expected != f"Echo-Beta-Update-{args.version}.zip":
        raise SystemExit(f"更新包文件名应为 Echo-Beta-Update-{args.version}.zip，实际 {source.name}")
    from scripts.build_release import verify_installer
    if args.installer:
        ok, detail = verify_installer(source)
        if not ok:
            raise SystemExit(f"安装包结构自检不通过：{detail}")

    with source.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    if args.notes_file:
        notes = [line.strip() for line in args.notes_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        notes = [line.strip() for line in args.notes.splitlines() if line.strip()] or ["Echo 内测更新。"]
    release = {
        "version": args.version,
        "filename": source.name,
        "size": source.stat().st_size,
        "sha256": sha,
        "notes": notes,
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
    key = load_pem_private_key(PRIVATE_KEY.read_bytes(), password=None)
    signature = base64.b64encode(key.sign(canonical(release))).decode("ascii")
    envelope = {**release, "signature": signature}
    load_pem_public_key(PUBLIC_KEY.read_bytes()).verify(
        base64.b64decode(signature, validate=True), canonical(release))

    args.out.mkdir(parents=True, exist_ok=True)
    candidate = args.out / f"beta-{args.version}-{source.stem}.json"
    candidate.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    staged = args.out / source.name
    shutil.copy2(source, staged)
    print(f"候选清单: {candidate}")
    print(f"上传文件: {staged}")
    print(f"version={args.version} size={release['size']} sha256={sha}")


if __name__ == "__main__":
    main()
