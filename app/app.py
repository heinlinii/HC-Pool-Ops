from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
from datetime import datetime, date, timedelta
from app.routes import pool_monitoring
import calendar
import json
import os
import shutil
import sqlite3
import uuid
import boto3
import csv
import io
try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "poolops2_local.db"
LEGACY_DB_PATH = ROOT / "poolops_local.db"
UPLOAD_DIR = ROOT / "app" / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
R2_ENABLED = os.environ.get("R2_ENABLED", "").lower() == "true"
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")

def r2_client():
    if not (R2_ENABLED and R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME):
        return None
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
THEME_FILE = ROOT / "app" / "dashboard_theme.json"
DESIGN_FILE = ROOT / "app" / "design_studio.json"
app = FastAPI(title="Heinlin Field Ops")
app.add_middleware(SessionMiddleware, secret_key="heinlin-field-ops-local-secret")
app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
app.include_router(pool_monitoring.router)

DEFAULT_THEME = {
    "title": "HEINLIN FIELD OPS",
    "subtitle": "Got pool related troubles? Ready to enter your work performed, materials used, problems found, reminders, and operational memory? Click on the fountain and tell Jarvis! He'll take care of the rest!",
    "hero_title": "Command Center",
    "hero_subtitle": "Jobs, clients, properties, schedule, maps, photos, billing, QuickBooks, weather, and invisible office.",
    "background_image": "",
    "calendar_background": "",
    "clients_image": "/static/uploads/fountain.jpg",
    "properties_image": "/static/uploads/maria.jpg",
    "jobs_image": "/static/uploads/McCord.jpg",
    "schedule_image": "/static/uploads/pate.jpg",
    "photos_image": "/static/uploads/boger.jpg",
    "crew_image": "/static/uploads/fountain.jpg",
    "estimates_image": "/static/uploads/maria.jpg",
    "job_costing_image": "/static/uploads/McCord.jpg",
    "quickbooks_image": "/static/uploads/pate.jpg",
    "weather_image": "/static/uploads/boger.jpg",
    "field_log_image": "/static/uploads/fountain.jpg",
    "map_image": "/static/uploads/maria.jpg",
}



DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))


def db():
    """Return a SQLite connection locally, or Postgres on Render when DATABASE_URL is set."""
    if USE_POSTGRES:
        if psycopg is None:
            raise RuntimeError("psycopg is required for Postgres DATABASE_URL")
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    if not DB_PATH.exists() and LEGACY_DB_PATH.exists():
        shutil.copy2(LEGACY_DB_PATH, DB_PATH)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _convert_placeholders(sql: str) -> str:
    # The app was originally written with SQLite '?' placeholders.
    # psycopg uses '%s'. This simple conversion is safe for our parameterized app queries.
    return sql.replace("?", "%s")


def rows(sql, params=()):
    con = db()
    try:
        if USE_POSTGRES:
            s = sql.strip()
            low = s.lower()
            if "sqlite_master" in low:
                with con.cursor() as cur:
                    cur.execute("SELECT tablename AS name FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
                    return [dict(r) for r in cur.fetchall()]
            if low.startswith("pragma table_info"):
                table = s[s.find("(")+1:s.rfind(")")].strip().strip('"')
                with con.cursor() as cur:
                    cur.execute("SELECT column_name AS name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))
                    return [dict(r) for r in cur.fetchall()]
            with con.cursor() as cur:
                cur.execute(_convert_placeholders(sql), params)
                return [dict(r) for r in cur.fetchall()]
        else:
            return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def one(sql, params=()):
    data = rows(sql, params)
    return data[0] if data else None


def exec_sql(sql, params=()):
    con = db()
    try:
        if USE_POSTGRES:
            with con.cursor() as cur:
                cur.execute(_convert_placeholders(sql), params)
                new_id = None
                try:
                    if cur.description:
                        row = cur.fetchone()
                        if row:
                            new_id = list(dict(row).values())[0]
                except Exception:
                    pass
                con.commit()
                return new_id
        else:
            cur = con.execute(sql, params)
            con.commit()
            return cur.lastrowid
    finally:
        con.close()


def table_columns(table):
    if USE_POSTGRES:
        return [r["name"] for r in rows("SELECT column_name AS name FROM information_schema.columns WHERE table_schema='public' AND table_name=? ORDER BY ordinal_position", (table,))]
    con = db()
    try:
        return [r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    finally:
        con.close()


def add_col(table, col, spec):
    if col not in table_columns(table):
        try:
            exec_sql(f"ALTER TABLE {table} ADD COLUMN {col} {spec}")
        except Exception:
            pass


def ensure_schema():
    con = db()
    try:
        c = con.cursor()
        if USE_POSTGRES:
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'admin',
                name TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_clients (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                contact_name TEXT DEFAULT '', phone TEXT DEFAULT '', mobile TEXT DEFAULT '', email TEXT DEFAULT '',
                billing_address TEXT DEFAULT '', shipping_address TEXT DEFAULT '', city TEXT DEFAULT '', state TEXT DEFAULT '', zip_code TEXT DEFAULT '',
                company TEXT DEFAULT '', notes TEXT DEFAULT '', portal_username TEXT DEFAULT '', portal_password TEXT DEFAULT '', card_image TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_properties (
                id SERIAL PRIMARY KEY,
                client_id INTEGER, client TEXT DEFAULT '', property_name TEXT DEFAULT '', address TEXT DEFAULT '', city TEXT DEFAULT '', state TEXT DEFAULT '', zip_code TEXT DEFAULT '',
                pool_type TEXT DEFAULT '', pool_size TEXT DEFAULT '', pool_depth TEXT DEFAULT '', cover_type TEXT DEFAULT '', finish_type TEXT DEFAULT '',
                pump_model TEXT DEFAULT '', filter_model TEXT DEFAULT '', heater_model TEXT DEFAULT '', sanitizer TEXT DEFAULT '', automation_system TEXT DEFAULT '',
                gate_code TEXT DEFAULT '', service_plan TEXT DEFAULT '', notes TEXT DEFAULT '', card_image TEXT DEFAULT '', latitude REAL, longitude REAL,
                pool_notes TEXT DEFAULT '', equipment_notes TEXT DEFAULT ''
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS pool_monitoring (
                id SERIAL PRIMARY KEY,
                client_id INTEGER REFERENCES poolops2_clients(id),
                property_id INTEGER REFERENCES poolops2_properties(id),
                system_brand TEXT DEFAULT 'Pentair',
                system_type TEXT DEFAULT '',
                pentair_account_email TEXT DEFAULT '',
                monitoring_status TEXT DEFAULT 'Not Started',
                last_checked DATE,
                current_alert TEXT DEFAULT '',
                equipment_notes TEXT DEFAULT '',
                service_notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_jobs (
                id SERIAL PRIMARY KEY,
                client TEXT DEFAULT '', property TEXT DEFAULT '', address TEXT DEFAULT '', job_type TEXT DEFAULT '', status TEXT DEFAULT 'Pending', crew TEXT DEFAULT 'Unassigned',
                date TEXT DEFAULT '', priority TEXT DEFAULT 'Normal', notes TEXT DEFAULT '', scheduled_start TEXT, scheduled_end TEXT, card_image TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_employees (
                id SERIAL PRIMARY KEY,
                name TEXT DEFAULT '', role TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '', active BOOLEAN DEFAULT true, card_image TEXT DEFAULT '', username TEXT DEFAULT '', password TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS employee_location_points (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER,
                employee_name TEXT DEFAULT '',
                latitude REAL,
                longitude REAL,
                accuracy REAL,
                speed REAL,
                heading REAL,
                source TEXT DEFAULT 'employee_portal',
                note TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_photo_logs (
                id SERIAL PRIMARY KEY,
                job_id INTEGER, property_id INTEGER, client TEXT DEFAULT '', photo_type TEXT DEFAULT 'Progress', title TEXT DEFAULT '',
                photo_url TEXT DEFAULT '', date TEXT DEFAULT '', notes TEXT DEFAULT '', latitude REAL, longitude REAL
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_calendar_day_images (
                id SERIAL PRIMARY KEY,
                day_date TEXT UNIQUE NOT NULL,
                image_url TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_equipment (
                id SERIAL PRIMARY KEY,
                property_id INTEGER,
                equipment_type TEXT DEFAULT '', brand TEXT DEFAULT '', model TEXT DEFAULT '', serial TEXT DEFAULT '', installed_date TEXT DEFAULT '', notes TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_estimates (
                id SERIAL PRIMARY KEY,
                client TEXT DEFAULT '', property TEXT DEFAULT '', title TEXT DEFAULT '', status TEXT DEFAULT 'Draft', amount REAL DEFAULT 0, notes TEXT DEFAULT '', created_at TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS field_logs (
                id SERIAL PRIMARY KEY,
                employee_name TEXT DEFAULT '', crew TEXT DEFAULT '', client TEXT DEFAULT '', property TEXT DEFAULT '', address TEXT DEFAULT '', date TEXT DEFAULT '',
                arrival_time TEXT DEFAULT '', departure_time TEXT DEFAULT '', total_hours REAL DEFAULT 0, tools_used TEXT DEFAULT '', materials_used TEXT DEFAULT '',
                equipment_used TEXT DEFAULT '', work_completed TEXT DEFAULT '', issues TEXT DEFAULT '', next_steps TEXT DEFAULT '', weather TEXT DEFAULT '', photo_count INTEGER DEFAULT 0, created_at TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_job_costs (
                id SERIAL PRIMARY KEY,
                job_id INTEGER, client TEXT DEFAULT '', labor REAL DEFAULT 0, materials REAL DEFAULT 0, subs REAL DEFAULT 0, equipment REAL DEFAULT 0, fuel REAL DEFAULT 0, other REAL DEFAULT 0, invoice_amount REAL DEFAULT 0, notes TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_office_notes (
                id SERIAL PRIMARY KEY,
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )""")
          
            c.execute("""CREATE TABLE IF NOT EXISTS invisible_office_items (
                id SERIAL PRIMARY KEY,
                source TEXT DEFAULT 'manual',
                category TEXT DEFAULT 'General Note',
                title TEXT DEFAULT '',
                body TEXT DEFAULT '',
                client TEXT DEFAULT '',
                property TEXT DEFAULT '',
                job_id INTEGER,
                assigned_to TEXT DEFAULT '',
                due_date TEXT DEFAULT '',
                priority TEXT DEFAULT 'Normal',
                status TEXT DEFAULT 'Open',
                created_by TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                completed_at TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_invoices (
                id SERIAL PRIMARY KEY,
                job_id INTEGER, client TEXT DEFAULT '', description TEXT DEFAULT '', amount REAL DEFAULT 0, status TEXT DEFAULT 'Draft', date TEXT DEFAULT '', notes TEXT DEFAULT '',
                qb_invoice_number TEXT DEFAULT '', due_date TEXT DEFAULT '', open_balance REAL DEFAULT 0, source TEXT DEFAULT ''
            )""")
        else:
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'admin',
                name TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                contact_name TEXT DEFAULT '', phone TEXT DEFAULT '', mobile TEXT DEFAULT '', email TEXT DEFAULT '',
                billing_address TEXT DEFAULT '', shipping_address TEXT DEFAULT '', city TEXT DEFAULT '', state TEXT DEFAULT '', zip_code TEXT DEFAULT '',
                company TEXT DEFAULT '', notes TEXT DEFAULT '', portal_username TEXT DEFAULT '', portal_password TEXT DEFAULT '', card_image TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER, client TEXT DEFAULT '', property_name TEXT DEFAULT '', address TEXT DEFAULT '', city TEXT DEFAULT '', state TEXT DEFAULT '', zip_code TEXT DEFAULT '',
                pool_type TEXT DEFAULT '', pool_size TEXT DEFAULT '', pool_depth TEXT DEFAULT '', cover_type TEXT DEFAULT '', finish_type TEXT DEFAULT '',
                pump_model TEXT DEFAULT '', filter_model TEXT DEFAULT '', heater_model TEXT DEFAULT '', sanitizer TEXT DEFAULT '', automation_system TEXT DEFAULT '',
                gate_code TEXT DEFAULT '', service_plan TEXT DEFAULT '', notes TEXT DEFAULT '', card_image TEXT DEFAULT '', latitude REAL, longitude REAL,
                pool_notes TEXT DEFAULT '', equipment_notes TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS pool_monitoring (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                property_id INTEGER,
                system_brand TEXT DEFAULT 'Pentair',
                system_type TEXT DEFAULT '',
                pentair_account_email TEXT DEFAULT '',
                monitoring_status TEXT DEFAULT 'Not Started',
                last_checked DATE,
                current_alert TEXT DEFAULT '',
                equipment_notes TEXT DEFAULT '',
                service_notes TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client TEXT DEFAULT '', property TEXT DEFAULT '', address TEXT DEFAULT '', job_type TEXT DEFAULT '', status TEXT DEFAULT 'Pending', crew TEXT DEFAULT 'Unassigned',
                date TEXT DEFAULT '', priority TEXT DEFAULT 'Normal', notes TEXT DEFAULT '', scheduled_start TEXT, scheduled_end TEXT, card_image TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT DEFAULT '', role TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '', active BOOLEAN DEFAULT true, card_image TEXT DEFAULT '', username TEXT DEFAULT '', password TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS employee_location_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                employee_name TEXT DEFAULT '',
                latitude REAL,
                longitude REAL,
                accuracy REAL,
                speed REAL,
                heading REAL,
                source TEXT DEFAULT 'employee_portal',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_photo_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER, property_id INTEGER, client TEXT DEFAULT '', photo_type TEXT DEFAULT 'Progress', title TEXT DEFAULT '',
                photo_url TEXT DEFAULT '', date TEXT DEFAULT '', notes TEXT DEFAULT '', latitude REAL, longitude REAL
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_calendar_day_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_date TEXT UNIQUE NOT NULL,
                image_url TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                property_id INTEGER,
                equipment_type TEXT DEFAULT '', brand TEXT DEFAULT '', model TEXT DEFAULT '', serial TEXT DEFAULT '', installed_date TEXT DEFAULT '', notes TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_estimates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client TEXT DEFAULT '', property TEXT DEFAULT '', title TEXT DEFAULT '', status TEXT DEFAULT 'Draft', amount REAL DEFAULT 0, notes TEXT DEFAULT '', created_at TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS field_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_name TEXT DEFAULT '', crew TEXT DEFAULT '', client TEXT DEFAULT '', property TEXT DEFAULT '', address TEXT DEFAULT '', date TEXT DEFAULT '',
                arrival_time TEXT DEFAULT '', departure_time TEXT DEFAULT '', total_hours REAL DEFAULT 0, tools_used TEXT DEFAULT '', materials_used TEXT DEFAULT '',
                equipment_used TEXT DEFAULT '', work_completed TEXT DEFAULT '', issues TEXT DEFAULT '', next_steps TEXT DEFAULT '', weather TEXT DEFAULT '', photo_count INTEGER DEFAULT 0, created_at TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_job_costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER, client TEXT DEFAULT '', labor REAL DEFAULT 0, materials REAL DEFAULT 0, subs REAL DEFAULT 0, equipment REAL DEFAULT 0, fuel REAL DEFAULT 0, other REAL DEFAULT 0, invoice_amount REAL DEFAULT 0, notes TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_office_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS invisible_office_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT DEFAULT 'manual',
                category TEXT DEFAULT 'General Note',
                title TEXT DEFAULT '',
                body TEXT DEFAULT '',
                client TEXT DEFAULT '',
                property TEXT DEFAULT '',
                job_id INTEGER,
                assigned_to TEXT DEFAULT '',
                due_date TEXT DEFAULT '',
                priority TEXT DEFAULT 'Normal',
                status TEXT DEFAULT 'Open',
                created_by TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                completed_at TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS poolops2_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER, client TEXT DEFAULT '', description TEXT DEFAULT '', amount REAL DEFAULT 0, status TEXT DEFAULT 'Draft', date TEXT DEFAULT '', notes TEXT DEFAULT '',
                qb_invoice_number TEXT DEFAULT '', due_date TEXT DEFAULT '', open_balance REAL DEFAULT 0, source TEXT DEFAULT ''
            )""")
        con.commit()
    finally:
        con.close()

    for table, cols in {
        "poolops2_clients": [("portal_username", "TEXT DEFAULT ''"), ("portal_password", "TEXT DEFAULT ''"), ("card_image", "TEXT DEFAULT ''")],
        "poolops2_properties": [("card_image", "TEXT DEFAULT ''"), ("pool_notes", "TEXT DEFAULT ''"), ("equipment_notes", "TEXT DEFAULT ''"), ("latitude", "REAL"), ("longitude", "REAL")],
        "poolops2_jobs": [("scheduled_start", "TEXT"), ("scheduled_end", "TEXT"), ("card_image", "TEXT DEFAULT ''")],
        "poolops2_employees": [("username", "TEXT DEFAULT ''"), ("password", "TEXT DEFAULT ''"), ("card_image", "TEXT DEFAULT ''"), ("clocked_in", "BOOLEAN DEFAULT false" if USE_POSTGRES else "INTEGER DEFAULT 0"), ("clock_lat", "REAL"), ("clock_lng", "REAL"), ("clocked_in_at", "TEXT DEFAULT ''"), ("last_seen_at", "TEXT DEFAULT ''")],
        "poolops2_photo_logs": [("property_id", "INTEGER"), ("latitude", "REAL"), ("longitude", "REAL")],
        "field_logs": [("latitude", "REAL"), ("longitude", "REAL")],
        "poolops2_invoices": [("qb_invoice_number", "TEXT DEFAULT ''"), ("due_date", "TEXT DEFAULT ''"), ("open_balance", "REAL DEFAULT 0"), ("source", "TEXT DEFAULT ''")],
    }.items():
        for col, spec in cols:
            add_col(table, col, spec)

    if not one("SELECT id FROM poolops2_users WHERE username=?", ("mike",)):
        exec_sql("INSERT INTO poolops2_users (username,password,role,name) VALUES (?,?,?,?)", ("mike", "mike", "admin", "Mike"))

@app.on_event("startup")
def startup():
    ensure_schema()
    print("HEINLIN FIELD OPS READY")


def theme():
    data = DEFAULT_THEME.copy()
    if THEME_FILE.exists():
        try:
            data.update(json.loads(THEME_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return data


def save_theme(data):
    THEME_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

DEFAULT_DESIGN = {
    "global": {
        "brass_color": "#d6b36a",
        "dark_bg": "#071017",
        "card_bg": "rgba(7, 14, 20, .94)",
        "card_radius": "24px",
        "page_padding": "80px 18px 40px",
        "button_height": "104px",
        "button_radius": "22px",
        "mobile_page_padding": "56px 12px 28px",
    },
    "dashboard": {
        "legacy_line": "Heinlin Field Ops • Founded 1907 • 5 Generations Strong",
        "crest_image": "/static/heinlin-wide-crest.png",
        "motto_first": "Work Hard.",
        "motto_second": "Play Harder.",
        "hero_subline": "Built by hand. Run like a machine. No lost notes. No mystery jobs.",
        "search_title": "What needs handled?",
        "search_subtitle": "Search it, say it, or hit the button.",
        "search_placeholder": "Find a client, job, property, photo, log, map, weather...",
        "handle_button": "Handle It",
        "page_top_space": "54px",
        "crest_width": "920px",
        "crest_height": "420px",
        "motto_size": "clamp(3rem, 7vw, 7.8rem)",
        "motto_top_space": "22px",
        "section_gap": "22px",
        "button_height": "104px",
    },
    "login": {
        "title": "Heinlin Field Ops",
        "legacy_line": "Founded 1907 • 5 Generations Strong",
        "subtitle": "Built by the hands that perfected the term work hard play harder.",
        "button_text": "Enter Operations Center",
        "crest_image": "/static/heinlin-wide-crest.png",
        "background_image": "/static/heinlin-wide-crest.png",
        "crest_width": "760px",
        "card_width": "460px",
    },
    "schedule": {
        "title": "Schedule",
        "day_title": "Daily Schedule",
        "week_title": "Weekly Schedule",
        "subtitle": "Jobs, field work, service calls, and crew movement.",
        "empty_text": "No jobs are scheduled for this view yet.",
        "button_daily": "Daily",
        "button_weekly": "Weekly",
        "button_yearly": "Yearly",
        "button_jobs": "Jobs",
        "button_dashboard": "Dashboard",
        "button_text": "Add Schedule Item",
    },
    "map": {
        "title": "Field Map",
        "subtitle": "Property pins, clocked-in employees, and jobsite locations.",
        "map_height": "560px",
        "mobile_map_height": "480px",
        "top_padding": "115px",
        "mobile_top_padding": "95px",
    },
    "clients": {
        "title": "Clients",
        "subtitle": "The people, properties, pools, and promises we are responsible for.",
        "button_text": "Add Client",
    },
    "properties": {
        "title": "Properties",
        "subtitle": "Every pool, address, gate code, equipment pad, and detail in one place.",
        "button_text": "Add Property",
    },
    "jobs": {
        "title": "Jobs",
        "subtitle": "Scheduled work, service calls, repairs, and field notes.",
        "button_text": "Add Job",
    },
    "crew": {
        "title": "Employees",
        "subtitle": "Crew access, login credentials, roles, and field visibility.",
        "button_text": "Add Employee",
    },
    "employee": {
        "title": "Crew Portal",
        "subtitle": "My jobs, clock in/out, photos, field notes, weather, and map.",
        "button_text": "Clock / Field Work",
    },
    "crew_dashboard": {
        "greeting_prefix": "Good morning",
        "title": "Crew Portal",
        "subtitle": "My jobs, clock in/out, photos, field notes, weather, and map.",
        "section_title": "Crew Tools",
        "crest_image": "/static/heinlin-wide-crest.png",
        "crest_width": "340px",
        "crest_top": "210px",
        "crest_right": "70px",
        "crest_opacity": "0.92",
        "hero_padding_top": "150px",
        "dashboard_padding_top": "120px",
        "tools": [
            {"label": "My Day", "description": "Today's work", "href": "/crew/my-day", "enabled": True},
            {"label": "Crew Portal", "description": "Clock and GPS", "href": "/employee", "enabled": True},
            {"label": "My Jobs", "description": "Assigned work", "href": "/jobs", "enabled": True},
            {"label": "Photos", "description": "Field proof", "href": "/photos", "enabled": True},
            {"label": "Schedule", "description": "Today", "href": "/schedule/day", "enabled": True},
            {"label": "Map", "description": "Locations", "href": "/map", "enabled": True},
            {"label": "Weather", "description": "Conditions", "href": "/weather", "enabled": True},
            {"label": "GPS Day Log", "description": "Raw GPS points", "href": "/gps/day", "enabled": True},
            {"label": "GPS Stops", "description": "Stops and time on site", "href": "/gps/stops", "enabled": True},
            {"label": "AI Systems", "description": "Jarvis tools and office memory", "href": "/ai-systems", "enabled": True},
            {"label": "Talk to Jarvis", "description": "Tell Jarvis what needs handled, filed, remembered, or followed up.", "href": "/assistant-interview-live", "enabled": True},
            {"label": "Invisible Office", "description": "Saved notes, follow-ups, reminders, materials, problems, billing notes, and Jarvis-filed work.", "href": "/invisible-office", "enabled": True},
        ],
    },
    "ai_systems": {
        "title": "AI Systems",
        "subtitle": "All Jarvis tools, office memory, and AI workflows in one place.",
        "cards": [
            {"label": "Talk to Jarvis", "description": "Tell Jarvis what needs handled, filed, remembered, or followed up.", "href": "/assistant-interview-live", "image": "", "enabled": True},
            {"label": "Invisible Office", "description": "Saved notes, follow-ups, reminders, materials, problems, billing notes, and Jarvis-filed work.", "href": "/invisible-office", "image": "", "enabled": True},
            {"label": "Organize My Day", "description": "Turn work, notes, and priorities into a useful day plan.", "href": "/organize-my-day", "image": "", "enabled": True},
            {"label": "Design Studio", "description": "Edit dashboard wording, buttons, and visual settings.", "href": "/design-studio", "image": "", "enabled": True, "roles": ["admin"]},
            {"label": "Link Check", "description": "Check app navigation and find broken internal links.", "href": "/admin/link-check", "image": "", "enabled": True, "roles": ["admin"]},
            {"label": "Crew Portal", "description": "Clock, GPS, jobs, photos, and field tools.", "href": "/employee", "image": "", "enabled": True, "roles": ["employee"]},
        ],
    },
    "photos": {
        "title": "Photos",
        "subtitle": "Job photos, property photos, progress shots, and field proof.",
        "button_text": "Upload Photos",
    },
    "pool_monitoring": {
        "title": "Pool Monitoring",
        "subtitle": "Pentair access, pool alerts, service notes, and monitored systems.",
        "button_text": "Add Pool Monitor",
    },
}

def deep_update(base, updates):
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def design_settings():
    data = json.loads(json.dumps(DEFAULT_DESIGN))

    if DESIGN_FILE.exists():
        try:
            saved = json.loads(DESIGN_FILE.read_text(encoding="utf-8"))
            deep_update(data, saved)
        except Exception:
            pass

    return data


def save_design_settings(data):
    DESIGN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def current_user(request: Request):
    return request.session.get("user")


def require_login(request: Request):
    u = current_user(request)
    if not u:
        return None
    return u


def is_admin(user):
    return user and user.get("role") == "admin"


def is_client(user):
    return user and user.get("role") == "client"


def is_employee(user):
    return user and str(user.get("role", "")).lower() in ("employee", "crew")


def admin_redirect(user):
    if is_client(user):
        return RedirectResponse("/jarvis", status_code=303)
    if is_employee(user):
        return RedirectResponse("/employee", status_code=303)
    return login_redirect()


def client_name_for_user(user):
    if not user:
        return ""
    if is_client(user):
        c = one("SELECT * FROM poolops2_clients WHERE id=?", (user.get("id"),))
        return (c or {}).get("name", "")
    return ""


def client_can_access(user, client_id=None, client_name=""):
    if is_admin(user):
        return True
    if not is_client(user):
        return False
    if client_id is not None and str(user.get("id")) == str(client_id):
        return True
    own = client_name_for_user(user).strip().lower()
    return bool(own and client_name and own == str(client_name).strip().lower())


def property_can_access(user, prop):
    if is_admin(user):
        return True
    if not prop:
        return False
    if is_client(user):
        return client_can_access(user, prop.get("client_id"), prop.get("client"))
    if is_employee(user):
        return True
    return False


def employee_can_access_job(user, job):
    if is_admin(user):
        return True
    if not job:
        return False
    if is_employee(user):
        crew = str(job.get("crew") or "").lower()
        name = str(user.get("name") or "").lower()
        return crew in ("", "unassigned") or (name and name in crew)
    return False


def jobs_for_user(user):
    if is_admin(user):
        return rows("SELECT * FROM poolops2_jobs ORDER BY id DESC")

    if is_employee(user):
        name = str(user.get("name") or "").strip()
        username = str(user.get("username") or "").strip()

        return rows(
            """
            SELECT * FROM poolops2_jobs
            WHERE crew LIKE ?
               OR crew LIKE ?
               OR crew=''
               OR crew='Unassigned'
               OR crew IS NULL
            ORDER BY id DESC
            """,
            (f"%{name}%", f"%{username}%")
        )

    if is_client(user):
        cname = client_name_for_user(user)
        return rows("SELECT * FROM poolops2_jobs WHERE client=? ORDER BY id DESC", (cname,))

    return []


def properties_for_user(user):
    if is_admin(user) or is_employee(user):
        return rows("SELECT * FROM poolops2_properties ORDER BY client,address")
    if is_client(user):
        cname = client_name_for_user(user)
        return rows("SELECT * FROM poolops2_properties WHERE client_id=? OR client=? ORDER BY address", (user.get("id"), cname))
    return []


def photos_for_user(user):
    if is_admin(user) or is_employee(user):
        return rows("SELECT * FROM poolops2_photo_logs ORDER BY id DESC")
    if is_client(user):
        cname = client_name_for_user(user)
        return rows("SELECT * FROM poolops2_photo_logs WHERE client=? ORDER BY id DESC", (cname,))
    return []


def login_redirect():
    return RedirectResponse("/login", status_code=303)


def safe_filename(filename):
    ext = Path(filename or "photo.jpg").suffix.lower() or ".jpg"
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"


async def save_upload(file: UploadFile | None):
    if not file or not file.filename:
        return ""

    name = safe_filename(file.filename)
    content = await file.read()

    client = r2_client()

    if client:
        try:
            key = f"uploads/{name}"

            client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=key,
                Body=content,
                ContentType=file.content_type or "application/octet-stream",
            )

            if R2_PUBLIC_URL:
                return f"{R2_PUBLIC_URL}/{key}"

            return f"https://pub-{R2_ACCOUNT_ID}.r2.dev/{key}"

        except Exception as e:
            print(f"R2 upload failed, falling back to local storage: {e}")

    path = UPLOAD_DIR / name

    with path.open("wb") as f:
        f.write(content)

    return f"/static/uploads/{name}"


def schedule_date(job):
    val = job.get("scheduled_start") or job.get("date") or ""

    if not val:
        return ""

    # Render/Postgres may return real date/datetime objects.
    if isinstance(val, datetime):
        return val.date().isoformat()

    if isinstance(val, date):
        return val.isoformat()

    # SQLite/local usually returns text.
    val = str(val).strip()

    if not val:
        return ""

    return val[:10]

def month_grid(year=None, month=None, job_rows=None):
    today = date.today()
    year = year or today.year
    month = month or today.month
    cal = calendar.Calendar(firstweekday=6)
    day_rows = []
    jobs = job_rows if job_rows is not None else rows("SELECT * FROM poolops2_jobs ORDER BY id DESC")
    images = {r["day_date"]: r for r in rows("SELECT * FROM poolops2_calendar_day_images")}
    for d in cal.itermonthdates(year, month):
        ds = d.isoformat()
        day_rows.append({
            "date": ds,
            "day": d.day,
            "in_month": d.month == month,
            "is_today": d == today,
            "jobs": [j for j in jobs if schedule_date(j) == ds],
            "image": images.get(ds, {}).get("image_url", ""),
            "notes": images.get(ds, {}).get("notes", ""),
        })
    return day_rows


def ctx(request, **kw):
    u = current_user(request)
    return {
        "request": request,
        "user": u,
        "theme": theme(),
        "design": design_settings(),
        "is_admin": is_admin(u),
        "is_client": is_client(u),
        "is_employee": is_employee(u),
        **kw,
    }

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if current_user(request):
        return RedirectResponse("/jarvis", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", ctx(request, error=""))


@app.post("/login")
def login_post(request: Request, username: str = Form(""), password: str = Form("")):
    ensure_schema()

    username = username.strip()
    password = password.strip()

    if not username or not password:
        return templates.TemplateResponse(
            "login.html",
            ctx(request, error="Enter a username and password.")
        )

    username_l = username.lower()

    # 1. Admin login from users table
    u = one(
        """
        SELECT * FROM poolops2_users
        WHERE lower(username)=lower(?)
          AND password=?
          AND lower(coalesce(role,''))='admin'
        """,
        (username, password)
    )

    if u:
        request.session["user"] = {
            "id": u["id"],
            "username": u.get("username") or u.get("name") or username,
            "role": "admin",
            "name": u.get("name") or u.get("username") or username
        }
        return RedirectResponse("/jarvis", status_code=303)

    # 2. Crew / employee login
    if USE_POSTGRES:
        employee_sql = """
            SELECT * FROM poolops2_employees
            WHERE coalesce(password,'')=?
              AND coalesce(active::text, 'true') IN ('true', '1', 't')
        """
    else:
        employee_sql = """
            SELECT * FROM poolops2_employees
            WHERE coalesce(password,'')=?
              AND coalesce(active, 1)=1
        """

    employees = rows(employee_sql, (password,))

    for e in employees:
        emp_username = str(e.get("username") or "").strip().lower()
        emp_name = str(e.get("name") or "").strip().lower()
        emp_first = emp_name.split(" ")[0] if emp_name else ""
        emp_dot_name = emp_name.replace(" ", ".")
        emp_nospace_name = emp_name.replace(" ", "")

        accepted_names = {
            emp_username,
            emp_name,
            emp_first,
            emp_dot_name,
            emp_nospace_name,
        }

        if username_l in accepted_names:
            request.session["user"] = {
                "id": e["id"],
                "username": e.get("username") or e.get("name") or username,
                "role": "employee",
                "name": e.get("name") or e.get("username") or username
            }
            return RedirectResponse("/jarvis", status_code=303)

    # 3. Crew/employee fallback from users table
    crew_user = one(
        """
        SELECT * FROM poolops2_users
        WHERE lower(username)=lower(?)
          AND password=?
          AND lower(coalesce(role,'')) IN ('employee', 'crew')
        """,
        (username, password)
    )

    if crew_user:
        request.session["user"] = {
            "id": crew_user["id"],
            "username": crew_user.get("username") or username,
            "role": "employee",
            "name": crew_user.get("name") or crew_user.get("username") or username
        }
        return RedirectResponse("/jarvis", status_code=303)

    # 4. Client portal login
    c = one(
        """
        SELECT * FROM poolops2_clients
        WHERE lower(portal_username)=lower(?)
          AND portal_password=?
        """,
        (username, password)
    )

    if c:
        request.session["user"] = {
            "id": c["id"],
            "username": c["portal_username"],
            "role": "client",
            "name": c["name"]
        }
        return RedirectResponse("/jarvis", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        ctx(request, error="Login not found. Check the username and password.")
    )

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/jarvis/search")
def jarvis_search(request: Request, q: str = ""):
    u = require_login(request)
    if not u:
        return login_redirect()

    text = (q or "").strip().lower()

    if not text:
        return RedirectResponse("/organize-my-day", status_code=303)

    if "today" in text or "day" in text or "work" in text or "handle" in text:
        return RedirectResponse("/organize-my-day", status_code=303)

    if "my day" in text or "clock" in text or "clock in" in text or "employee" in text:
        return RedirectResponse("/employee", status_code=303)

    if "talk" in text or "jarvis" in text or "assistant" in text:
        return RedirectResponse("/assistant-interview-live", status_code=303)

    if "job" in text:
        return RedirectResponse("/jobs", status_code=303)

    if "client" in text:
        return RedirectResponse("/clients", status_code=303)

    if "property" in text or "pool" in text:
        return RedirectResponse("/properties", status_code=303)

    if "photo" in text or "picture" in text:
        return RedirectResponse("/photos", status_code=303)

    if "field log" in text or "log" in text:
        return RedirectResponse("/field-logs", status_code=303)

    if "map" in text or "crew" in text:
        return RedirectResponse("/map", status_code=303)

    if "weather" in text:
        return RedirectResponse("/weather", status_code=303)

    return RedirectResponse("/organize-my-day", status_code=303)

@app.get("/jarvis", response_class=HTMLResponse)
def jarvis_landing(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    hour = datetime.now().hour

    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    today = date.today().isoformat()

    return templates.TemplateResponse(
        "jarvis.html",
        ctx(
            request,
            today=today,
            greeting=greeting,
        )
    )

# ============================================================
# HEINLIN FIELD OPS - ORGANIZED DASHBOARD SECTIONS
# ============================================================

DASHBOARD_SECTIONS = {
    "accounts": {
        "title": "Accounts",
        "subtitle": "Clients, properties, jobs, billing, photos, estimates, and invoices.",
        "description": "Everything tied to a customer account, property, job, invoice, estimate, or photo record.",
        "items": [
            {
                "title": "Clients",
                "subtitle": "Customer list, contact info, notes, and account history.",
                "url": "/clients",
                "button": "Open Clients",
            },
            {
                "title": "Properties",
                "subtitle": "Addresses, pool details, equipment, photos, and property notes.",
                "url": "/properties",
                "button": "Open Properties",
            },
            {
                "title": "Jobs",
                "subtitle": "Active jobs, service work, repairs, installs, and project records.",
                "url": "/jobs",
                "button": "Open Jobs",
            },
            {
                "title": "Billing",
                "subtitle": "Invoices, QuickBooks imports, balances, and money tracking.",
                "url": "/billing",
                "button": "Open Billing",
            },
            {
                "title": "Photos",
                "subtitle": "Job photos, property photos, equipment photos, and uploads.",
                "url": "/photos",
                "button": "Open Photos",
            },
            {
                "title": "Estimates",
                "subtitle": "Estimate work, pricing, proposals, and customer quote records.",
                "url": "/estimates",
                "button": "Open Estimates",
            },
        ],
    },

    "today": {
        "title": "Today",
        "subtitle": "Daily work, schedule, weather, map, and crew planning.",
        "description": "The first place to go every morning before the day starts.",
        "items": [
            {
                "title": "My Day",
                "subtitle": "Daily work view, today's work, notes, and field workflow.",
                "url": "/my-day",
                "button": "Open My Day",
            },
            {
                "title": "Schedule",
                "subtitle": "Schedule and calendar views for jobs, crew, and planning.",
                "url": "/schedule",
                "button": "Open Schedule",
            },
            {
                "title": "Weather",
                "subtitle": "Weather, freeze watch, weather watch, alerts, forecast, and radar.",
                "url": "/weather",
                "button": "Open Weather",
            },
            {
                "title": "Map",
                "subtitle": "Customer locations, jobsite map, and route planning.",
                "url": "/map",
                "button": "Open Map",
            },
        ],
    },

    "field-operations": {
        "title": "Field Operations",
        "subtitle": "Crew tools, employee dashboard, field logs, GPS, and photos.",
        "description": "The working side of the app for the people actually doing the work.",
        "items": [
            {
                "title": "Employee Dashboard",
                "subtitle": "Crew portal, daily tools, profile, and clock in/out.",
                "url": "/employee",
                "button": "Open Employee Dashboard",
            },
            {
                "title": "Crew List",
                "subtitle": "Crew records, employees, and field users.",
                "url": "/crew",
                "button": "Open Crew",
            },
            {
                "title": "Field Logs",
                "subtitle": "Job notes, labor, materials, problems, and jobsite updates.",
                "url": "/field-logs",
                "button": "Open Field Logs",
            },
            {
                "title": "GPS Day Log",
                "subtitle": "GPS activity, stops, and day movement records.",
                "url": "/gps-day-log",
                "button": "Open GPS Day",
            },
            {
                "title": "Photos",
                "subtitle": "Upload and review jobsite photos.",
                "url": "/photos",
                "button": "Open Photos",
            },
        ],
    },

    "pool-systems": {
        "title": "Pool Systems",
        "subtitle": "Pool monitoring, Pentair access, weather protection, and equipment notes.",
        "description": "Everything related to monitored pools, pool equipment, heaters, pumps, filters, freeze risk, and service history.",
        "items": [
            {
                "title": "Pool Monitoring",
                "subtitle": "Open Pentair Pro links, track alerts, notes, and next actions.",
                "url": "/pool-monitoring",
                "button": "Open Pool Monitoring",
            },
            {
                "title": "Weather Protection",
                "subtitle": "Freeze watch, weather watch, forecast, radar, and pool protection planning.",
                "url": "/weather",
                "button": "Open Weather Protection",
            },
            {
                "title": "Photos",
                "subtitle": "Pool equipment photos, pad photos, repairs, and job documentation.",
                "url": "/photos",
                "button": "Open Photos",
            },
        ],
    },

    "business": {
        "title": "Business",
        "subtitle": "Employees, QuickBooks, invoice import, design studio, and office tools.",
        "description": "Company-side tools for running the business instead of working the jobsite.",
        "items": [
            {
                "title": "Employees",
                "subtitle": "Employee list, roles, crew access, and staff records.",
                "url": "/employees",
                "button": "Open Employees",
            },
            {
                "title": "QuickBooks",
                "subtitle": "QuickBooks invoice area and imported invoice records.",
                "url": "/quickbooks",
                "button": "Open QuickBooks",
            },
            {
                "title": "Invoice Import",
                "subtitle": "Import QuickBooks invoice CSV records.",
                "url": "/quickbooks/invoices/import",
                "button": "Open Import",
            },
            {
                "title": "Design Studio",
                "subtitle": "Change the app look, dashboard cards, images, and layout.",
                "url": "/design-studio",
                "button": "Open Design Studio",
            },
            {
                "title": "Invisible Office",
                "subtitle": "Internal notes, admin search, and office tools.",
                "url": "/invisible-office",
                "button": "Open Invisible Office",
            },
        ],
    },

    "jarvis-tools": {
        "title": "Jarvis",
        "subtitle": "AI system tools.",
        "description": "The Jarvis section is now cleaned up to show only the AI Systems card.",
        "items": [
            {
                "title": "AI Systems",
                "subtitle": "Assistant and AI system tools.",
                "url": "/ai-systems",
                "button": "Open AI Systems",
            },
        ],
    },
}

@app.get("/accounts", response_class=HTMLResponse)
def accounts_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["accounts"]),
    )


@app.get("/today-dashboard", response_class=HTMLResponse)
def today_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["today"]),
    )


@app.get("/field-operations", response_class=HTMLResponse)
def field_operations_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["field-operations"]),
    )


@app.get("/pool-systems", response_class=HTMLResponse)
def pool_systems_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["pool-systems"]),
    )


@app.get("/business", response_class=HTMLResponse)
def business_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["business"]),
    )


@app.get("/jarvis-tools", response_class=HTMLResponse)
def jarvis_tools_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["jarvis-tools"]),
    )

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, y: int = None, m: int = None):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/jarvis", status_code=303)

# =========================================
# SAFE NAVIGATION ALIASES
# Keeps old dashboard/client/crew buttons from breaking
# =========================================

@app.get("/handle-it", response_class=HTMLResponse)
def handle_it_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/organize-my-day", status_code=303)


@app.get("/send-it", response_class=HTMLResponse)
def send_it_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/assistant-interview-live", status_code=303)


@app.get("/sendit", response_class=HTMLResponse)
def sendit_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/assistant-interview-live", status_code=303)


@app.get("/talk-to-jarvis", response_class=HTMLResponse)
def talk_to_jarvis_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/assistant-interview-live", status_code=303)


@app.get("/talk-to-jarvis-live", response_class=HTMLResponse)
def talk_to_jarvis_live_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/assistant-interview-live", status_code=303)


@app.get("/ai", response_class=HTMLResponse)
def ai_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/assistant-interview-live", status_code=303)


@app.get("/assistant-live", response_class=HTMLResponse)
def assistant_live_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/assistant-interview-live", status_code=303)


@app.get("/schedule/today", response_class=HTMLResponse)
def schedule_today_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/schedule/day", status_code=303)


@app.get("/todays-schedule", response_class=HTMLResponse)
def todays_schedule_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/schedule/day", status_code=303)

def classify_invisible_office_item(text: str):
    """
    First-pass Jarvis filing logic.
    This sorts Assistant Live messages into useful Invisible Office buckets.
    """
    raw = (text or "").strip()
    lower = raw.lower()

    category = "General Note"
    priority = "Normal"

    if any(w in lower for w in ["call", "text", "email", "follow up", "follow-up", "reach out", "check with"]):
        category = "Client Follow-Up"

    if any(w in lower for w in ["material", "materials", "need", "buy", "pickup", "pick up", "order", "salt", "check valve", "pipe", "fitting"]):
        category = "Material Needed"

    if any(w in lower for w in ["bill", "billing", "invoice", "paid", "payment", "charge", "estimate", "quote"]):
        category = "Billing Note"

    if any(w in lower for w in ["schedule", "tomorrow", "next week", "monday", "tuesday", "wednesday", "thursday", "friday"]):
        category = "Schedule Task"

    if any(w in lower for w in ["problem", "issue", "broken", "leak", "leaking", "error", "failed", "bad", "cracked", "not working"]):
        category = "Problem Found"

    if any(w in lower for w in ["heater", "pump", "filter", "automation", "salt cell", "intellicenter", "pentair", "hayward", "valve", "actuator"]):
        category = "Equipment Note"

    if any(w in lower for w in ["urgent", "asap", "emergency", "today", "right now", "critical"]):
        priority = "High"

    title = raw[:70].strip()
    if len(raw) > 70:
        title += "..."

    return {
        "category": category,
        "priority": priority,
        "title": title or "Jarvis Note",
        "body": raw,
    }


def save_invisible_office_item(
    request: Request,
    body: str,
    source: str = "manual",
    category: str = "",
    title: str = "",
    client: str = "",
    property: str = "",
    job_id: int | None = None,
    assigned_to: str = "",
    due_date: str = "",
    priority: str = "",
):
    u = current_user(request) or {}

    classified = classify_invisible_office_item(body)

    final_category = category.strip() or classified["category"]
    final_title = title.strip() or classified["title"]
    final_priority = priority.strip() or classified["priority"]

    exec_sql(
        """
        INSERT INTO invisible_office_items
        (source, category, title, body, client, property, job_id, assigned_to, due_date, priority, status, created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            source,
            final_category,
            final_title,
            body.strip(),
            client.strip(),
            property.strip(),
            job_id,
            assigned_to.strip(),
            due_date.strip(),
            final_priority,
            "Open",
            u.get("name") or u.get("username") or "",
            datetime.now().isoformat(timespec="seconds"),
        )
    )

@app.get("/assistant-interview-live", response_class=HTMLResponse)
def assistant_interview_live(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "assistant_interview_live.html",
        ctx(request)
    )


@app.get("/ai-systems", response_class=HTMLResponse)
def ai_systems(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "ai_systems.html",
        ctx(request)
    )


@app.post("/assistant-live/send")
def assistant_live_send(
    request: Request,
    message: str = Form(""),
    client: str = Form(""),
    property: str = Form(""),
    due_date: str = Form(""),
    priority: str = Form(""),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    text = message.strip()

    if text:
        save_invisible_office_item(
            request=request,
            body=text,
            source="Assistant Live",
            client=client,
            property=property,
            due_date=due_date,
            priority=priority,
        )

    return RedirectResponse("/invisible-office", status_code=303)

@app.get("/today", response_class=HTMLResponse)
def today_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/organize-my-day", status_code=303)


@app.get("/todays-work", response_class=HTMLResponse)
def todays_work_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/organize-my-day", status_code=303)


@app.get("/today-work", response_class=HTMLResponse)
def today_work_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/organize-my-day", status_code=303)


@app.get("/my-day", response_class=HTMLResponse)
def my_day_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if is_employee(u):
        return RedirectResponse("/crew/my-day", status_code=303)

    return RedirectResponse("/organize-my-day", status_code=303)


@app.get("/crew-login", response_class=HTMLResponse)
def crew_login_alias(request: Request):
    return RedirectResponse("/login", status_code=303)


@app.get("/crew-portal", response_class=HTMLResponse)
def crew_portal_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/employee", status_code=303)


@app.get("/employees", response_class=HTMLResponse)
def employees_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/crew", status_code=303)


@app.get("/calendar", response_class=HTMLResponse)
def calendar_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/schedule/year", status_code=303)


@app.get("/daily-schedule", response_class=HTMLResponse)
def daily_schedule_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/schedule/day", status_code=303)


@app.get("/monthly-schedule", response_class=HTMLResponse)
def monthly_schedule_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/schedule/year", status_code=303)

# =========================================
# ADMIN LINK CHECK
# =========================================

@app.get("/gps-day-log", response_class=HTMLResponse)
def gps_day_log_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/gps/day", status_code=303)


@app.get("/gps-stops", response_class=HTMLResponse)
def gps_stops_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/gps/stops", status_code=303)

@app.get("/admin/link-check", response_class=HTMLResponse)
def admin_link_check(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not is_admin(u):
        return RedirectResponse("/jarvis", status_code=303)

    links = [
        ("Dashboard / Jarvis", "/jarvis"),
        ("Design Studio", "/design-studio"),
        ("Pool Monitoring", "/pool-monitoring"),
        ("Organize My Day", "/organize-my-day"),
        ("Handle It", "/handle-it"),
        ("Schedule", "/schedule"),
        ("Today Schedule", "/schedule/today"),
        ("GPS Day Log", "/gps/day"),
        ("GPS Stops", "/gps/stops"),
        ("Crew Login", "/crew-login"),
        ("Crew Portal", "/employee"),
        ("Crew My Day", "/crew/my-day"),
        ("Clients", "/clients"),
        ("Properties", "/properties"),
        ("Jobs", "/jobs"),
        ("Photos", "/photos"),
        ("Crew", "/crew"),
        ("Weather", "/weather"),
        ("Weather Watch", "/weather"),
        ("Map", "/map"),
        ("Daily Schedule", "/schedule/day"),
        ("Full Calendar", "/schedule/year"),
        ("Field Logs", "/field-logs"),
        ("Estimates", "/estimates"),
        ("Job Costing", "/job-costing"),
        ("QuickBooks", "/quickbooks"),
        ("AI Systems", "/ai-systems"),
        ("Invisible Office", "/invisible-office"),
        ("Talk to Jarvis", "/assistant-interview-live"),
        ("Edit Dashboard", "/dashboard/theme"),
        ("Logout", "/logout"),
    ]

    return templates.TemplateResponse(
        "link_check.html",
        ctx(request, links=links)
    )

@app.get("/detailed", response_class=HTMLResponse)
def detailed_redirect(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/jarvis", status_code=303)


@app.get("/dashboard/theme", response_class=HTMLResponse)
def dashboard_theme(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not is_admin(u):
        return RedirectResponse("/jarvis", status_code=303)

    return RedirectResponse("/design-studio", status_code=303)


@app.post("/dashboard/theme")
async def dashboard_theme_save(request: Request,
    title: str = Form(""), subtitle: str = Form(""), hero_title: str = Form(""), hero_subtitle: str = Form(""),
    background_image: UploadFile = File(None), calendar_background: UploadFile = File(None),
    clients_image: UploadFile = File(None), properties_image: UploadFile = File(None), jobs_image: UploadFile = File(None),
    schedule_image: UploadFile = File(None), photos_image: UploadFile = File(None), crew_image: UploadFile = File(None),
    estimates_image: UploadFile = File(None), job_costing_image: UploadFile = File(None), quickbooks_image: UploadFile = File(None),
    weather_image: UploadFile = File(None), field_log_image: UploadFile = File(None), map_image: UploadFile = File(None)):
    u = require_login(request)
    if not is_admin(u):
        return login_redirect()
    t = theme()
    for k, v in {"title": title, "subtitle": subtitle, "hero_title": hero_title, "hero_subtitle": hero_subtitle}.items():
        t[k] = v.strip()
    for key, file in {
        "background_image": background_image, "calendar_background": calendar_background, "clients_image": clients_image,
        "properties_image": properties_image, "jobs_image": jobs_image, "schedule_image": schedule_image, "photos_image": photos_image,
        "crew_image": crew_image, "estimates_image": estimates_image, "job_costing_image": job_costing_image,
        "quickbooks_image": quickbooks_image, "weather_image": weather_image, "field_log_image": field_log_image, "map_image": map_image,
    }.items():
        url = await save_upload(file)
        if url:
            t[key] = url
    save_theme(t)
    return RedirectResponse("/jarvis", status_code=303)

@app.get("/design-studio", response_class=HTMLResponse)
def design_studio_page(request: Request):
    u = require_login(request)
    if not is_admin(u):
        return login_redirect()

    return templates.TemplateResponse(
        "design_studio.html",
        ctx(request, design=design_settings())
    )


@app.post("/design-studio")
def design_studio_save(
    request: Request,
    legacy_line: str = Form(""),
    crest_image: str = Form(""),
    motto_first: str = Form(""),
    motto_second: str = Form(""),
    hero_subline: str = Form(""),
    search_title: str = Form(""),
    search_subtitle: str = Form(""),
    search_placeholder: str = Form(""),
    handle_button: str = Form(""),
    page_top_space: str = Form("54px"),
    crest_width: str = Form("920px"),
    crest_height: str = Form("420px"),
    motto_size: str = Form("clamp(3rem, 7vw, 7.8rem)"),
    motto_top_space: str = Form("22px"),
    section_gap: str = Form("22px"),
    button_height: str = Form("104px"),
    schedule_title: str = Form("Schedule"),
    schedule_day_title: str = Form("Daily Schedule"),
    schedule_week_title: str = Form("Weekly Schedule"),
    schedule_subtitle: str = Form("Jobs, field work, service calls, and crew movement."),
    schedule_empty_text: str = Form("No jobs are scheduled for this view yet."),
    schedule_button_daily: str = Form("Daily"),
    schedule_button_weekly: str = Form("Weekly"),
    schedule_button_yearly: str = Form("Yearly"),
    map_title: str = Form("Field Map"),
    map_subtitle: str = Form("Property pins, clocked-in employees, and jobsite locations."),
    map_height: str = Form("560px"),
    mobile_map_height: str = Form("480px"),
    map_top_padding: str = Form("115px"),
    map_mobile_top_padding: str = Form("95px"),
    login_title: str = Form("Heinlin Field Ops"),
    login_legacy_line: str = Form("Founded 1907 • 5 Generations Strong"),
    login_subtitle: str = Form("Built by the hands that perfected the term work hard play harder."),
    login_button_text: str = Form("Enter Operations Center"),
    login_crest_image: str = Form("/static/heinlin-wide-crest.png"),
    login_background_image: str = Form("/static/heinlin-wide-crest.png"),
    login_crest_width: str = Form("760px"),
    login_card_width: str = Form("460px"),
    crew_title: str = Form("Employees"),
    crew_subtitle: str = Form("Crew access, login credentials, roles, and field visibility."),
    crew_button_text: str = Form("Add Employee"),

    employee_title: str = Form("Crew Portal"),
    employee_subtitle: str = Form("My jobs, clock in/out, photos, field notes, weather, and map."),
    employee_button_text: str = Form("Clock / Field Work"),
    crew_dashboard_title: str = Form("Crew Portal"),
    crew_dashboard_subtitle: str = Form("My jobs, clock in/out, photos, field notes, weather, and map."),
    crew_dashboard_section_title: str = Form("Crew Tools"),
    crew_dashboard_crest_image: str = Form("/static/heinlin-wide-crest.png"),
    crew_dashboard_crest_width: str = Form("340px"),
    crew_dashboard_crest_top: str = Form("210px"),
    crew_dashboard_crest_right: str = Form("70px"),
    crew_dashboard_crest_opacity: str = Form("0.92"),
    crew_dashboard_hero_padding_top: str = Form("150px"),
    crew_dashboard_dashboard_padding_top: str = Form("120px"),
    crew_dashboard_tools_json: str = Form(""),
    ai_systems_cards_json: str = Form(""),

    photos_title: str = Form("Photos"),
    photos_subtitle: str = Form("Job photos, property photos, progress shots, and field proof."),
    photos_button_text: str = Form("Upload Photos"),

    pool_monitoring_title: str = Form("Pool Monitoring"),
    pool_monitoring_subtitle: str = Form("Pentair access, pool alerts, service notes, and monitored systems."),
    pool_monitoring_button_text: str = Form("Add Pool Monitor"),
    clients_title: str = Form("Clients"),
    clients_subtitle: str = Form("The people, properties, pools, and promises we are responsible for."),
    clients_button_text: str = Form("Add Client"),
    properties_title: str = Form("Properties"),
    properties_subtitle: str = Form("Every pool, address, gate code, equipment pad, and detail in one place."),
    properties_button_text: str = Form("Add Property"),
    jobs_title: str = Form("Jobs"),
    jobs_subtitle: str = Form("Scheduled work, service calls, repairs, and field notes."),
    jobs_button_text: str = Form("Add Job"),

):
    u = require_login(request)
    if not is_admin(u):
        return login_redirect()

    data = design_settings()

    data["dashboard"] = {
        "legacy_line": legacy_line.strip() or DEFAULT_DESIGN["dashboard"]["legacy_line"],
        "crest_image": crest_image.strip() or DEFAULT_DESIGN["dashboard"]["crest_image"],
        "motto_first": motto_first.strip() or DEFAULT_DESIGN["dashboard"]["motto_first"],
        "motto_second": motto_second.strip() or DEFAULT_DESIGN["dashboard"]["motto_second"],
        "hero_subline": hero_subline.strip() or DEFAULT_DESIGN["dashboard"]["hero_subline"],
        "search_title": search_title.strip() or DEFAULT_DESIGN["dashboard"]["search_title"],
        "search_subtitle": search_subtitle.strip() or DEFAULT_DESIGN["dashboard"]["search_subtitle"],
        "search_placeholder": search_placeholder.strip() or DEFAULT_DESIGN["dashboard"]["search_placeholder"],
        "handle_button": handle_button.strip() or DEFAULT_DESIGN["dashboard"]["handle_button"],

        "page_top_space": page_top_space.strip() or "54px",
        "crest_width": crest_width.strip() or "920px",
        "crest_height": crest_height.strip() or "420px",
        "motto_size": motto_size.strip() or "clamp(3rem, 7vw, 7.8rem)",
        "motto_top_space": motto_top_space.strip() or "22px",
        "section_gap": section_gap.strip() or "22px",
        "button_height": button_height.strip() or "104px",
    }

    data["schedule"] = {
        "title": schedule_title.strip() or "Schedule",
        "day_title": schedule_day_title.strip() or "Daily Schedule",
        "week_title": schedule_week_title.strip() or "Weekly Schedule",
        "subtitle": schedule_subtitle.strip() or "Jobs, field work, service calls, and crew movement.",
        "empty_text": schedule_empty_text.strip() or "No jobs are scheduled for this view yet.",
        "button_daily": schedule_button_daily.strip() or "Daily",
        "button_weekly": schedule_button_weekly.strip() or "Weekly",
        "button_yearly": schedule_button_yearly.strip() or "Yearly",
        "button_jobs": "Jobs",
        "button_dashboard": "Dashboard",
        "button_text": "Add Schedule Item",
    }

    data["map"] = {
        "title": map_title.strip() or "Field Map",
        "subtitle": map_subtitle.strip() or "Property pins, clocked-in employees, and jobsite locations.",
        "map_height": map_height.strip() or "560px",
        "mobile_map_height": mobile_map_height.strip() or "480px",
        "top_padding": map_top_padding.strip() or "115px",
        "mobile_top_padding": map_mobile_top_padding.strip() or "95px",
    }

    data["login"] = {
        "title": login_title.strip() or "Heinlin Field Ops",
        "legacy_line": login_legacy_line.strip() or "Founded 1907 • 5 Generations Strong",
        "subtitle": login_subtitle.strip() or "Built by the hands that perfected the term work hard play harder.",
        "button_text": login_button_text.strip() or "Enter Operations Center",
        "crest_image": login_crest_image.strip() or "/static/heinlin-wide-crest.png",
        "background_image": login_background_image.strip() or "/static/heinlin-wide-crest.png",
        "crest_width": login_crest_width.strip() or "760px",
        "card_width": login_card_width.strip() or "460px",
    }
    data["crew"] = {
        "title": crew_title.strip() or "Employees",
        "subtitle": crew_subtitle.strip() or "Crew access, login credentials, roles, and field visibility.",
        "button_text": crew_button_text.strip() or "Add Employee",
    }

    data["employee"] = {
        "title": employee_title.strip() or "Crew Portal",
        "subtitle": employee_subtitle.strip() or "My jobs, clock in/out, photos, field notes, weather, and map.",
        "button_text": employee_button_text.strip() or "Clock / Field Work",
    }

    previous_crew_dashboard = data.get("crew_dashboard", DEFAULT_DESIGN["crew_dashboard"])
    crew_dashboard_tools = previous_crew_dashboard.get("tools", DEFAULT_DESIGN["crew_dashboard"]["tools"])
    try:
        parsed_tools = json.loads(crew_dashboard_tools_json or "[]")
        if isinstance(parsed_tools, list):
            crew_dashboard_tools = parsed_tools
    except Exception:
        pass

    data["crew_dashboard"] = {
        "greeting_prefix": previous_crew_dashboard.get("greeting_prefix", "Good morning"),
        "title": crew_dashboard_title.strip() or "Crew Portal",
        "subtitle": crew_dashboard_subtitle.strip() or "My jobs, clock in/out, photos, field notes, weather, and map.",
        "section_title": crew_dashboard_section_title.strip() or "Crew Tools",
        "crest_image": crew_dashboard_crest_image.strip() or "/static/heinlin-wide-crest.png",
        "crest_width": crew_dashboard_crest_width.strip() or "340px",
        "crest_top": crew_dashboard_crest_top.strip() or "210px",
        "crest_right": crew_dashboard_crest_right.strip() or "70px",
        "crest_opacity": crew_dashboard_crest_opacity.strip() or "0.92",
        "hero_padding_top": crew_dashboard_hero_padding_top.strip() or "150px",
        "dashboard_padding_top": crew_dashboard_dashboard_padding_top.strip() or "120px",
        "tools": crew_dashboard_tools,
    }

    previous_ai_systems = data.get("ai_systems", DEFAULT_DESIGN["ai_systems"])
    ai_systems_cards = previous_ai_systems.get("cards", DEFAULT_DESIGN["ai_systems"]["cards"])
    try:
        parsed_ai_cards = json.loads(ai_systems_cards_json or "[]")
        if isinstance(parsed_ai_cards, list):
            ai_systems_cards = parsed_ai_cards
    except Exception:
        pass

    data["ai_systems"] = {
        "title": previous_ai_systems.get("title", "AI Systems"),
        "subtitle": previous_ai_systems.get("subtitle", "All Jarvis tools, office memory, and AI workflows in one place."),
        "cards": ai_systems_cards,
    }

    data["photos"] = {
        "title": photos_title.strip() or "Photos",
        "subtitle": photos_subtitle.strip() or "Job photos, property photos, progress shots, and field proof.",
        "button_text": photos_button_text.strip() or "Upload Photos",
    }

    data["pool_monitoring"] = {
        "title": pool_monitoring_title.strip() or "Pool Monitoring",
        "subtitle": pool_monitoring_subtitle.strip() or "Pentair access, pool alerts, service notes, and monitored systems.",
        "button_text": pool_monitoring_button_text.strip() or "Add Pool Monitor",
    }


    data["clients"] = {
        "title": clients_title.strip() or "Clients",
        "subtitle": clients_subtitle.strip() or "The people, properties, pools, and promises we are responsible for.",
        "button_text": clients_button_text.strip() or "Add Client",
    }

    data["properties"] = {
        "title": properties_title.strip() or "Properties",
        "subtitle": properties_subtitle.strip() or "Every pool, address, gate code, equipment pad, and detail in one place.",
        "button_text": properties_button_text.strip() or "Add Property",
    }

    data["jobs"] = {
        "title": jobs_title.strip() or "Jobs",
        "subtitle": jobs_subtitle.strip() or "Scheduled work, service calls, repairs, and field notes.",
        "button_text": jobs_button_text.strip() or "Add Job",
    }

    save_design_settings(data)

    return RedirectResponse("/design-studio", status_code=303)

@app.post("/calendar/day-image")
async def calendar_day_image(request: Request, day_date: str = Form(...), notes: str = Form(""), image: UploadFile = File(None)):
    u = require_login(request)
    if not is_admin(u):
        return login_redirect()
    existing = one("SELECT * FROM poolops2_calendar_day_images WHERE day_date=?", (day_date,))
    url = await save_upload(image)
    if existing:
        exec_sql("UPDATE poolops2_calendar_day_images SET image_url=coalesce(nullif(?,''), image_url), notes=? WHERE day_date=?", (url, notes, day_date))
    else:
        exec_sql("INSERT INTO poolops2_calendar_day_images (day_date,image_url,notes) VALUES (?,?,?)", (day_date, url, notes))
    return RedirectResponse("/jarvis", status_code=303)


# =========================================
# ADMIN DELETE HELPERS
# =========================================
def _safe_delete_upload(photo_url: str):
    """Delete local uploaded file when it lives under /static/uploads/."""
    if not photo_url:
        return
    try:
        if not str(photo_url).startswith("/static/uploads/"):
            return
        rel = str(photo_url).replace("/static/", "", 1)
        path = ROOT / "app" / "static" / rel
        # Never allow a URL to escape the uploads folder.
        uploads_root = (ROOT / "app" / "static" / "uploads").resolve()
        resolved = path.resolve()
        if uploads_root in resolved.parents or resolved == uploads_root:
            if resolved.exists() and resolved.is_file():
                resolved.unlink()
    except Exception:
        pass


def _try_exec(sql, params=()):
    try:
        return exec_sql(sql, params)
    except Exception:
        return None


def _delete_photo_records(photo_rows):
    for ph in photo_rows or []:
        _safe_delete_upload(ph.get("photo_url", ""))
        _try_exec("DELETE FROM poolops2_photo_logs WHERE id=?", (ph.get("id"),))



@app.get("/clients", response_class=HTMLResponse)
def clients(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    client_rows = rows(
        """
        SELECT *
        FROM poolops2_clients
        ORDER BY name ASC
        """
    )

    return templates.TemplateResponse(
        "clients.html",
        ctx(
            request,
            clients=client_rows,
            records=client_rows,
            items=client_rows,
            client_list=client_rows,
            q="",
        )
    )

@app.get("/clients/{client_id}", response_class=HTMLResponse)
def client_detail(request: Request, client_id: int):
    u = require_login(request)
    if not u: return login_redirect()
    client = one("SELECT * FROM poolops2_clients WHERE id=?", (client_id,))
    if not client: return admin_redirect(u)
    if not client_can_access(u, client_id, client.get("name", "")):
        return admin_redirect(u)
    props = rows("SELECT * FROM poolops2_properties WHERE client_id=? OR client=? ORDER BY address", (client_id, client["name"]))
    jobs = rows("SELECT * FROM poolops2_jobs WHERE client=? ORDER BY id DESC", (client["name"],))
    photos = rows("SELECT * FROM poolops2_photo_logs WHERE client=? ORDER BY id DESC", (client["name"],))
    return templates.TemplateResponse("client_detail.html", ctx(request, client=client, properties=props, jobs=jobs, photos=photos))




@app.post("/clients/{client_id}/photo")
async def client_photo_upload(
    request: Request,
    client_id: int,
    title: str = Form("Client Photo"),
    notes: str = Form(""),
    photo: UploadFile = File(None),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    client = one("SELECT * FROM poolops2_clients WHERE id=?", (client_id,))
    if not client or not client_can_access(u, client_id, client.get("name", "")):
        return admin_redirect(u)

    url = await save_upload(photo)

    if url:
        exec_sql(
            """
            INSERT INTO poolops2_photo_logs
            (client, photo_type, title, photo_url, date, notes)
            VALUES (?,?,?,?,?,?)
            """,
            (
                client.get("name", ""),
                "Client",
                title.strip() or "Client Photo",
                url,
                date.today().isoformat(),
                notes,
            )
        )

    return RedirectResponse(f"/clients/{client_id}", status_code=303)


@app.post("/clients/{client_id}/save")
async def client_save(request: Request, client_id: int, name: str = Form(""), contact_name: str = Form(""), phone: str = Form(""), mobile: str = Form(""), email: str = Form(""), billing_address: str = Form(""), city: str = Form(""), state: str = Form(""), zip_code: str = Form(""), notes: str = Form(""), portal_username: str = Form(""), portal_password: str = Form(""), card_image: UploadFile = File(None)):
    u = require_login(request)
    if not u: return login_redirect()
    client = one("SELECT * FROM poolops2_clients WHERE id=?", (client_id,))
    if not client or not client_can_access(u, client_id, client.get("name", "")):
        return admin_redirect(u)
    url = await save_upload(card_image) if is_admin(u) else ""
    # Clients may update their own contact/profile info. Only admins can change portal login credentials or card images.
    if is_admin(u):
        if url:
            exec_sql("UPDATE poolops2_clients SET name=?, contact_name=?, phone=?, mobile=?, email=?, billing_address=?, city=?, state=?, zip_code=?, notes=?, portal_username=?, portal_password=?, card_image=? WHERE id=?", (name, contact_name, phone, mobile, email, billing_address, city, state, zip_code, notes, portal_username, portal_password, url, client_id))
        else:
            exec_sql("UPDATE poolops2_clients SET name=?, contact_name=?, phone=?, mobile=?, email=?, billing_address=?, city=?, state=?, zip_code=?, notes=?, portal_username=?, portal_password=? WHERE id=?", (name, contact_name, phone, mobile, email, billing_address, city, state, zip_code, notes, portal_username, portal_password, client_id))
    else:
        exec_sql("UPDATE poolops2_clients SET name=?, contact_name=?, phone=?, mobile=?, email=?, billing_address=?, city=?, state=?, zip_code=?, notes=? WHERE id=?", (name, contact_name, phone, mobile, email, billing_address, city, state, zip_code, notes, client_id))
    return RedirectResponse("/jarvis" if is_client(u) else f"/clients/{client_id}", status_code=303)


@app.post("/clients/new")
async def client_new(request: Request, name: str = Form("New Client")):
    if not is_admin(require_login(request)): return login_redirect()
    cid = exec_sql("INSERT INTO poolops2_clients (name) VALUES (?)", (name.strip() or "New Client",))
    return RedirectResponse(f"/clients/{cid}", status_code=303)


@app.post("/clients/{client_id}/delete")
def client_delete(request: Request, client_id: int):
    if not is_admin(require_login(request)):
        return login_redirect()

    client = one("SELECT * FROM poolops2_clients WHERE id=?", (client_id,))
    if not client:
        return RedirectResponse("/clients", status_code=303)

    client_name = client.get("name", "")
    props = rows("SELECT * FROM poolops2_properties WHERE client_id=? OR client=?", (client_id, client_name))
    prop_ids = [p.get("id") for p in props if p.get("id") is not None]

    # Delete related property photos/files.
    photo_rows = rows("SELECT * FROM poolops2_photo_logs WHERE client=?", (client_name,))
    for pid in prop_ids:
        photo_rows += rows("SELECT * FROM poolops2_photo_logs WHERE property_id=?", (pid,))
    seen = set()
    unique_photos = []
    for ph in photo_rows:
        if ph.get("id") not in seen:
            seen.add(ph.get("id"))
            unique_photos.append(ph)
    _delete_photo_records(unique_photos)

    # Delete related jobs, job costs, invoices, equipment, and properties.
    jobs = rows("SELECT * FROM poolops2_jobs WHERE client=?", (client_name,))
    for j in jobs:
        jid = j.get("id")
        _try_exec("DELETE FROM poolops2_job_costs WHERE job_id=?", (jid,))
        _try_exec("DELETE FROM poolops2_invoices WHERE job_id=?", (jid,))
        _try_exec("DELETE FROM poolops2_jobs WHERE id=?", (jid,))

    for pid in prop_ids:
        _try_exec("DELETE FROM poolops2_equipment WHERE property_id=?", (pid,))
        _try_exec("DELETE FROM poolops2_properties WHERE id=?", (pid,))

    _safe_delete_upload(client.get("card_image", ""))
    _try_exec("DELETE FROM poolops2_clients WHERE id=?", (client_id,))
    return RedirectResponse("/clients", status_code=303)


@app.get("/properties", response_class=HTMLResponse)
def properties(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    property_rows = rows(
        """
        SELECT *
        FROM poolops2_properties
        ORDER BY id DESC
        """
    )

    return templates.TemplateResponse(
        "properties.html",
        ctx(
            request,
            properties=property_rows,
            records=property_rows,
            items=property_rows,
            property_list=property_rows,
        )
    )
@app.get("/properties/{property_id}", response_class=HTMLResponse)
def property_detail(request: Request, property_id: int):
    u = require_login(request)
    if not u: return login_redirect()
    prop = one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    if not prop: return admin_redirect(u)
    if not property_can_access(u, prop):
        return admin_redirect(u)
    photos = rows("SELECT * FROM poolops2_photo_logs WHERE property_id=? ORDER BY id DESC", (property_id,))
    equip = rows("SELECT * FROM poolops2_equipment WHERE property_id=? ORDER BY id DESC", (property_id,))
    jobs = rows("SELECT * FROM poolops2_jobs WHERE address=? OR property=? ORDER BY id DESC", (prop["address"], prop["property_name"]))
    return templates.TemplateResponse("property_detail.html", ctx(request, prop=prop, photos=photos, equipment=equip, jobs=jobs))


@app.post("/properties/{property_id}/save")
async def property_save(request: Request, property_id: int, client: str = Form(""), property_name: str = Form(""), address: str = Form(""), city: str = Form(""), state: str = Form(""), zip_code: str = Form(""), pool_type: str = Form(""), pool_size: str = Form(""), pool_depth: str = Form(""), cover_type: str = Form(""), finish_type: str = Form(""), pump_model: str = Form(""), filter_model: str = Form(""), heater_model: str = Form(""), sanitizer: str = Form(""), automation_system: str = Form(""), gate_code: str = Form(""), service_plan: str = Form(""), pool_notes: str = Form(""), equipment_notes: str = Form(""), notes: str = Form(""), card_image: UploadFile = File(None)):
    u = require_login(request)
    if not u: return login_redirect()
    prop = one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    if not prop or not property_can_access(u, prop):
        return admin_redirect(u)
    url = await save_upload(card_image) if is_admin(u) else ""
    # Clients can update their own property/pool/equipment details; only admins can reassign client or card image.
    if is_admin(u):
        base = (client, property_name, address, city, state, zip_code, pool_type, pool_size, pool_depth, cover_type, finish_type, pump_model, filter_model, heater_model, sanitizer, automation_system, gate_code, service_plan, pool_notes, equipment_notes, notes)
        if url:
            exec_sql("UPDATE poolops2_properties SET client=?, property_name=?, address=?, city=?, state=?, zip_code=?, pool_type=?, pool_size=?, pool_depth=?, cover_type=?, finish_type=?, pump_model=?, filter_model=?, heater_model=?, sanitizer=?, automation_system=?, gate_code=?, service_plan=?, pool_notes=?, equipment_notes=?, notes=?, card_image=? WHERE id=?", base + (url, property_id))
        else:
            exec_sql("UPDATE poolops2_properties SET client=?, property_name=?, address=?, city=?, state=?, zip_code=?, pool_type=?, pool_size=?, pool_depth=?, cover_type=?, finish_type=?, pump_model=?, filter_model=?, heater_model=?, sanitizer=?, automation_system=?, gate_code=?, service_plan=?, pool_notes=?, equipment_notes=?, notes=? WHERE id=?", base + (property_id,))
    else:
        exec_sql("UPDATE poolops2_properties SET property_name=?, address=?, city=?, state=?, zip_code=?, pool_type=?, pool_size=?, pool_depth=?, cover_type=?, finish_type=?, pump_model=?, filter_model=?, heater_model=?, sanitizer=?, automation_system=?, gate_code=?, service_plan=?, pool_notes=?, equipment_notes=?, notes=? WHERE id=?", (property_name, address, city, state, zip_code, pool_type, pool_size, pool_depth, cover_type, finish_type, pump_model, filter_model, heater_model, sanitizer, automation_system, gate_code, service_plan, pool_notes, equipment_notes, notes, property_id))
    return RedirectResponse(f"/properties/{property_id}", status_code=303)


@app.post("/properties/{property_id}/photo")
async def property_photo(request: Request, property_id: int, title: str = Form("Property Photo"), notes: str = Form(""), photo: UploadFile = File(None)):
    u = require_login(request)
    if not u: return login_redirect()
    if is_client(u): return RedirectResponse("/jarvis", status_code=303)
    prop = one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    url = await save_upload(photo)
    if url and prop:
        exec_sql("INSERT INTO poolops2_photo_logs (property_id,client,photo_type,title,photo_url,date,notes) VALUES (?,?,?,?,?,?,?)", (property_id, prop.get("client", ""), "Property", title, url, date.today().isoformat(), notes))
    return RedirectResponse(f"/properties/{property_id}", status_code=303)


@app.post("/properties/{property_id}/equipment")
def property_equipment(request: Request, property_id: int, equipment_type: str = Form(""), brand: str = Form(""), model: str = Form(""), serial: str = Form(""), installed_date: str = Form(""), notes: str = Form("")):
    if not is_admin(require_login(request)): return login_redirect()
    exec_sql("INSERT INTO poolops2_equipment (property_id,equipment_type,brand,model,serial,installed_date,notes) VALUES (?,?,?,?,?,?,?)", (property_id, equipment_type, brand, model, serial, installed_date, notes))
    return RedirectResponse(f"/properties/{property_id}", status_code=303)


@app.post("/properties/new")
def property_new(request: Request, client: str = Form(""), address: str = Form("New Property")):
    if not is_admin(require_login(request)): return login_redirect()
    pid = exec_sql("INSERT INTO poolops2_properties (client,address) VALUES (?,?)", (client, address))
    return RedirectResponse(f"/properties/{pid}", status_code=303)


@app.post("/properties/{property_id}/delete")
def property_delete(request: Request, property_id: int):
    if not is_admin(require_login(request)):
        return login_redirect()

    prop = one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    if not prop:
        return RedirectResponse("/properties", status_code=303)

    # Delete photos/files tied directly to this property.
    _delete_photo_records(rows("SELECT * FROM poolops2_photo_logs WHERE property_id=?", (property_id,)))

    # Delete jobs that belong to this property/address and their costs/photos.
    jobs = rows("SELECT * FROM poolops2_jobs WHERE address=? OR property=?", (prop.get("address", ""), prop.get("property_name", "")))
    for j in jobs:
        jid = j.get("id")
        _delete_photo_records(rows("SELECT * FROM poolops2_photo_logs WHERE job_id=?", (jid,)))
        _try_exec("DELETE FROM poolops2_job_costs WHERE job_id=?", (jid,))
        _try_exec("DELETE FROM poolops2_invoices WHERE job_id=?", (jid,))
        _try_exec("DELETE FROM poolops2_jobs WHERE id=?", (jid,))

    _try_exec("DELETE FROM poolops2_equipment WHERE property_id=?", (property_id,))
    _safe_delete_upload(prop.get("card_image", ""))
    _try_exec("DELETE FROM poolops2_properties WHERE id=?", (property_id,))
    return RedirectResponse("/properties", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    job_rows = rows(
        """
        SELECT *
        FROM poolops2_jobs
        ORDER BY id DESC
        """
    )

    return templates.TemplateResponse(
        "jobs.html",
        ctx(
            request,
            jobs=job_rows,
            records=job_rows,
            items=job_rows,
            job_list=job_rows,
            q="",
        )
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: int):
    u = require_login(request)
    if not u: return login_redirect()
    if is_client(u): return RedirectResponse("/jarvis", status_code=303)
    job = one("SELECT * FROM poolops2_jobs WHERE id=?", (job_id,))
    if not job or not employee_can_access_job(u, job): return RedirectResponse("/jobs", status_code=303)
    costs = rows("SELECT * FROM poolops2_job_costs WHERE job_id=?", (job_id,))
    photos = rows("SELECT * FROM poolops2_photo_logs WHERE job_id=?", (job_id,))
    return templates.TemplateResponse("job_detail.html", ctx(request, job=job, costs=costs, photos=photos))


@app.post("/jobs/{job_id}/save")
def job_save(request: Request, job_id: int, client: str = Form(""), property: str = Form(""), address: str = Form(""), job_type: str = Form(""), status: str = Form(""), crew: str = Form(""), date: str = Form(""), priority: str = Form(""), notes: str = Form("")):
    if not is_admin(require_login(request)): return login_redirect()
    exec_sql("UPDATE poolops2_jobs SET client=?, property=?, address=?, job_type=?, status=?, crew=?, date=?, scheduled_start=?, priority=?, notes=? WHERE id=?", (client, property, address, job_type, status, crew, date, date, priority, notes, job_id))
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/new")
def job_new(request: Request, client: str = Form(""), property: str = Form(""), address: str = Form(""), job_type: str = Form("Service"), date: str = Form("")):
    if not is_admin(require_login(request)): return login_redirect()
    jid = exec_sql("INSERT INTO poolops2_jobs (client,property,address,job_type,status,crew,date,scheduled_start,priority,notes) VALUES (?,?,?,?,?,?,?,?,?,?)", (client, property, address, job_type, "Scheduled", "Unassigned", date, date, "Normal", ""))
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.post("/jobs/{job_id}/delete")
def job_delete(request: Request, job_id: int):
    if not is_admin(require_login(request)):
        return login_redirect()

    job = one("SELECT * FROM poolops2_jobs WHERE id=?", (job_id,))
    if not job:
        return RedirectResponse("/jobs", status_code=303)

    _delete_photo_records(rows("SELECT * FROM poolops2_photo_logs WHERE job_id=?", (job_id,)))
    _try_exec("DELETE FROM poolops2_job_costs WHERE job_id=?", (job_id,))
    _try_exec("DELETE FROM poolops2_invoices WHERE job_id=?", (job_id,))
    _try_exec("DELETE FROM poolops2_jobs WHERE id=?", (job_id,))
    return RedirectResponse("/jobs", status_code=303)

@app.post("/jobs/{job_id}/start")
def start_job(job_id: int, request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    exec_sql(
        "UPDATE poolops2_jobs SET status=? WHERE id=?",
        ("In Progress", job_id)
    )

    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/complete")
def complete_job(job_id: int, request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    exec_sql(
        "UPDATE poolops2_jobs SET status=? WHERE id=?",
        ("Complete", job_id)
    )

    return RedirectResponse(f"/jobs/{job_id}", status_code=303)

@app.get("/schedule/year", response_class=HTMLResponse)
def schedule_year(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    today = date.today()
    year = int(request.query_params.get("year", today.year))

    months = []
    for month in range(1, 13):
        cal = calendar.Calendar(firstweekday=6)
        days = []
        for week in cal.monthdayscalendar(year, month):
            days.extend(week)

        months.append({
            "year": year,
            "month": month,
            "name": calendar.month_name[month],
            "days": days,
        })

    return templates.TemplateResponse(
        "schedule_year.html",
        ctx(request, months=months, year=year)
    )

@app.get("/organize-my-day", response_class=HTMLResponse)
def organize_my_day(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    today = date.today().isoformat()

    today_jobs = [
        j for j in jobs_for_user(u)
        if schedule_date(j) == today
    ]

    overdue_jobs = [
        j for j in jobs_for_user(u)
        if schedule_date(j) and schedule_date(j) < today and str(j.get("status", "")).lower() not in ("complete", "completed", "done")
    ]

    clocked_in = []
    if is_admin(u):
        clocked_in = rows(
            "SELECT * FROM poolops2_employees WHERE clocked_in=? ORDER BY name",
            (True if USE_POSTGRES else 1,)
        )

    return templates.TemplateResponse(
        "organize_my_day.html",
        ctx(
            request,
            today=today,
            today_jobs=today_jobs,
            overdue_jobs=overdue_jobs,
            clocked_in=clocked_in,
        )
    )

@app.get("/crew/my-day", response_class=HTMLResponse)
def crew_my_day(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    today = date.today().isoformat()
    job_rows = jobs_for_user(u)

    my_jobs = []
    for j in job_rows:
        jd = schedule_date(j)
        status = str(j.get("status", "") or "").lower()
        if jd == today and status not in ("complete", "completed", "done"):
            my_jobs.append(j)

    return templates.TemplateResponse(
        "crew_my_day.html",
        ctx(request, today=today, my_jobs=my_jobs)
    )

@app.get("/schedule")
def schedule(request: Request):
    return RedirectResponse("/schedule/year", status_code=303)

@app.get("/schedule/month", response_class=HTMLResponse)
def schedule_month(request: Request):
    u = require_login(request)
    if not u: return login_redirect()
    return templates.TemplateResponse("schedule_month.html", ctx(request, days=month_grid(job_rows=jobs_for_user(u))))

@app.get("/schedule/day", response_class=HTMLResponse)
def schedule_day(request: Request):
    u = require_login(request)
    if not u: return login_redirect()
    selected_day = request.query_params.get("date") or date.today().isoformat()
    visible_jobs = [j for j in jobs_for_user(u) if schedule_date(j) == selected_day]
    design = design_settings()
    title = design.get("schedule", {}).get("day_title", "Daily Schedule")
    return templates.TemplateResponse("schedule_list.html", ctx(request, title=title, selected_day=selected_day, jobs=visible_jobs))

@app.get("/schedule/week", response_class=HTMLResponse)
def schedule_week(request: Request):
    u = require_login(request)
    if not u: return login_redirect()
    start = date.today(); end = start + timedelta(days=7)
    jobs = []
    for j in jobs_for_user(u):
        ds = schedule_date(j)
        try:
            d = date.fromisoformat(ds)
            if start <= d <= end: jobs.append(j)
        except Exception: pass
    design = design_settings()
    title = design.get("schedule", {}).get("week_title", "Weekly Schedule")
    return templates.TemplateResponse("schedule_list.html", ctx(request, title=title, jobs=jobs))


@app.get("/photos", response_class=HTMLResponse)
def photos(request: Request):
    u = require_login(request)
    if not u: return login_redirect()
    return templates.TemplateResponse("photos.html", ctx(request, photos=photos_for_user(u), jobs=jobs_for_user(u), properties=properties_for_user(u)))

@app.post("/photos/add")
async def photos_add(request: Request, job_id: int = Form(0), property_id: int = Form(0), photo_type: str = Form("Progress"), title: str = Form("Photo"), date_str: str = Form(""), notes: str = Form(""), photo_files: list[UploadFile] = File(None)):
    u = require_login(request)
    if not u: return login_redirect()
    if is_client(u): return RedirectResponse("/jarvis", status_code=303)
    prop = one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,)) if property_id else None
    job = one("SELECT * FROM poolops2_jobs WHERE id=?", (job_id,)) if job_id else None
    client = (prop or job or {}).get("client", "")
    for f in (photo_files or []):
        url = await save_upload(f)
        if url:
            exec_sql("INSERT INTO poolops2_photo_logs (job_id,property_id,client,photo_type,title,photo_url,date,notes) VALUES (?,?,?,?,?,?,?,?)", (job_id or None, property_id or None, client, photo_type, title, url, date_str or date.today().isoformat(), notes))
    return RedirectResponse("/photos", status_code=303)


@app.post("/photos/{photo_id}/delete")
def photo_delete(request: Request, photo_id: int):
    if not is_admin(require_login(request)):
        return login_redirect()

    ph = one("SELECT * FROM poolops2_photo_logs WHERE id=?", (photo_id,))
    if ph:
        _safe_delete_upload(ph.get("photo_url", ""))
        _try_exec("DELETE FROM poolops2_photo_logs WHERE id=?", (photo_id,))
    return RedirectResponse("/photos", status_code=303)


@app.get("/crew", response_class=HTMLResponse)
def crew(request: Request):
    u = require_login(request)
    if not u: return login_redirect()
    if not is_admin(u): return admin_redirect(u)
    return templates.TemplateResponse("crew.html", ctx(request, employees=rows("SELECT * FROM poolops2_employees ORDER BY name")))

@app.post("/crew/new")
def crew_new(request: Request, name: str = Form("New Employee"), role: str = Form("Crew"), phone: str = Form(""), email: str = Form(""), username: str = Form(""), password: str = Form("")):
    u = require_login(request)
    if not is_admin(u): return login_redirect()
    eid = exec_sql("INSERT INTO poolops2_employees (name,role,phone,email,username,password,active) VALUES (?,?,?,?,?,?,?)", (name.strip() or "New Employee", role.strip() or "Crew", phone, email, username or name.strip().lower().replace(" ", "."), password or "1234", True if USE_POSTGRES else 1))
    return RedirectResponse("/crew", status_code=303)

@app.post("/crew/{emp_id}/delete")
def crew_delete(request: Request, emp_id: int):
    u = require_login(request)
    if not is_admin(u): return login_redirect()
    _try_exec("DELETE FROM poolops2_employees WHERE id=?", (emp_id,))
    return RedirectResponse("/crew", status_code=303)

@app.post("/crew/{emp_id}/save")
def crew_save(
    request: Request,
    emp_id: int,
    name: str = Form(""),
    role: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    active: str = Form("1"),
):
    if not is_admin(require_login(request)):
        return login_redirect()

    # Render/Postgres stores active as a real boolean in some deployments,
    # while the old local SQLite build used 1/0. Passing integer 1 into a
    # Postgres boolean column can throw a save error, so normalize it here.
    active_value = str(active).strip().lower() in ("1", "true", "yes", "on", "active")

    # Some live employee tables were created before username/password existed.
    # Update only columns that are actually present so Crew save never crashes
    # from a schema mismatch.
    cols = set(table_columns("poolops2_employees"))
    updates = []
    values = []
    for col, val in [
        ("name", name),
        ("role", role),
        ("phone", phone),
        ("email", email),
        ("username", username),
        ("password", password),
        ("active", active_value),
    ]:
        if col in cols:
            updates.append(f"{col}=?")
            values.append(val)

    if updates:
        values.append(emp_id)
        exec_sql(f"UPDATE poolops2_employees SET {', '.join(updates)} WHERE id=?", tuple(values))

    return RedirectResponse("/crew", status_code=303)



@app.post("/gps/ping")
def gps_ping(
    request: Request,
    lat: str = Form(""),
    lng: str = Form(""),
    accuracy: str = Form(""),
    speed: str = Form(""),
    heading: str = Form(""),
    source: str = Form("employee_portal"),
    note: str = Form(""),
):
    u = require_login(request)
    if not u:
        return {"ok": False, "error": "not_logged_in"}

    if not (is_employee(u) or is_admin(u)):
        return {"ok": False, "error": "not_allowed"}

    try:
        latitude = float(lat)
        longitude = float(lng)
    except Exception:
        return {"ok": False, "error": "bad_location"}

    def clean_float(value):
        try:
            return float(value) if value not in ("", None) else None
        except Exception:
            return None

    now = datetime.now().isoformat(timespec="seconds")

    exec_sql(
        """
        INSERT INTO employee_location_points
        (employee_id, employee_name, latitude, longitude, accuracy, speed, heading, source, note, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            u.get("id"),
            u.get("name") or u.get("username") or "",
            latitude,
            longitude,
            clean_float(accuracy),
            clean_float(speed),
            clean_float(heading),
            source,
            note,
            now,
        )
    )

    if is_employee(u):
        try:
            exec_sql(
                "UPDATE poolops2_employees SET clock_lat=?, clock_lng=?, last_seen_at=? WHERE id=?",
                (latitude, longitude, now, u.get("id"))
            )
        except Exception:
            pass

    return {"ok": True}


@app.get("/gps/day", response_class=HTMLResponse)
def gps_day(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not is_admin(u):
        return RedirectResponse("/employee", status_code=303)

    today = date.today().isoformat()

    points = rows(
        """
        SELECT * FROM employee_location_points
        WHERE created_at LIKE ?
        ORDER BY employee_name, created_at
        """,
        (f"{today}%",)
    )

    return templates.TemplateResponse(
        "gps_day.html",
        ctx(request, points=points, today=today)
    )

def _gps_distance_feet(lat1, lng1, lat2, lng2):
    """
    Rough distance between two GPS points in feet.
    Good enough for stop detection.
    """
    import math

    try:
        lat1 = float(lat1)
        lng1 = float(lng1)
        lat2 = float(lat2)
        lng2 = float(lng2)
    except Exception:
        return 999999

    earth_radius_feet = 20925524.9

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)

    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius_feet * c


def _parse_gps_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
    except Exception:
        try:
            return datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None


def build_gps_stops(points, radius_feet=150, min_minutes=5):
    """
    Turns raw GPS points into stop groups.

    A stop starts when points stay within radius_feet.
    A stop is kept only if it lasts min_minutes or longer.
    """
    stops = []

    by_employee = {}

    for p in points:
        name = p.get("employee_name") or "Employee"
        by_employee.setdefault(name, []).append(p)

    for employee_name, employee_points in by_employee.items():
        employee_points = sorted(employee_points, key=lambda x: str(x.get("created_at") or ""))

        current = []

        for point in employee_points:
            lat = point.get("latitude")
            lng = point.get("longitude")
            point_time = _parse_gps_time(point.get("created_at"))

            if lat is None or lng is None or not point_time:
                continue

            if not current:
                current = [point]
                continue

            anchor = current[0]
            dist = _gps_distance_feet(anchor.get("latitude"), anchor.get("longitude"), lat, lng)

            if dist <= radius_feet:
                current.append(point)
            else:
                if len(current) >= 2:
                    start_time = _parse_gps_time(current[0].get("created_at"))
                    end_time = _parse_gps_time(current[-1].get("created_at"))

                    if start_time and end_time:
                        minutes = round((end_time - start_time).total_seconds() / 60)

                        if minutes >= min_minutes:
                            avg_lat = sum(float(x.get("latitude")) for x in current if x.get("latitude") is not None) / len(current)
                            avg_lng = sum(float(x.get("longitude")) for x in current if x.get("longitude") is not None) / len(current)

                            stops.append({
                                "employee_name": employee_name,
                                "start_time": start_time,
                                "end_time": end_time,
                                "minutes": minutes,
                                "latitude": avg_lat,
                                "longitude": avg_lng,
                                "point_count": len(current),
                            })

                current = [point]

        if len(current) >= 2:
            start_time = _parse_gps_time(current[0].get("created_at"))
            end_time = _parse_gps_time(current[-1].get("created_at"))

            if start_time and end_time:
                minutes = round((end_time - start_time).total_seconds() / 60)

                if minutes >= min_minutes:
                    avg_lat = sum(float(x.get("latitude")) for x in current if x.get("latitude") is not None) / len(current)
                    avg_lng = sum(float(x.get("longitude")) for x in current if x.get("longitude") is not None) / len(current)

                    stops.append({
                        "employee_name": employee_name,
                        "start_time": start_time,
                        "end_time": end_time,
                        "minutes": minutes,
                        "latitude": avg_lat,
                        "longitude": avg_lng,
                        "point_count": len(current),
                    })

    return stops


@app.get("/gps/stops", response_class=HTMLResponse)
def gps_stops(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not is_admin(u):
        return RedirectResponse("/employee", status_code=303)

    today = date.today().isoformat()

    points = rows(
        """
        SELECT * FROM employee_location_points
        WHERE created_at LIKE ?
        ORDER BY employee_name, created_at
        """,
        (f"{today}%",)
    )

    stops = build_gps_stops(points, radius_feet=150, min_minutes=5)

    return templates.TemplateResponse(
        "gps_stops.html",
        ctx(
            request,
            today=today,
            stops=stops,
            points=points,
        )
    )

@app.get("/employee", response_class=HTMLResponse)
def employee_portal(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if is_client(u):
        return RedirectResponse("/jarvis", status_code=303)

    employee = None

    if is_employee(u):
        employee = one(
            "SELECT * FROM poolops2_employees WHERE id=?",
            (u.get("id"),)
        )

    return templates.TemplateResponse(
        "employee_portal.html",
        ctx(
            request,
            employee=employee,
            jobs=jobs_for_user(u),
            photos=photos_for_user(u)
        )
    )

@app.post("/employee/profile")
def employee_profile_save(request: Request, name: str = Form(""), phone: str = Form(""), email: str = Form(""), username: str = Form(""), password: str = Form("")):
    u = require_login(request)
    if not u: return login_redirect()
    if not is_employee(u): return admin_redirect(u)
    exec_sql("UPDATE poolops2_employees SET name=?, phone=?, email=?, username=?, password=? WHERE id=?", (name, phone, email, username, password, u.get("id")))
    u.update({"name": name, "username": username})
    request.session["user"] = u
    

@app.post("/employee/clock")
def employee_clock(request: Request, action: str = Form("in"), lat: str = Form(""), lng: str = Form("")):
    u = require_login(request)
    if not u or not is_employee(u):
        return login_redirect()

    now = datetime.now().isoformat(timespec="minutes")
    clocked = action == "in"

    exec_sql(
        "UPDATE poolops2_employees SET clocked_in=?, clock_lat=?, clock_lng=?, clocked_in_at=?, last_seen_at=? WHERE id=?",
        (
            clocked,
            float(lat) if lat else None,
            float(lng) if lng else None,
            now if clocked else "",
            now,
            u.get("id")
        )
    )

    return RedirectResponse("/employee", status_code=303)

@app.get("/client-portal", response_class=HTMLResponse)
def client_portal(request: Request):
    u = require_login(request)
    if not u: return login_redirect()
    if not is_client(u) and not is_admin(u):
        return RedirectResponse("/jarvis", status_code=303)
    client = one("SELECT * FROM poolops2_clients WHERE id=?", (u.get("id"),)) if is_client(u) else None
    if is_admin(u) and not client:
        # Admin can preview a generic client portal with no destructive access.
        client = rows("SELECT * FROM poolops2_clients ORDER BY name LIMIT 1")
        client = client[0] if client else None
    cname = client.get("name") if client else ""
    cid = client.get("id") if client else 0
    props = rows("SELECT * FROM poolops2_properties WHERE client_id=? OR client=? ORDER BY address", (cid, cname))
    photos = rows("SELECT * FROM poolops2_photo_logs WHERE client=? ORDER BY id DESC", (cname,))
    jobs = rows("SELECT * FROM poolops2_jobs WHERE client=? ORDER BY id DESC", (cname,))
    return templates.TemplateResponse("client_portal.html", ctx(request, client=client, properties=props, photos=photos, jobs=jobs))


@app.get("/estimates", response_class=HTMLResponse)
def estimates(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    return templates.TemplateResponse(
        "simple_crud.html",
        ctx(
            request,
            title="Estimates",
            table="poolops2_estimates",
            records=rows("SELECT * FROM poolops2_estimates ORDER BY id DESC"),
            fields=["client", "property", "title", "status", "amount", "notes"]
        )
    )

@app.post("/estimates/add")
def estimates_add(request: Request, client: str = Form(""), property: str = Form(""), title: str = Form(""), status: str = Form("Draft"), amount: float = Form(0), notes: str = Form("")):
    if not is_admin(require_login(request)): return login_redirect()
    exec_sql("INSERT INTO poolops2_estimates (client,property,title,status,amount,notes,created_at) VALUES (?,?,?,?,?,?,?)", (client, property, title, status, amount, notes, date.today().isoformat()))
    return RedirectResponse("/estimates", status_code=303)

@app.get("/job-costing", response_class=HTMLResponse)
def job_costing(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    return templates.TemplateResponse(
        "job_costing.html",
        ctx(
            request,
            costs=rows("SELECT * FROM poolops2_job_costs ORDER BY id DESC"),
            jobs=rows("SELECT * FROM poolops2_jobs ORDER BY id DESC")
        )
    )

@app.post("/job-costing/add")
def job_costing_add(request: Request, job_id: int = Form(0), client: str = Form(""), labor: float = Form(0), materials: float = Form(0), subs: float = Form(0), equipment: float = Form(0), fuel: float = Form(0), other: float = Form(0), invoice_amount: float = Form(0), notes: str = Form("")):
    if not is_admin(require_login(request)): return login_redirect()
    exec_sql("INSERT INTO poolops2_job_costs (job_id,client,labor,materials,subs,equipment,fuel,other,invoice_amount,notes) VALUES (?,?,?,?,?,?,?,?,?,?)", (job_id, client, labor, materials, subs, equipment, fuel, other, invoice_amount, notes))
    return RedirectResponse("/job-costing", status_code=303)

@app.get("/field-logs", response_class=HTMLResponse)
@app.get("/field-log", response_class=HTMLResponse)
def field_logs(request: Request):
    u = require_login(request)
    if not u: return login_redirect()
    if is_client(u): return RedirectResponse("/jarvis", status_code=303)
    logs = rows("SELECT * FROM field_logs ORDER BY id DESC") if is_admin(u) else rows("SELECT * FROM field_logs WHERE employee_name=? ORDER BY id DESC", (u.get("name", ""),))
    return templates.TemplateResponse("field_logs.html", ctx(request, logs=logs, jobs=jobs_for_user(u)))

@app.post("/field-logs/add")
def field_logs_add(request: Request, employee_name: str = Form(""), client: str = Form(""), property: str = Form(""), address: str = Form(""), date_str: str = Form(""), total_hours: float = Form(0), tools_used: str = Form(""), materials_used: str = Form(""), equipment_used: str = Form(""), work_completed: str = Form(""), issues: str = Form(""), next_steps: str = Form(""), weather: str = Form(""), latitude: str = Form(""), longitude: str = Form("")):
    u = require_login(request)
    if not u: return login_redirect()
    if is_client(u): return RedirectResponse("/jarvis", status_code=303)
    emp_name = employee_name if is_admin(u) else u.get("name", "")
    exec_sql("INSERT INTO field_logs (employee_name,client,property,address,date,total_hours,tools_used,materials_used,equipment_used,work_completed,issues,next_steps,weather,latitude,longitude,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (emp_name, client, property, address, date_str or date.today().isoformat(), total_hours, tools_used, materials_used, equipment_used, work_completed, issues, next_steps, weather, float(latitude) if latitude else None, float(longitude) if longitude else None, datetime.now().isoformat()))
    return RedirectResponse("/field-logs", status_code=303)

@app.get("/freeze-watch", response_class=HTMLResponse)
def freeze_watch_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/weather", status_code=303)


@app.get("/weather-watch", response_class=HTMLResponse)
def weather_watch_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/weather", status_code=303)

@app.get("/quickbooks", response_class=HTMLResponse)
def quickbooks(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    return templates.TemplateResponse("quickbooks.html", ctx(request))

@app.get("/quickbooks/invoices/import", response_class=HTMLResponse)
def quickbooks_invoice_import_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not is_admin(u):
        return RedirectResponse("/jarvis", status_code=303)

    return templates.TemplateResponse(
        "quickbooks_invoice_import.html",
        ctx(request, imported=None, skipped=None, errors=None)
    )


@app.post("/quickbooks/invoices/import", response_class=HTMLResponse)
async def quickbooks_invoice_import(
    request: Request,
    csv_file: UploadFile = File(None),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not is_admin(u):
        return RedirectResponse("/jarvis", status_code=303)

    imported = []
    skipped = []
    errors = []

    if not csv_file or not csv_file.filename:
        return templates.TemplateResponse(
            "quickbooks_invoice_import.html",
            ctx(request, imported=[], skipped=[], errors=["No CSV file uploaded."])
        )

    try:
        raw = await csv_file.read()
        text = raw.decode("utf-8-sig")
        raw_rows = list(csv.reader(io.StringIO(text)))
        header_aliases = {
            "Date": ["date"],
            "Transaction type": ["transaction type", "transaction", "transactio"],
            "Num": ["num", "number", "invoice number"],
            "Name": ["name", "customer", "client"],
            "Memo": ["memo"],
            "Due date": ["due date", "duedate"],
            "Amount": ["amount"],
            "Open balance": ["open balance", "openbalance", "balance"],
        }
        header_index = None

        def clean_header(value):
            return " ".join(str(value or "").strip().lower().split())

        def canonical_header(value):
            cleaned_value = clean_header(value)
            compact_value = cleaned_value.replace(" ", "")
            for canonical, aliases in header_aliases.items():
                for alias in aliases:
                    if cleaned_value == alias or compact_value == alias.replace(" ", ""):
                        return canonical
            return str(value or "").strip()

        for idx, raw_row in enumerate(raw_rows):
            canonical_cells = {canonical_header(cell) for cell in raw_row}
            if all(header in canonical_cells for header in header_aliases):
                header_index = idx
                break

        if header_index is None:
            errors.append("Could not find the QuickBooks invoice header row. Expected: Date, Transaction type, Num, Name, Memo, Due date, Amount, Open balance.")
            return templates.TemplateResponse(
                "quickbooks_invoice_import.html",
                ctx(request, imported=imported, skipped=skipped, errors=errors)
            )

        def csv_value(row, name):
            return (row.get(name) or "").strip()

        def money_value(value):
            cleaned = str(value or "").strip()
            if not cleaned:
                return 0.0
            negative = cleaned.startswith("(") and cleaned.endswith(")")
            cleaned = cleaned.replace("$", "").replace(",", "").replace("(", "").replace(")", "")
            try:
                amount = float(cleaned)
            except Exception:
                amount = 0.0
            return -amount if negative else amount

        for index, row in enumerate(raw_rows[header_index + 1:], start=header_index + 2):
            try:
                row = {canonical_header(raw_rows[header_index][i]): (row[i] if i < len(row) else "") for i in range(len(raw_rows[header_index]))}
                invoice_date = csv_value(row, "Date")
                transaction_type = csv_value(row, "Transaction type")
                invoice_number = csv_value(row, "Num")
                client = csv_value(row, "Name")
                memo = csv_value(row, "Memo")
                due_date = csv_value(row, "Due date")
                amount_raw = csv_value(row, "Amount")
                open_balance_raw = csv_value(row, "Open balance")

                row_text = " ".join(str(v or "").strip() for v in row.values()).strip()
                if not row_text:
                    continue

                if any(str(v or "").strip().upper() == "TOTAL" for v in row.values()):
                    skipped.append(f"Row {index}: TOTAL row skipped.")
                    continue

                if transaction_type.lower() != "invoice":
                    continue

                amount = money_value(amount_raw)
                open_balance = money_value(open_balance_raw)
                status = "Paid" if open_balance == 0 else "Open"

                invoice_description = memo or f"QuickBooks Invoice {invoice_number}".strip()

                notes_parts = []
                notes_parts.append("Imported from QuickBooks Invoice List CSV")

                if invoice_number:
                    notes_parts.append(f"Invoice #: {invoice_number}")
                if due_date:
                    notes_parts.append(f"Due Date: {due_date}")
                if memo:
                    notes_parts.append(f"Memo: {memo}")

                notes = " | ".join(notes_parts)

                existing = None
                if invoice_number:
                    existing = one(
                        "SELECT id FROM poolops2_invoices WHERE qb_invoice_number=? AND source=?",
                        (invoice_number, "QuickBooks Invoice List CSV")
                    )
                if not existing:
                    existing = one(
                        """
                        SELECT id FROM poolops2_invoices
                        WHERE client=?
                          AND description=?
                          AND amount=?
                          AND date=?
                          AND source=?
                        """,
                        (client, invoice_description, amount, invoice_date, "QuickBooks Invoice List CSV")
                    )

                if existing:
                    exec_sql(
                        """
                        UPDATE poolops2_invoices
                        SET client=?, description=?, amount=?, status=?, date=?, notes=?,
                            qb_invoice_number=?, due_date=?, open_balance=?, source=?
                        WHERE id=?
                        """,
                        (
                            client,
                            invoice_description,
                            amount,
                            status,
                            invoice_date,
                            notes,
                            invoice_number,
                            due_date,
                            open_balance,
                            "QuickBooks Invoice List CSV",
                            existing["id"],
                        )
                    )
                    imported.append(f"Row {index}: updated {client} invoice {invoice_number or existing['id']} - {status}.")
                    continue

                exec_sql(
                    """
                    INSERT INTO poolops2_invoices
                    (job_id, client, description, amount, status, date, notes, qb_invoice_number, due_date, open_balance, source)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        None,
                        client,
                        invoice_description,
                        amount,
                        status,
                        invoice_date,
                        notes,
                        invoice_number,
                        due_date,
                        open_balance,
                        "QuickBooks Invoice List CSV",
                    )
                )

                imported.append(f"Row {index}: imported {client} — ${amount:,.2f}")

            except Exception as row_error:
                errors.append(f"Row {index}: {row_error}")

    except Exception as e:
        errors.append(str(e))

    return templates.TemplateResponse(
        "quickbooks_invoice_import.html",
        ctx(request, imported=imported, skipped=skipped, errors=errors)
    )

@app.get("/billing", response_class=HTMLResponse)
def billing_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    invoice_rows = rows(
        """
        SELECT *
        FROM poolops2_invoices
        ORDER BY date DESC, id DESC
        LIMIT 1000
        """
    )

    summary = one(
        """
        SELECT
            COALESCE(SUM(amount), 0) AS total_billed,
            COALESCE(SUM(CASE WHEN status='Paid' THEN amount ELSE 0 END), 0) AS paid_total,
            COALESCE(SUM(open_balance), 0) AS open_total,
            COUNT(*) AS invoice_count
        FROM poolops2_invoices
        """
    )

    return templates.TemplateResponse(
        "billing.html",
        ctx(
            request,
            invoices=invoice_rows,
            records=invoice_rows,
            items=invoice_rows,
            total_billed=(summary.get("total_billed", 0) if summary else 0),
            paid_total=(summary.get("paid_total", 0) if summary else 0),
            open_total=(summary.get("open_total", 0) if summary else 0),
            invoice_count=(summary.get("invoice_count", 0) if summary else 0),
        )
    )

@app.get("/weather", response_class=HTMLResponse)
def weather(request: Request):
    if not require_login(request): return login_redirect()
    return templates.TemplateResponse("weather.html", ctx(request))

@app.get("/contact-us", response_class=HTMLResponse)
def contact_us(request: Request):
    if not require_login(request): return login_redirect()
    return templates.TemplateResponse("contact_us.html", ctx(request))

@app.get("/map", response_class=HTMLResponse)
def map_page(request: Request):
    u = require_login(request)
    if not u: return login_redirect()
    employees = rows("SELECT * FROM poolops2_employees WHERE clocked_in=?", (True if USE_POSTGRES else 1,)) if is_admin(u) else []
    return templates.TemplateResponse("map.html", ctx(request, properties=properties_for_user(u), employees=employees))

@app.get("/invisible-office", response_class=HTMLResponse)
def invisible_office(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    items = rows("SELECT * FROM invisible_office_items ORDER BY id DESC")

    return templates.TemplateResponse(
        "invisible_office.html",
        ctx(request, items=items)
    )


@app.post("/invisible-office/add")
def invisible_office_add(
    request: Request,
    note: str = Form(""),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    text = note.strip()
    if text:
        save_invisible_office_item(
            request=request,
            body=text,
            source="manual",
        )

    return RedirectResponse("/invisible-office", status_code=303)


@app.post("/invisible-office/{item_id}/delete")
def invisible_office_delete(request: Request, item_id: int):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not is_admin(u):
        return RedirectResponse("/invisible-office", status_code=303)

    exec_sql("DELETE FROM invisible_office_items WHERE id=?", (item_id,))

    return RedirectResponse("/invisible-office", status_code=303)


@app.post("/invisible-office/note")
def invisible_office_note(request: Request, note: str = Form("")):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)
    if note.strip():
        save_invisible_office_item(
            request=request,
            body=note.strip(),
            source="manual",
        )
    return RedirectResponse("/invisible-office", status_code=303)

@app.get("/invisible-office/search", response_class=HTMLResponse)
def invisible_office_search(request: Request, q: str = ""):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return admin_redirect(user)

    q = (q or "").strip()
    results = []

    def get_tables():
        try:
            return [r.get("name") for r in rows("SELECT name FROM sqlite_master WHERE type='table'") if r.get("name")]
        except Exception:
            return []

    def get_cols(table):
        try:
            return [r.get("name") for r in rows(f"PRAGMA table_info({table})") if r.get("name")]
        except Exception:
            return []

    def find_table(*keys):
        for t in get_tables():
            low = t.lower()
            if all(k.lower() in low for k in keys):
                return t
        return None

    def title_for(row, cols):
        for combo in [
            ["client_name"], ["property_name"], ["name"], ["contact_name"],
            ["address"], ["job_name"], ["title"], ["description"]
        ]:
            vals = [str(row.get(c) or "") for c in combo if c in cols and row.get(c)]
            if vals:
                return " ".join(vals)
        return "Record"

    def detail_for(row, cols):
        preferred = ["address", "city", "state", "zip", "phone", "email", "job_type", "status", "date", "scheduled_date", "notes", "description"]
        out = []
        for c in preferred:
            if c in cols and row.get(c):
                val = str(row.get(c))
                if len(val) > 120:
                    val = val[:120] + "..."
                out.append(val)
            if len(out) >= 5:
                break
        return " | ".join(out)

    def kind_for(table):
        t = table.lower()
        if "propert" in t:
            return "Property"
        if "client" in t:
            return "Client"
        if "job" in t:
            return "Job"
        if "photo" in t:
            return "Photo"
        if "field" in t:
            return "Field Log"
        if "employee" in t or "crew" in t:
            return "Crew"
        if "estimate" in t:
            return "Estimate"
        if "cost" in t:
            return "Job Cost"
        if "invoice" in t or "quickbook" in t:
            return "Billing"
        return table

    def url_for(table, row):
        rid = row.get("id") or ""
        t = table.lower()
        if "propert" in t:
            return f"/properties/{rid}" if rid else "/properties"
        if "client" in t:
            return f"/clients/{rid}" if rid else "/clients"
        if "job" in t:
            return f"/jobs/{rid}" if rid else "/jobs"
        if "photo" in t:
            return "/photos"
        if "field" in t:
            return "/field-logs"
        if "employee" in t or "crew" in t:
            return "/crew"
        if "estimate" in t:
            return "/estimates"
        if "cost" in t:
            return "/job-costing"
        if "invoice" in t or "quickbook" in t:
            return "/quickbooks"
        return "/invisible-office"

    def add_result(kind, title, detail, url, badge=""):
        results.append({"kind": kind, "title": title, "detail": detail, "url": url, "badge": badge})

    def search_table(table, q, limit=25):
        cols = get_cols(table)
        search_cols = [c for c in cols if c.lower() not in ["id"]]
        if not search_cols:
            return []
        where = " OR ".join([f"CAST({c} AS TEXT) LIKE ?" for c in search_cols])
        try:
            return rows(f"SELECT * FROM {table} WHERE {where} LIMIT {limit}", tuple([f"%{q}%"] * len(search_cols)))
        except Exception:
            return []

    if q:
        tables = get_tables()
        property_table = find_table("propert")
        client_table = find_table("client")
        job_table = find_table("job")
        photo_table = find_table("photo")
        field_table = find_table("field")

        matched_properties = []

        # First, prioritize property cards because property is the center of the system.
        if property_table:
            pcols = get_cols(property_table)
            for p in search_table(property_table, q, 20):
                matched_properties.append(p)
                title = title_for(p, pcols)
                detail = detail_for(p, pcols)
                add_result("Property Card", title, detail, url_for(property_table, p), "Open Property Brain")

                # Pull related jobs by property_id, client_id, property name, or address if possible.
                if job_table:
                    jcols = get_cols(job_table)
                    clauses = []
                    params = []
                    if "property_id" in jcols and p.get("id"):
                        clauses.append("CAST(property_id AS TEXT)=?")
                        params.append(str(p.get("id")))
                    if "client_id" in jcols and p.get("client_id"):
                        clauses.append("CAST(client_id AS TEXT)=?")
                        params.append(str(p.get("client_id")))
                    for key in ["property_name", "name", "address"]:
                        if key in pcols and p.get(key):
                            for jc in ["property_name", "client_name", "description", "notes", "address"]:
                                if jc in jcols:
                                    clauses.append(f"CAST({jc} AS TEXT) LIKE ?")
                                    params.append(f"%{p.get(key)}%")
                    if clauses:
                        try:
                            for j in rows(f"SELECT * FROM {job_table} WHERE {' OR '.join(clauses)} LIMIT 8", tuple(params)):
                                add_result("Related Job", title_for(j, jcols), detail_for(j, jcols), url_for(job_table, j), "Linked to Property")
                        except Exception:
                            pass

                # Pull related photos by property_id or property text.
                if photo_table:
                    phcols = get_cols(photo_table)
                    clauses = []
                    params = []
                    if "property_id" in phcols and p.get("id"):
                        clauses.append("CAST(property_id AS TEXT)=?")
                        params.append(str(p.get("id")))
                    for key in ["property_name", "name", "address"]:
                        if key in pcols and p.get(key):
                            for pc in ["property_name", "caption", "description", "notes", "filename", "path"]:
                                if pc in phcols:
                                    clauses.append(f"CAST({pc} AS TEXT) LIKE ?")
                                    params.append(f"%{p.get(key)}%")
                    if clauses:
                        try:
                            for ph in rows(f"SELECT * FROM {photo_table} WHERE {' OR '.join(clauses)} LIMIT 8", tuple(params)):
                                add_result("Related Photo", title_for(ph, phcols), detail_for(ph, phcols), url_for(photo_table, ph), "Photo Memory")
                        except Exception:
                            pass

                # Pull related field logs.
                if field_table:
                    fcols = get_cols(field_table)
                    clauses = []
                    params = []
                    if "property_id" in fcols and p.get("id"):
                        clauses.append("CAST(property_id AS TEXT)=?")
                        params.append(str(p.get("id")))
                    for key in ["property_name", "name", "address"]:
                        if key in pcols and p.get(key):
                            for fc in ["property_name", "client_name", "notes", "description", "work_performed"]:
                                if fc in fcols:
                                    clauses.append(f"CAST({fc} AS TEXT) LIKE ?")
                                    params.append(f"%{p.get(key)}%")
                    if clauses:
                        try:
                            for fl in rows(f"SELECT * FROM {field_table} WHERE {' OR '.join(clauses)} LIMIT 8", tuple(params)):
                                add_result("Related Field Log", title_for(fl, fcols), detail_for(fl, fcols), url_for(field_table, fl), "Field Memory")
                        except Exception:
                            pass

        # Then do a broad fallback search across operational tables.
        for table in tables:
            if not any(k in table.lower() for k in ["client", "propert", "job", "photo", "field", "employee", "crew", "estimate", "cost", "invoice", "quickbook", "office_note"]):
                continue
            cols = get_cols(table)
            for row in search_table(table, q, 12):
                add_result(kind_for(table), title_for(row, cols), detail_for(row, cols), url_for(table, row), "Search Match")
            if len(results) >= 75:
                break

        # De-duplicate by kind/title/detail/url.
        seen = set()
        clean = []
        for r in results:
            key = (r.get("kind"), r.get("title"), r.get("detail"), r.get("url"))
            if key not in seen:
                clean.append(r)
                seen.add(key)
        results = clean[:75]

    try:
        notes = rows("SELECT * FROM poolops2_office_notes ORDER BY id DESC LIMIT 25")
    except Exception:
        notes = []

    return templates.TemplateResponse("invisible_office.html", {
        "request": request,
        "user": user,
        "theme": theme(),
        "notes": notes,
        "q": q,
        "results": results,
        "title": "Invisible Office"
    })

 
