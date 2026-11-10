"""Verify directory/portable apps and a disposable per-user installation before delivery."""
import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def execute(argv, timeout=120):
    result = subprocess.run(list(map(str, argv)), timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{Path(argv[0]).name} exited with {result.returncode}")


def application_check(executable, report):
    execute([executable, "--self-test", "--report", report])
    data = json.loads(report.read_text(encoding="utf-8"))
    if not data.get("ok") or not data.get("frozen"):
        raise RuntimeError(f"Packaged self-test failed: {report}")
    print(f"PASS {executable}: speech / Qt / HTML / isolated data", flush=True)
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--version", default="2.2.0")
    args = parser.parse_args()
    build = Path(args.build_dir).resolve()
    dist = build / "dist"
    installer = dist / f"Echo-Setup-{args.version}.exe"
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    tests = {}
    tests["directory"] = application_check(dist / "Echo/Echo.exe", artifacts / "release-directory-check.json")
    tests["portable"] = application_check(dist / "Echo.exe", artifacts / "release-portable-check.json")
    spec = importlib.util.spec_from_file_location("build_release", ROOT / "scripts/build_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    valid, detail = module.verify_installer(installer)
    if not valid:
        raise RuntimeError(detail)
    print("PASS installer PE and payload structure", flush=True)
    trial = Path(tempfile.mkdtemp(prefix="echo-install-qa-", dir=artifacts)).resolve()
    if not trial.is_relative_to(artifacts.resolve()):
        raise RuntimeError("Test install must stay inside the workspace's artifact directory")
    target = trial / "application"
    execute([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/ECHOQA=1",
             f"/DIR={target}", f"/LOG={trial / 'install.log'}"], timeout=240)
    tests["installed"] = application_check(target / "Echo.exe", trial / "installed-check.json")
    execute([target / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=120)
    if (target / "Echo.exe").exists():
        raise RuntimeError("Disposable installation did not uninstall completely")
    tests["install_uninstall"] = True
    print("PASS isolated installation, installed HTML runtime and uninstall", flush=True)
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    delivered = []
    for source, name in ((dist / "Echo.exe", f"Echo-{args.version}.exe"), (installer, installer.name)):
        destination = output / name
        shutil.copy2(source, destination)
        delivered.append({"name": name, "bytes": destination.stat().st_size,
                          "sha256": hashlib.file_digest(destination.open("rb"), "sha256").hexdigest()})
    manifest = {"version": args.version, "verified": True, "files": delivered, "tests": tests}
    (output / f"release-verification-{args.version}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(delivered, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
