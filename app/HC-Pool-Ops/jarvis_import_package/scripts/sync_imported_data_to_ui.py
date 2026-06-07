import sqlite3
from pathlib import Path

DB = Path("poolops_local.db")

def col_exists(cur, table, col):
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

def table_exists(cur, table):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None

def clean(v):
    return "" if v is None else str(v)

def first_existing(row, names, default=""):
    for n in names:
        if n in row.keys() and row[n] not in (None, ""):
            return row[n]
    return default

def main():
    if not DB.exists():
        raise SystemExit("poolops_local.db not found. Run this from the HC-Pool-Ops-FIXED-BY-JARVIS folder.")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # UI tables expected by the existing app/routes/templates.
    cur.execute("""
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
        )
    """)

    cur.execute("""
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
            latitude REAL,
            longitude REAL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS poolops2_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client TEXT NOT NULL,
            property TEXT DEFAULT '',
            address TEXT DEFAULT '',
            check_in_time DATETIME,
            check_in_lat REAL,
            check_in_lng REAL,
            check_out_time DATETIME,
            check_out_lat REAL,
            check_out_lng REAL,
            job_type TEXT DEFAULT '',
            status TEXT DEFAULT 'Pending',
            crew TEXT DEFAULT 'Unassigned',
            date TEXT DEFAULT '',
            scheduled_start DATETIME,
            scheduled_end DATETIME,
            priority TEXT DEFAULT 'Normal',
            notes TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS poolops2_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'crew',
            name TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS poolops2_employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            card_image TEXT DEFAULT ''
        )
    """)

    cur.execute("INSERT OR IGNORE INTO poolops2_users (username,password,role,name) VALUES (?,?,?,?)", ("mike","mike","admin","Mike"))
    cur.execute("INSERT OR IGNORE INTO poolops2_employees (name,role,phone,email,active,card_image) VALUES (?,?,?,?,?,?)", ("Mike","admin","","",1,""))

    # Clear UI mirror tables and rebuild from imported source tables.
    cur.execute("DELETE FROM poolops2_clients")
    cur.execute("DELETE FROM poolops2_properties")
    cur.execute("DELETE FROM poolops2_jobs")

    if table_exists(cur, "clients"):
        for r in cur.execute("SELECT * FROM clients").fetchall():
            name = clean(first_existing(r, ["client_name", "name"], "Unnamed Client"))
            contact = clean(first_existing(r, ["contact_name"], ""))
            phone = clean(first_existing(r, ["phone"], ""))
            email = clean(first_existing(r, ["email"], ""))
            notes = clean(first_existing(r, ["notes"], ""))
            username = clean(first_existing(r, ["portal_username"], ""))
            password = clean(first_existing(r, ["portal_password"], ""))
            card_image = clean(first_existing(r, ["card_image"], ""))
            cur.execute("""
                INSERT INTO poolops2_clients
                (name, contact_name, phone, mobile, email, billing_address, shipping_address, city, state, zip_code, company, notes, portal_username, portal_password, card_image)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (name, contact, phone, "", email, "", "", "", "", "", "", notes, username, password, card_image))

    if table_exists(cur, "properties"):
        for r in cur.execute("SELECT * FROM properties").fetchall():
            client = clean(first_existing(r, ["client_name", "client"], "Unknown Client"))
            pname = clean(first_existing(r, ["property_name", "name"], ""))
            address = clean(first_existing(r, ["full_address", "address", "street"], ""))
            city = clean(first_existing(r, ["city"], ""))
            state = clean(first_existing(r, ["state"], ""))
            zip_code = clean(first_existing(r, ["zip_code", "zip"], ""))
            notes = clean(first_existing(r, ["notes"], ""))
            card_image = clean(first_existing(r, ["card_image"], ""))
            client_id = first_existing(r, ["client_id"], None)
            cur.execute("""
                INSERT INTO poolops2_properties
                (client_id, client, property_name, address, city, state, zip_code, notes, card_image)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (client_id, client, pname, address, city, state, zip_code, notes, card_image))

    if table_exists(cur, "jobs"):
        for r in cur.execute("SELECT * FROM jobs").fetchall():
            client = clean(first_existing(r, ["client_name", "client"], "Unknown Client"))
            prop = clean(first_existing(r, ["property_name", "property"], ""))
            address = clean(first_existing(r, ["address", "full_address"], ""))
            job_type = clean(first_existing(r, ["job_type", "type"], ""))
            status = clean(first_existing(r, ["status"], "Pending")) or "Pending"
            crew = clean(first_existing(r, ["crew"], "Unassigned")) or "Unassigned"
            date = clean(first_existing(r, ["scheduled_date", "date", "raw_date"], ""))
            priority = clean(first_existing(r, ["priority"], "Normal")) or "Normal"
            notes = clean(first_existing(r, ["notes"], ""))
            cur.execute("""
                INSERT INTO poolops2_jobs
                (client, property, address, job_type, status, crew, date, priority, notes)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (client, prop, address, job_type, status, crew, date, priority, notes))

    conn.commit()

    counts = {
        "poolops2_clients": cur.execute("SELECT COUNT(*) FROM poolops2_clients").fetchone()[0],
        "poolops2_properties": cur.execute("SELECT COUNT(*) FROM poolops2_properties").fetchone()[0],
        "poolops2_jobs": cur.execute("SELECT COUNT(*) FROM poolops2_jobs").fetchone()[0],
    }
    conn.close()

    print("UI tables synced")
    for k, v in counts.items():
        print(f"{k}: {v}")

if __name__ == "__main__":
    main()
