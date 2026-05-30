
import sqlite3, json, os, shutil, zipfile
from pathlib import Path

ROOT = Path.cwd()
DB_CANDIDATES = [ROOT/'poolops2_local.db', ROOT/'poolops_local.db']
DB_PATH = next((p for p in DB_CANDIDATES if p.exists()), None)
if not DB_PATH:
    raise SystemExit('No poolops2_local.db or poolops_local.db found in this folder.')

EXPORT_DIR = ROOT/'heinlin_live_export'
if EXPORT_DIR.exists():
    shutil.rmtree(EXPORT_DIR)
EXPORT_DIR.mkdir(parents=True)

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cur = con.cursor()
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
keep = [t for t in tables if t.startswith('poolops2_') or t == 'field_logs']

payload = {'source_db': str(DB_PATH.name), 'tables': {}}
for t in keep:
    rows = [dict(r) for r in cur.execute(f'SELECT * FROM {t}').fetchall()]
    payload['tables'][t] = rows
    print(f'{t}: {len(rows)}')
con.close()

(EXPORT_DIR/'heinlin_live_data.json').write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')

uploads = ROOT/'app'/'static'/'uploads'
if uploads.exists():
    shutil.copytree(uploads, EXPORT_DIR/'uploads', dirs_exist_ok=True)

zip_path = ROOT/'heinlin_live_data_export.zip'
if zip_path.exists():
    zip_path.unlink()
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
    for p in EXPORT_DIR.rglob('*'):
        if p.is_file():
            z.write(p, p.relative_to(EXPORT_DIR))
print('\nDONE:', zip_path)
print('Upload/transport this ZIP for live import if needed.')
