#!/bin/sh
set -eu
cd '/opt/echo/Echo Website'
docker compose exec -T accounts python - <<'PY'
import sqlite3
from pathlib import Path
from datetime import datetime,timezone
folder=Path('/data/backups')
folder.mkdir(mode=0o700,exist_ok=True)
name=datetime.now(timezone.utc).strftime('%Y-%m-%d')+'.sqlite'
with sqlite3.connect('/data/accounts.sqlite') as source,sqlite3.connect(folder/name) as target:
    source.backup(target)
for path in sorted(folder.glob('????-??-??.sqlite'))[:-7]:
    if path.resolve().parent==folder.resolve():path.unlink()
print('Account backup completed; last seven snapshots retained.')
PY
