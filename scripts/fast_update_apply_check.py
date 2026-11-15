"""Windows rollback smoke test in a verified project-local scratch directory."""
import json
import os
import subprocess
from pathlib import Path
import uuid
ROOT=Path(__file__).resolve().parents[1]

def main():
    if os.name!='nt':print('SKIP Windows-only helper rollback test');return
    scratch=(ROOT/'.build'/('fast-update-rollback-'+uuid.uuid4().hex)).resolve()
    assert scratch.is_relative_to((ROOT/'.build').resolve())
    target=scratch/'Echo';staged=scratch/'.echo-stage-fixture'
    target.mkdir(parents=True);staged.mkdir()
    (target/'Echo.exe').write_bytes(b'MZoriginal-fixture')
    (target/'original.txt').write_text('preserve',encoding='utf-8')
    (staged/'Echo.exe').write_bytes(b'MZinvalid-new-executable')
    config=scratch/'apply.json'
    config.write_text(json.dumps({'target':str(target),'stage':str(staged),'parent_id':999999999}),encoding='utf-8')
    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result=subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-WindowStyle','Hidden','-ExecutionPolicy','RemoteSigned','-File',str(ROOT/'assets/apply-update.ps1'),'-ConfigFile',str(config)],cwd=str(scratch),capture_output=True,timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    assert (target/'Echo.exe').read_bytes()==b'MZoriginal-fixture',result.stderr
    assert (target/'original.txt').read_text(encoding='utf-8')=='preserve'
    assert 'prior version retained' in config.with_suffix('.log').read_text(encoding='utf-8-sig')
    assert (staged/'Echo.exe').is_file()
    print('PASS real Windows helper: failed new executable rolls back to intact old directory')

if __name__=='__main__':main()
