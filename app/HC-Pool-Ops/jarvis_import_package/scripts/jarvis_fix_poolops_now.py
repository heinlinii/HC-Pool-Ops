import sqlite3
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
APP_DB = ROOT / "poolops2_local.db"
IMPORT_DB = ROOT / "poolops_local.db"
BACKUP_DIR = ROOT / "jarvis_backups"

def rows(conn, sql):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql).fetchall()]

def table_exists(conn, name):
    return conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

def count(conn, table):
    if not table_exists(conn, table):
        return 0
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

def val(row, *names, default=""):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return default

def main():
    print("ROOT:", ROOT)
    BACKUP_DIR.mkdir(exist_ok=True)

    if APP_DB.exists():
        backup = BACKUP_DIR / "poolops2_local_before_jarvis_fix.db"
        shutil.copy2(APP_DB, backup)
        print("Backup saved:", backup)

    # Pick the DB that actually has the imported clients/properties/jobs.
    candidates = []
    for p in [IMPORT_DB, APP_DB]:
        if p.exists():
            c = sqlite3.connect(p)
            try:
                candidates.append((count(c, "clients"), count(c, "properties"), count(c, "jobs"), p))
            finally:
                c.close()

    source = None
    for client_count, prop_count, job_count, p in sorted(candidates, reverse=True):
        if client_count or prop_count or job_count:
            source = p
            print(f"Using imported data from {p.name}: clients={client_count}, properties={prop_count}, jobs={job_count}")
            break

    if source is None:
        print("ERROR: I could not find imported data in poolops_local.db or poolops2_local.db")
        sys.exit(1)

    src = sqlite3.connect(source)
    dst = sqlite3.connect(APP_DB)
    dst.execute("PRAGMA foreign_keys=OFF")

    # These are the tables the current app/models.py reads.
    dst.executescript("""
    CREATE TABLE IF NOT EXISTS poolops2_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'crew',
        name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS poolops2_employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        active BOOLEAN DEFAULT 1,
        card_image TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS poolops2_clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        contact_name TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        mobile TEXT DEFAULT '',
        email TEXT DEFAULT '',
        billing_address TEXT DEFAULT '',
        shipping_address TEXT DEFAULT '',
        city TEXT DEFAULT '',
        state TEXT DEFAULT '',
        zip_code TEXT DEFAULT '',
        company TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        portal_username TEXT DEFAULT '',
        portal_password TEXT DEFAULT '',
        card_image TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS poolops2_properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        client TEXT NOT NULL,
        property_name TEXT DEFAULT '',
        address TEXT NOT NULL,
        city TEXT DEFAULT '',
        state TEXT DEFAULT '',
        zip_code TEXT DEFAULT '',
        pool_type TEXT DEFAULT '',
        pool_size TEXT DEFAULT '',
        pool_depth TEXT DEFAULT '',
        cover_type TEXT DEFAULT '',
        finish_type TEXT DEFAULT '',
        pump_model TEXT DEFAULT '',
        filter_model TEXT DEFAULT '',
        heater_model TEXT DEFAULT '',
        sanitizer TEXT DEFAULT '',
        automation_system TEXT DEFAULT '',
        gate_code TEXT DEFAULT '',
        service_plan TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        card_image TEXT DEFAULT '',
        latitude FLOAT,
        longitude FLOAT
    );

    CREATE TABLE IF NOT EXISTS poolops2_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client TEXT NOT NULL,
        property TEXT DEFAULT '',
        address TEXT DEFAULT '',
        check_in_time DATETIME,
        check_in_lat FLOAT,
        check_in_lng FLOAT,
        check_out_time DATETIME,
        check_out_lat FLOAT,
        check_out_lng FLOAT,
        job_type TEXT DEFAULT '',
        status TEXT DEFAULT 'Pending',
        crew TEXT DEFAULT 'Unassigned',
        date TEXT DEFAULT '',
        scheduled_start DATETIME,
        scheduled_end DATETIME,
        priority TEXT DEFAULT 'Normal',
        notes TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS poolops2_invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER,
        client TEXT NOT NULL,
        description TEXT NOT NULL,
        amount FLOAT DEFAULT 0,
        status TEXT DEFAULT 'Draft',
        date TEXT DEFAULT '',
        notes TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS poolops2_job_costs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER,
        client TEXT NOT NULL,
        labor FLOAT DEFAULT 0,
        materials FLOAT DEFAULT 0,
        subs FLOAT DEFAULT 0,
        equipment FLOAT DEFAULT 0,
        fuel FLOAT DEFAULT 0,
        other FLOAT DEFAULT 0,
        invoice_amount FLOAT DEFAULT 0,
        notes TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS poolops2_photo_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER,
        client TEXT NOT NULL,
        photo_type TEXT DEFAULT 'Progress',
        title TEXT NOT NULL,
        photo_url TEXT DEFAULT '/static/logo.png',
        date TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        property_id INTEGER,
        latitude FLOAT,
        longitude FLOAT
    );

    CREATE TABLE IF NOT EXISTS field_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_name TEXT DEFAULT '', crew TEXT DEFAULT '', client TEXT DEFAULT '', property TEXT DEFAULT '', address TEXT DEFAULT '',
        date TEXT DEFAULT '', arrival_time TEXT DEFAULT '', departure_time TEXT DEFAULT '', total_hours FLOAT DEFAULT 0,
        truck TEXT DEFAULT '', trailer TEXT DEFAULT '', tools_used TEXT DEFAULT '', materials_used TEXT DEFAULT '', equipment_used TEXT DEFAULT '',
        fuel_cost FLOAT DEFAULT 0, work_completed TEXT DEFAULT '', issues TEXT DEFAULT '', next_steps TEXT DEFAULT '', weather TEXT DEFAULT '',
        photo_count INTEGER DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Clear UI tables so sync is clean/repeatable.
    for t in ["poolops2_clients", "poolops2_properties", "poolops2_jobs", "poolops2_invoices", "poolops2_photo_logs"]:
        dst.execute(f"DELETE FROM {t}")

    # Always create a login that works.
    dst.execute("INSERT OR IGNORE INTO poolops2_users (username,password,role,name) VALUES (?,?,?,?)", ("mike", "mike", "admin", "Mike"))
    dst.execute("INSERT OR IGNORE INTO poolops2_employees (name,role,phone,email,active,card_image) VALUES (?,?,?,?,?,?)", ("Mike", "admin", "", "", 1, ""))

    # Clients
    client_rows = rows(src, "SELECT * FROM clients") if table_exists(src, "clients") else []
    for r in client_rows:
        dst.execute("""
            INSERT INTO poolops2_clients
            (id, name, contact_name, phone, mobile, email, billing_address, shipping_address, city, state, zip_code, company, notes, portal_username, portal_password, card_image)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            val(r, "id", default=None),
            val(r, "client_name", "name", default="Unnamed Client"),
            val(r, "contact_name"),
            val(r, "phone"),
            val(r, "mobile"),
            val(r, "email"),
            val(r, "billing_address"),
            val(r, "shipping_address"),
            val(r, "city"),
            val(r, "state"),
            val(r, "zip_code"),
            val(r, "source", "company"),
            val(r, "notes"),
            val(r, "portal_username"),
            val(r, "portal_password"),
            val(r, "card_image"),
        ))

    # Properties
    prop_rows = rows(src, "SELECT * FROM properties") if table_exists(src, "properties") else []
    for r in prop_rows:
        address = val(r, "full_address", "address", "street", "raw_address", default="Address missing")
        dst.execute("""
            INSERT INTO poolops2_properties
            (id, client_id, client, property_name, address, city, state, zip_code, notes, card_image, latitude, longitude)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            val(r, "id", default=None),
            val(r, "client_id", default=None),
            val(r, "client_name", "client", default="Unknown Client"),
            val(r, "property_name", default=address),
            address,
            val(r, "city"),
            val(r, "state"),
            val(r, "zip_code"),
            val(r, "notes"),
            val(r, "card_image"),
            val(r, "latitude", default=None),
            val(r, "longitude", default=None),
        ))

    # Jobs
    job_rows = rows(src, "SELECT * FROM jobs") if table_exists(src, "jobs") else []
    for r in job_rows:
        dst.execute("""
            INSERT INTO poolops2_jobs
            (id, client, property, address, job_type, status, crew, date, priority, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            val(r, "id", default=None),
            val(r, "client_name", "client", default="Unknown Client"),
            val(r, "property_name", "property"),
            val(r, "address"),
            val(r, "job_type"),
            val(r, "status", default="Pending"),
            val(r, "crew", default="Unassigned"),
            str(val(r, "scheduled_date", "raw_date", "date")),
            val(r, "priority", default="Normal"),
            val(r, "notes"),
        ))

    # Invoices, if present.
    inv_rows = rows(src, "SELECT * FROM invoices") if table_exists(src, "invoices") else []
    for r in inv_rows:
        try:
            amount = float(val(r, "amount", default=0) or 0)
        except Exception:
            amount = 0
        dst.execute("""
            INSERT INTO poolops2_invoices (client, description, amount, status, date, notes)
            VALUES (?,?,?,?,?,?)
        """, (
            val(r, "client_name", "client", default="Unknown Client"),
            val(r, "description", default="Invoice"),
            amount,
            val(r, "status", default="Draft"),
            str(val(r, "invoice_date", "raw_date", "date")),
            val(r, "notes"),
        ))

    # Photo logs, if present.
    photo_rows = rows(src, "SELECT * FROM photo_logs") if table_exists(src, "photo_logs") else []
    for r in photo_rows:
        dst.execute("""
            INSERT INTO poolops2_photo_logs (job_id, client, photo_type, title, photo_url, date, notes, property_id, latitude, longitude)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            val(r, "job_id", default=None),
            val(r, "client_name", "client", default="Unknown Client"),
            val(r, "photo_type", default="Progress"),
            val(r, "title", default="Photo"),
            val(r, "photo_url", default="/static/logo.png"),
            str(val(r, "photo_date", "raw_date", "date")),
            val(r, "notes"),
            val(r, "property_id", default=None),
            val(r, "latitude", default=None),
            val(r, "longitude", default=None),
        ))

    dst.commit()

    final_counts = {
        "poolops2_users": count(dst, "poolops2_users"),
        "poolops2_clients": count(dst, "poolops2_clients"),
        "poolops2_properties": count(dst, "poolops2_properties"),
        "poolops2_jobs": count(dst, "poolops2_jobs"),
        "poolops2_invoices": count(dst, "poolops2_invoices"),
        "poolops2_photo_logs": count(dst, "poolops2_photo_logs"),
    }

    src.close()
    dst.close()

    print("\nDONE. PoolOps UI tables are fixed:")
    for k, v in final_counts.items():
        print(f"  {k}: {v}")
    print("\nLogin: mike / mike")
    print("Open: http://127.0.0.1:8000/clients")

if __name__ == "__main__":
    main()
