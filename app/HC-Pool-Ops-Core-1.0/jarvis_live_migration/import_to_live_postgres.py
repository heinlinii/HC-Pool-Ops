
import json, os, sys, zipfile, shutil
from pathlib import Path

try:
    import psycopg
except Exception as e:
    raise SystemExit('Missing psycopg. Run: pip install "psycopg[binary]"') from e

ROOT = Path.cwd()
DATABASE_URL = os.environ.get('DATABASE_URL') or (sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith('postgres') else '')
if not DATABASE_URL:
    raise SystemExit('DATABASE_URL is missing. Run this on Render Shell or pass the Postgres URL as the first argument.')

zip_arg = None
for a in sys.argv[1:]:
    if a.endswith('.zip'):
        zip_arg = a
        break

if zip_arg:
    export_zip = Path(zip_arg)
else:
    export_zip = ROOT/'heinlin_live_data_export.zip'

work = ROOT/'heinlin_live_import_work'
if work.exists():
    shutil.rmtree(work)
work.mkdir(parents=True)

if export_zip.exists():
    with zipfile.ZipFile(export_zip, 'r') as z:
        z.extractall(work)
    data_file = work/'heinlin_live_data.json'
else:
    data_file = ROOT/'heinlin_live_export'/'heinlin_live_data.json'

if not data_file.exists():
    raise SystemExit(f'Could not find export JSON: {data_file}')

payload = json.loads(data_file.read_text(encoding='utf-8'))
tables = payload.get('tables', {})

SCHEMA = [
"""CREATE TABLE IF NOT EXISTS poolops2_users (id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT DEFAULT 'admin', name TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS poolops2_clients (id INTEGER PRIMARY KEY, name TEXT NOT NULL, contact_name TEXT DEFAULT '', phone TEXT DEFAULT '', mobile TEXT DEFAULT '', email TEXT DEFAULT '', billing_address TEXT DEFAULT '', shipping_address TEXT DEFAULT '', city TEXT DEFAULT '', state TEXT DEFAULT '', zip_code TEXT DEFAULT '', company TEXT DEFAULT '', notes TEXT DEFAULT '', portal_username TEXT DEFAULT '', portal_password TEXT DEFAULT '', card_image TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS poolops2_properties (id INTEGER PRIMARY KEY, client_id INTEGER, client TEXT DEFAULT '', property_name TEXT DEFAULT '', address TEXT DEFAULT '', city TEXT DEFAULT '', state TEXT DEFAULT '', zip_code TEXT DEFAULT '', pool_type TEXT DEFAULT '', pool_size TEXT DEFAULT '', pool_depth TEXT DEFAULT '', cover_type TEXT DEFAULT '', finish_type TEXT DEFAULT '', pump_model TEXT DEFAULT '', filter_model TEXT DEFAULT '', heater_model TEXT DEFAULT '', sanitizer TEXT DEFAULT '', automation_system TEXT DEFAULT '', gate_code TEXT DEFAULT '', service_plan TEXT DEFAULT '', notes TEXT DEFAULT '', card_image TEXT DEFAULT '', latitude REAL, longitude REAL, pool_notes TEXT DEFAULT '', equipment_notes TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS poolops2_jobs (id INTEGER PRIMARY KEY, client TEXT DEFAULT '', property TEXT DEFAULT '', address TEXT DEFAULT '', job_type TEXT DEFAULT '', status TEXT DEFAULT 'Pending', crew TEXT DEFAULT 'Unassigned', date TEXT DEFAULT '', priority TEXT DEFAULT 'Normal', notes TEXT DEFAULT '', scheduled_start TEXT, scheduled_end TEXT, card_image TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS poolops2_employees (id INTEGER PRIMARY KEY, name TEXT DEFAULT '', role TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '', active INTEGER DEFAULT 1, card_image TEXT DEFAULT '', username TEXT DEFAULT '', password TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS poolops2_photo_logs (id INTEGER PRIMARY KEY, job_id INTEGER, property_id INTEGER, client TEXT DEFAULT '', photo_type TEXT DEFAULT 'Progress', title TEXT DEFAULT '', photo_url TEXT DEFAULT '', date TEXT DEFAULT '', notes TEXT DEFAULT '', latitude REAL, longitude REAL)""",
"""CREATE TABLE IF NOT EXISTS poolops2_calendar_day_images (id INTEGER PRIMARY KEY, day_date TEXT UNIQUE NOT NULL, image_url TEXT DEFAULT '', notes TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS poolops2_equipment (id INTEGER PRIMARY KEY, property_id INTEGER, equipment_type TEXT DEFAULT '', brand TEXT DEFAULT '', model TEXT DEFAULT '', serial TEXT DEFAULT '', installed_date TEXT DEFAULT '', notes TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS poolops2_estimates (id INTEGER PRIMARY KEY, client TEXT DEFAULT '', property TEXT DEFAULT '', title TEXT DEFAULT '', status TEXT DEFAULT 'Draft', amount REAL DEFAULT 0, notes TEXT DEFAULT '', created_at TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS field_logs (id INTEGER PRIMARY KEY, employee_name TEXT DEFAULT '', crew TEXT DEFAULT '', client TEXT DEFAULT '', property TEXT DEFAULT '', address TEXT DEFAULT '', date TEXT DEFAULT '', arrival_time TEXT DEFAULT '', departure_time TEXT DEFAULT '', total_hours REAL DEFAULT 0, tools_used TEXT DEFAULT '', materials_used TEXT DEFAULT '', equipment_used TEXT DEFAULT '', work_completed TEXT DEFAULT '', issues TEXT DEFAULT '', next_steps TEXT DEFAULT '', weather TEXT DEFAULT '', photo_count INTEGER DEFAULT 0, created_at TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS poolops2_job_costs (id INTEGER PRIMARY KEY, job_id INTEGER, client TEXT DEFAULT '', labor REAL DEFAULT 0, materials REAL DEFAULT 0, subs REAL DEFAULT 0, equipment REAL DEFAULT 0, fuel REAL DEFAULT 0, other REAL DEFAULT 0, invoice_amount REAL DEFAULT 0, notes TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS poolops2_office_notes (id INTEGER PRIMARY KEY, note TEXT DEFAULT '', created_at TEXT DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS poolops2_invoices (id INTEGER PRIMARY KEY, job_id INTEGER, client TEXT DEFAULT '', description TEXT DEFAULT '', amount REAL DEFAULT 0, status TEXT DEFAULT 'Draft', date TEXT DEFAULT '', notes TEXT DEFAULT '')""",
]

ORDER = ['poolops2_users','poolops2_clients','poolops2_properties','poolops2_jobs','poolops2_employees','poolops2_photo_logs','poolops2_calendar_day_images','poolops2_equipment','poolops2_estimates','field_logs','poolops2_job_costs','poolops2_office_notes','poolops2_invoices']

def cols_for(cur, table):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))
    return [r[0] for r in cur.fetchall()]

with psycopg.connect(DATABASE_URL) as con:
    with con.cursor() as cur:
        for ddl in SCHEMA:
            cur.execute(ddl)
        con.commit()
        for table in ORDER:
            if table not in tables:
                continue
            records = tables[table]
            if not records:
                print(table, 0)
                continue
            dest_cols = cols_for(cur, table)
            insert_count = 0
            for row in records:
                cols = [c for c in row.keys() if c in dest_cols]
                vals = [row.get(c) for c in cols]
                placeholders = ','.join(['%s']*len(cols))
                col_sql = ','.join(cols)
                conflict = 'id' if 'id' in cols else None
                if conflict:
                    update_cols = [c for c in cols if c != 'id']
                    updates = ','.join([f"{c}=EXCLUDED.{c}" for c in update_cols]) or 'id=EXCLUDED.id'
                    sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) ON CONFLICT (id) DO UPDATE SET {updates}"
                else:
                    sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"
                cur.execute(sql, vals)
                insert_count += 1
            print(table, insert_count)
        con.commit()

print('\nDONE. Live Postgres data import complete.')
print('Restart Render service, then test Invisible Office search: larry / bulkley')
