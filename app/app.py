from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
from datetime import datetime, date, timedelta
from app.routes import pool_monitoring, timeclock
from app.routes.auth import (
    current_user,
    require_login,
    is_admin,
    is_client,
    is_employee,
    login_redirect,
    admin_redirect,
)
import calendar
import json
import os
import shutil
import sqlite3
import uuid
import boto3
import csv
import io
import re
import html
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
# app.include_router(timeclock.router)

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
        "poolops2_users": [("active", "BOOLEAN DEFAULT true" if USE_POSTGRES else "INTEGER DEFAULT 1")],
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
    ensure_legacy_schema()
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


# Auth helpers live in app/routes/auth.py for Core 2 route refactor.


def is_office_user(user):
    return user and str(user.get("role", "")).lower().strip() == "office"


def can_accounting(user):
    return is_admin(user) or is_office_user(user)


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


# login_redirect imported from app.routes.auth

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
        "is_office": is_office_user(u),
        **kw,
    }


# Route modules that need ctx/app helpers must be included AFTER ctx exists.
from app.routes import properties
app.include_router(properties.router)

from app.routes import crew
app.include_router(crew.router)

from app.routes import schedule_board
app.include_router(schedule_board.router)


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
  AND lower(coalesce(role,'')) IN
      ('admin','office','crew','employee','client')
        """,
        (username, password)
    )

    if u:
        role = str(u.get("role") or "crew").lower()

        if role == "employee":
            role = "crew"

        request.session["user"] = {
            "id": u["id"],
            "username": u.get("username") or u.get("name") or username,
            "role": role,
            "name": u.get("name") or u.get("username") or username,
        }

        if role == "admin":
            return RedirectResponse("/jarvis", status_code=303)

        if role == "office":
            return RedirectResponse("/billing", status_code=303)

        if role in ("crew", "employee", "worker"):
            return RedirectResponse("/crew-home", status_code=303)

        if role == "client":
            return RedirectResponse("/client-portal", status_code=303)

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
            return RedirectResponse("/employee", status_code=303)

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
        return RedirectResponse("/employee", status_code=303)

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
        return RedirectResponse("/client-portal", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        ctx(request, error="Login not found. Check the username and password.")
    )

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)



# Dashboard and Command Center routes live in app/routes/dashboard.py

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
    dashboard_card_accounts: str = Form(""),
    dashboard_card_today: str = Form(""),
    dashboard_card_pool_systems: str = Form(""),
    dashboard_card_field_operations: str = Form(""),
    dashboard_card_business: str = Form(""),
    dashboard_card_jarvis: str = Form(""),

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

    data["dashboard_cards"] = {
        "accounts": dashboard_card_accounts.strip(),
        "today": dashboard_card_today.strip(),
        "pool_systems": dashboard_card_pool_systems.strip(),
        "field_operations": dashboard_card_field_operations.strip(),
        "business": dashboard_card_business.strip(),
        "jarvis": dashboard_card_jarvis.strip(),
    }

    save_design_settings(data)

    return RedirectResponse("/design-studio", status_code=303)

# ============================================================
# DASHBOARD CARD IMAGE SETTINGS
# ============================================================

DASHBOARD_CARD_KEYS = [
    "accounts",
    "today",
    "pool_systems",
    "field_operations",
    "business",
    "jarvis",
]


def dashboard_card_defaults():
    return {
        key: {
            "image": "",
            "size": "cover",
            "position": "center",
            "brightness": "0.28",
        }
        for key in DASHBOARD_CARD_KEYS
    }


def normalize_dashboard_cards(design):
    defaults = dashboard_card_defaults()
    existing = design.get("dashboard_cards", {})

    for key in DASHBOARD_CARD_KEYS:
        existing_value = existing.get(key, "")

        if isinstance(existing_value, str):
            defaults[key]["image"] = existing_value.strip()

        elif isinstance(existing_value, dict):
            defaults[key]["image"] = str(existing_value.get("image", "")).strip()
            defaults[key]["size"] = str(existing_value.get("size", "cover")).strip() or "cover"
            defaults[key]["position"] = str(existing_value.get("position", "center")).strip() or "center"
            defaults[key]["brightness"] = str(existing_value.get("brightness", "0.28")).strip() or "0.28"

    return defaults


@app.get("/dashboard-card-images", response_class=HTMLResponse)
def dashboard_card_images_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    design = design_settings()
    dashboard_cards = normalize_dashboard_cards(design)

    return templates.TemplateResponse(
        "dashboard_card_images.html",
        ctx(
            request,
            dashboard_cards=dashboard_cards,
        ),
    )


@app.post("/dashboard-card-images")
async def save_dashboard_card_images(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    form = await request.form()

    design = design_settings()
    dashboard_cards = {}

    for key in DASHBOARD_CARD_KEYS:
        raw_brightness = str(form.get(f"{key}_brightness", "0.28")).strip()

        try:
            brightness = float(raw_brightness)
        except Exception:
            brightness = 0.28

        if brightness < 0:
            brightness = 0

        if brightness > 1:
            brightness = 1

        dashboard_cards[key] = {
            "image": str(form.get(f"{key}_image", "")).strip(),
            "size": str(form.get(f"{key}_size", "cover")).strip() or "cover",
            "position": str(form.get(f"{key}_position", "center")).strip() or "center",
            "brightness": str(brightness),
        }

    design["dashboard_cards"] = dashboard_cards

    DESIGN_FILE.write_text(
        json.dumps(design, indent=2),
        encoding="utf-8",
    )

    return RedirectResponse("/dashboard-card-images", status_code=303)

# ============================================================
# UNIVERSAL PAGE DESIGNER + DESIGN IMAGE UPLOADS
# ============================================================

DESIGN_UPLOAD_DIR = ROOT / "app" / "static" / "design_uploads"
DESIGN_UPLOAD_URL_PREFIX = "/static/design_uploads"

PAGE_DESIGN_KEYS = [
    "dashboard",
    "accounts",
    "today",
    "field_operations",
    "pool_systems",
    "business",
    "jarvis_tools",
    "clients",
    "properties",
    "jobs",
    "billing",
    "photos",
    "schedule",
    "weather",
    "map",
    "employee",
    "pool_monitoring",
    "design_studio",
]


PAGE_DESIGN_LABELS = {
    "dashboard": "Dashboard",
    "accounts": "Accounts",
    "today": "Today",
    "field_operations": "Field Operations",
    "pool_systems": "Pool Systems",
    "business": "Business",
    "jarvis_tools": "Jarvis Tools",
    "clients": "Clients",
    "properties": "Properties",
    "jobs": "Jobs",
    "billing": "Billing",
    "photos": "Photos",
    "schedule": "Schedule",
    "weather": "Weather",
    "map": "Map",
    "employee": "Employee / Clock",
    "pool_monitoring": "Pool Monitoring",
    "design_studio": "Design Studio",
}


def page_design_defaults():
    return {
        "background_image": "",
        "background_size": "cover",
        "background_position": "center",
        "background_brightness": "0.28",
        "page_overlay": "0.55",
        "card_opacity": "0.08",
        "card_radius": "26px",
        "title_size": "clamp(44px, 8vw, 88px)",
        "top_space": "28px",
        "button_height": "48px",
    }


def normalize_page_design(design):
    if not isinstance(design, dict):
        design = {}

    pages = design.get("pages", {})
    if not isinstance(pages, dict):
        pages = {}

    defaults = {}

    for key in PAGE_DESIGN_KEYS:
        existing = pages.get(key, {})
        if not isinstance(existing, dict):
            existing = {}

        page = page_design_defaults()

        for setting_key, default_value in page.items():
            page[setting_key] = str(existing.get(setting_key, default_value)).strip() or default_value

        defaults[key] = page

    design["pages"] = defaults
    return defaults


def clean_uploaded_filename(filename):
    name = Path(filename or "upload").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")

    if not name:
        name = "upload.jpg"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{name}"


@app.get("/design-upload", response_class=HTMLResponse)
def design_upload_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    DESIGN_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    uploaded_files = []

    for path in sorted(DESIGN_UPLOAD_DIR.glob("*"), reverse=True):
        if path.is_file():
            uploaded_files.append(
                {
                    "name": path.name,
                    "url": f"{DESIGN_UPLOAD_URL_PREFIX}/{path.name}",
                }
            )

    return templates.TemplateResponse(
        "design_upload.html",
        ctx(
            request,
            uploaded_files=uploaded_files,
        ),
    )


@app.post("/design-upload")
async def save_design_upload(request: Request, image: UploadFile = File(...)):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    DESIGN_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    filename = clean_uploaded_filename(image.filename)
    destination = DESIGN_UPLOAD_DIR / filename

    with destination.open("wb") as out_file:
        shutil.copyfileobj(image.file, out_file)

    return RedirectResponse("/design-upload", status_code=303)


@app.get("/page-designer", response_class=HTMLResponse)
def page_designer_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    design = design_settings()
    pages = normalize_page_design(design)

    return templates.TemplateResponse(
        "page_designer.html",
        ctx(
            request,
            pages=pages,
            page_labels=PAGE_DESIGN_LABELS,
            page_keys=PAGE_DESIGN_KEYS,
        ),
    )


@app.post("/page-designer")
async def save_page_designer(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    form = await request.form()

    design = design_settings()
    if not isinstance(design, dict):
        design = {}

    pages = normalize_page_design(design)

    for page_key in PAGE_DESIGN_KEYS:
        page = pages.get(page_key, page_design_defaults())

        for setting_key, default_value in page_design_defaults().items():
            form_key = f"{page_key}_{setting_key}"
            page[setting_key] = str(form.get(form_key, page.get(setting_key, default_value))).strip() or default_value

        pages[page_key] = page

    design["pages"] = pages

    DESIGN_FILE.write_text(
        json.dumps(design, indent=2),
        encoding="utf-8",
    )

    return RedirectResponse("/page-designer", status_code=303)

# ============================================================
# DASHBOARD CARD IMAGE SETTINGS
# ============================================================

DASHBOARD_CARD_KEYS = [
    "accounts",
    "today",
    "pool_systems",
    "field_operations",
    "business",
    "jarvis",
]


def dashboard_card_defaults():
    return {
        key: {
            "image": "",
            "size": "cover",
            "position": "center",
            "brightness": "0.28",
        }
        for key in DASHBOARD_CARD_KEYS
    }


def normalize_dashboard_cards(design):
    defaults = dashboard_card_defaults()
    existing = design.get("dashboard_cards", {})

    for key in DASHBOARD_CARD_KEYS:
        old_value = existing.get(key, "")

        if isinstance(old_value, str):
            defaults[key]["image"] = old_value
        elif isinstance(old_value, dict):
            defaults[key]["image"] = str(old_value.get("image", "")).strip()
            defaults[key]["size"] = str(old_value.get("size", "cover")).strip() or "cover"
            defaults[key]["position"] = str(old_value.get("position", "center")).strip() or "center"
            defaults[key]["brightness"] = str(old_value.get("brightness", "0.28")).strip() or "0.28"

    design["dashboard_cards"] = defaults
    return defaults


@app.get("/dashboard-card-images", response_class=HTMLResponse)
def dashboard_card_images_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    design = design_settings()
    dashboard_cards = normalize_dashboard_cards(design)

    return templates.TemplateResponse(
        "dashboard_card_images.html",
        ctx(
            request,
            dashboard_cards=dashboard_cards,
        ),
    )


@app.post("/dashboard-card-images")
async def save_dashboard_card_images(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    form = await request.form()
    design = design_settings()

    dashboard_cards = {}

    for key in DASHBOARD_CARD_KEYS:
        brightness_raw = str(form.get(f"{key}_brightness", "0.28")).strip()

        try:
            brightness_value = float(brightness_raw)
        except Exception:
            brightness_value = 0.28

        if brightness_value < 0:
            brightness_value = 0
        if brightness_value > 1:
            brightness_value = 1

        dashboard_cards[key] = {
            "image": str(form.get(f"{key}_image", "")).strip(),
            "size": str(form.get(f"{key}_size", "cover")).strip() or "cover",
            "position": str(form.get(f"{key}_position", "center")).strip() or "center",
            "brightness": str(brightness_value),
        }

    design["dashboard_cards"] = dashboard_cards

    DESIGN_FILE.write_text(json.dumps(design, indent=2), encoding="utf-8")

    return RedirectResponse("/dashboard-card-images", status_code=303)

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





# Client routes live in app/routes/clients.py
from app.routes import clients
app.include_router(clients.router)

@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if is_client(u):
        return RedirectResponse("/client-portal", status_code=303)

    job_rows = jobs_for_user(u)

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

    return RedirectResponse(f"/jobs/{job_id}/legacy", status_code=303)

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
    employee_rows = rows("""
        SELECT *
        FROM poolops2_employees
        WHERE coalesce(name,'') <> ''
        ORDER BY name
    """)
    return templates.TemplateResponse("crew.html", ctx(request, employees=employee_rows))

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
    return RedirectResponse("/employee", status_code=303)


@app.post("/employee/clock")
def employee_clock(request: Request, action: str = Form("in"), lat: str = Form(""), lng: str = Form("")):
    u = require_login(request)

    if not u:
        return login_redirect()

    if not (is_employee(u) or is_admin(u)):
        return login_redirect()

    now = datetime.now().isoformat(timespec="minutes")
    clocked = action == "in"

    employee_id = u.get("id")
    employee_name = u.get("name") or u.get("username") or "Mike"

    if is_admin(u):
        existing = one(
            "SELECT * FROM poolops2_employees WHERE lower(name)=lower(?) OR lower(username)=lower(?) ORDER BY id LIMIT 1",
            (employee_name, u.get("username") or "")
        )

        if not existing:
            employee_id = exec_sql(
                """
                INSERT INTO poolops2_employees
                (name, role, phone, email, username, password, active)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    employee_name,
                    "Admin",
                    "",
                    "",
                    u.get("username") or employee_name.lower().replace(" ", "."),
                    "",
                    True if USE_POSTGRES else 1,
                )
            )
        else:
            employee_id = existing.get("id")

    exec_sql(
        """
        UPDATE poolops2_employees
        SET clocked_in=?,
            clock_lat=?,
            clock_lng=?,
            clocked_in_at=?,
            last_seen_at=?
        WHERE id=?
        """,
        (
            clocked,
            float(lat) if lat else None,
            float(lng) if lng else None,
            now if clocked else "",
            now,
            employee_id,
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



# ============================================================
# HEINLIN LEGACY - LESSONS, STANDARDS, AND JOB KNOWLEDGE
# ============================================================

def ensure_legacy_schema():
    try:
        exec_sql(
            """
            CREATE TABLE IF NOT EXISTS hfo_legacy_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER,
                client TEXT DEFAULT '',
                property TEXT DEFAULT '',
                address TEXT DEFAULT '',
                problem TEXT DEFAULT '',
                cause TEXT DEFAULT '',
                fix TEXT DEFAULT '',
                lesson TEXT DEFAULT '',
                standard_update TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )
            """
        )
    except Exception:
        exec_sql(
            """
            CREATE TABLE IF NOT EXISTS hfo_legacy_lessons (
                id SERIAL PRIMARY KEY,
                job_id INTEGER,
                client TEXT DEFAULT '',
                property TEXT DEFAULT '',
                address TEXT DEFAULT '',
                problem TEXT DEFAULT '',
                cause TEXT DEFAULT '',
                fix TEXT DEFAULT '',
                lesson TEXT DEFAULT '',
                standard_update TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )
            """
        )


def _e(value):
    return html.escape(str(value or ""))


def legacy_shell(title, body, user=None):
    return f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{_e(title)}</title>
        <style>
            body {{ margin:0; font-family:Arial, sans-serif; background:#071017; color:#f5efe2; }}
            .wrap {{ max-width:1180px; margin:0 auto; padding:34px 18px 70px; }}
            .top {{ display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; }}
            h1 {{ margin:0; font-size:clamp(34px, 6vw, 74px); color:#d6b36a; letter-spacing:.04em; text-transform:uppercase; }}
            .sub {{ color:#c9c1b0; font-size:18px; margin:8px 0 24px; }}
            .card {{ background:rgba(255,255,255,.06); border:1px solid rgba(214,179,106,.35); border-radius:22px; padding:18px; margin:16px 0; box-shadow:0 16px 38px rgba(0,0,0,.35); }}
            label {{ display:block; color:#d6b36a; font-weight:700; margin:14px 0 6px; }}
            input, textarea {{ width:100%; box-sizing:border-box; background:#0b1720; color:#fff; border:1px solid rgba(214,179,106,.35); border-radius:14px; padding:12px; font-size:16px; }}
            textarea {{ min-height:110px; }}
            .btn, button {{ display:inline-block; background:#d6b36a; color:#071017; border:none; border-radius:999px; padding:12px 18px; font-weight:800; text-decoration:none; cursor:pointer; margin:4px 6px 4px 0; }}
            .btn.dark {{ background:#10202c; color:#f5efe2; border:1px solid rgba(214,179,106,.45); }}
            .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; }}
            .muted {{ color:#b8ae9d; }}
            .pill {{ display:inline-block; padding:5px 10px; border:1px solid rgba(214,179,106,.5); border-radius:999px; color:#d6b36a; margin:2px; font-size:13px; }}
            .lesson-title {{ font-size:22px; color:#fff; font-weight:800; margin-bottom:6px; }}
        </style>
    </head>
    <body><div class="wrap">{body}</div></body>
    </html>
    """


@app.get("/legacy", response_class=HTMLResponse)
def legacy_library(request: Request, q: str = ""):
    u = require_login(request)
    if not u:
        return login_redirect()
    if is_client(u):
        return RedirectResponse("/client-portal", status_code=303)

    ensure_legacy_schema()
    q = (q or "").strip()

    if q:
        lessons = rows(
            """
            SELECT * FROM hfo_legacy_lessons
            WHERE problem LIKE ? OR cause LIKE ? OR fix LIKE ? OR lesson LIKE ? OR standard_update LIKE ? OR tags LIKE ? OR client LIKE ? OR property LIKE ?
            ORDER BY id DESC
            LIMIT 200
            """,
            tuple([f"%{q}%"] * 8),
        )
    else:
        lessons = rows("SELECT * FROM hfo_legacy_lessons ORDER BY id DESC LIMIT 200")

    cards = []
    for item in lessons:
        tags = "".join(f'<span class="pill">{_e(t.strip())}</span>' for t in str(item.get("tags") or "").split(",") if t.strip())
        job_link = f'<a class="btn dark" href="/jobs/{_e(item.get("job_id"))}">Open Job</a>' if item.get("job_id") else ""
        cards.append(f"""
        <div class="card">
            <div class="lesson-title">{_e(item.get('problem') or 'Legacy Lesson')}</div>
            <div class="muted">{_e(item.get('client'))} • {_e(item.get('property'))} • {_e(item.get('created_at'))}</div>
            <p><b>Cause:</b> {_e(item.get('cause'))}</p>
            <p><b>Fix:</b> {_e(item.get('fix'))}</p>
            <p><b>What we learned:</b> {_e(item.get('lesson'))}</p>
            <p><b>Heinlin Standard:</b> {_e(item.get('standard_update'))}</p>
            <div>{tags}</div>
            <div style="margin-top:12px;">{job_link}</div>
        </div>
        """)

    body = f"""
    <div class="top">
        <div>
            <h1>Heinlin Legacy</h1>
            <div class="sub">Jobs → Photos → Notes → Lessons → Standards. This is the digital apprenticeship system.</div>
        </div>
        <div>
            <a class="btn dark" href="/jarvis">Dashboard</a>
            <a class="btn dark" href="/jobs">Jobs</a>
        </div>
    </div>
    <form method="get" action="/legacy" class="card">
        <label>Search the Heinlin playbook</label>
        <input name="q" value="{_e(q)}" placeholder="heater, IntelliFlo3, concrete, winterize, valve actuator, skimmer leak...">
        <button type="submit">Search Legacy</button>
    </form>
    <div class="grid">
        {''.join(cards) if cards else '<div class="card"><b>No legacy lessons yet.</b><p class="muted">Complete a job, answer what we learned, and this library starts building itself.</p></div>'}
    </div>
    """
    return HTMLResponse(legacy_shell("Heinlin Legacy", body, u))


@app.get("/jobs/{job_id}/legacy", response_class=HTMLResponse)
def job_legacy_review(request: Request, job_id: int):
    u = require_login(request)
    if not u:
        return login_redirect()
    if is_client(u):
        return RedirectResponse("/client-portal", status_code=303)

    ensure_legacy_schema()
    job = one("SELECT * FROM poolops2_jobs WHERE id=?", (job_id,))
    if not job or not employee_can_access_job(u, job):
        return admin_redirect(u)

    existing = rows("SELECT * FROM hfo_legacy_lessons WHERE job_id=? ORDER BY id DESC", (job_id,))
    existing_html = "".join(f"""
        <div class="card">
            <b>{_e(x.get('problem'))}</b>
            <p><b>Lesson:</b> {_e(x.get('lesson'))}</p>
            <p class="muted">Saved by {_e(x.get('created_by'))} at {_e(x.get('created_at'))}</p>
        </div>
    """ for x in existing)

    body = f"""
    <div class="top">
        <div>
            <h1>What Did We Learn?</h1>
            <div class="sub">{_e(job.get('client'))} • {_e(job.get('property'))} • {_e(job.get('address'))}</div>
        </div>
        <div>
            <a class="btn dark" href="/jobs/{job_id}">Back to Job</a>
            <a class="btn dark" href="/legacy">Legacy Library</a>
        </div>
    </div>
    <form class="card" method="post" action="/jobs/{job_id}/legacy">
        <label>Problem found</label>
        <textarea name="problem" placeholder="What was wrong, unusual, risky, expensive, confusing, or important on this job?"></textarea>

        <label>Cause</label>
        <textarea name="cause" placeholder="What caused it? Bad install, freeze damage, poor flow, wiring mistake, settling, corrosion, hidden valve, customer operation, etc."></textarea>

        <label>Fix</label>
        <textarea name="fix" placeholder="Exactly how did Heinlin fix it?"></textarea>

        <label>What did we learn here?</label>
        <textarea name="lesson" placeholder="The lesson future crews need to know before they hit this problem again."></textarea>

        <label>Heinlin Standard / Playbook Update</label>
        <textarea name="standard_update" placeholder="From now on, how should Heinlin handle this situation?"></textarea>

        <label>Tags</label>
        <input name="tags" placeholder="Pentair, heater, relay, winterization, concrete, liner, plumbing">

        <button type="submit">Save to Heinlin Legacy</button>
    </form>
    {existing_html}
    """
    return HTMLResponse(legacy_shell("Legacy Review", body, u))


@app.post("/jobs/{job_id}/legacy")
def job_legacy_save(
    request: Request,
    job_id: int,
    problem: str = Form(""),
    cause: str = Form(""),
    fix: str = Form(""),
    lesson: str = Form(""),
    standard_update: str = Form(""),
    tags: str = Form(""),
):
    u = require_login(request)
    if not u:
        return login_redirect()
    if is_client(u):
        return RedirectResponse("/client-portal", status_code=303)

    ensure_legacy_schema()
    job = one("SELECT * FROM poolops2_jobs WHERE id=?", (job_id,))
    if not job or not employee_can_access_job(u, job):
        return admin_redirect(u)

    exec_sql(
        """
        INSERT INTO hfo_legacy_lessons
        (job_id, client, property, address, problem, cause, fix, lesson, standard_update, tags, created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            job_id,
            job.get("client", ""),
            job.get("property", ""),
            job.get("address", ""),
            problem.strip(),
            cause.strip(),
            fix.strip(),
            lesson.strip(),
            standard_update.strip(),
            tags.strip(),
            u.get("name") or u.get("username") or "",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )

    return RedirectResponse("/legacy", status_code=303)






# ============================================================
# HEINLIN LEGACY COMMAND CENTER - EDITABLE DASHBOARD + PROPERTY BRAIN
# ============================================================


from app.routes import dashboard
app.include_router(dashboard.router)

# Property Brain and remaining legacy routes stay in app.py for this phase.
@app.get("/properties/{property_id}/brain", response_class=HTMLResponse)
@app.get("/property-brain/{property_id}", response_class=HTMLResponse)
def property_brain(request: Request, property_id: int):
    u = require_login(request)
    if not u:
        return login_redirect()

    prop = one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    if not prop or not property_can_access(u, prop):
        return admin_redirect(u)

    cname = prop.get("client", "")
    client = None
    if prop.get("client_id"):
        client = one("SELECT * FROM poolops2_clients WHERE id=?", (prop.get("client_id"),))
    if not client and cname:
        client = one("SELECT * FROM poolops2_clients WHERE name=?", (cname,))

    jobs = rows(
        """
        SELECT * FROM poolops2_jobs
        WHERE address=? OR property=? OR client=?
        ORDER BY id DESC
        """,
        (prop.get("address", ""), prop.get("property_name", ""), cname),
    )
    photos = rows("SELECT * FROM poolops2_photo_logs WHERE property_id=? OR client=? ORDER BY id DESC LIMIT 80", (property_id, cname))
    equipment = rows("SELECT * FROM poolops2_equipment WHERE property_id=? ORDER BY id DESC", (property_id,))

    ensure_legacy_schema()
    lessons = rows(
        """
        SELECT * FROM hfo_legacy_lessons
        WHERE address=? OR property=? OR client=?
        ORDER BY id DESC
        LIMIT 60
        """,
        (prop.get("address", ""), prop.get("property_name", ""), cname),
    )

    return templates.TemplateResponse(
        "property_brain.html",
        ctx(
            request,
            prop=prop,
            client=client,
            jobs=jobs,
            photos=photos,
            equipment=equipment,
            lessons=lessons,
        )
    )


@app.get("/legacy-dashboard", response_class=HTMLResponse)
def legacy_dashboard_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/legacy", status_code=303)

@app.get("/estimates", response_class=HTMLResponse)
def estimates(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not can_accounting(u):
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
    if not can_accounting(u):
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
    if not can_accounting(u):
        return admin_redirect(u)

    return templates.TemplateResponse("quickbooks.html", ctx(request))

@app.get("/quickbooks/invoices/import", response_class=HTMLResponse)
def quickbooks_invoice_import_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not can_accounting(u):
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

    if not can_accounting(u):
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
    if not can_accounting(u):
        return admin_redirect(u)

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
    if not is_admin(u):
        return admin_redirect(u)

    items = rows("SELECT * FROM invisible_office_items ORDER BY id DESC")

    return templates.TemplateResponse(
        "invisible_office.html",
        ctx(request, items=items)
    )

from app.routes import work_engine
app.include_router(work_engine.router)

from app.routes import property_brain
app.include_router(property_brain.router)

from app.routes import client_portal_v2
app.include_router(client_portal_v2.router)

from app.routes import office
app.include_router(office.router)

from app.routes import job_detail_v2
app.include_router(job_detail_v2.router)

from app.routes import mike_mode
app.include_router(mike_mode.router)

from app.routes import jarvis_approval
app.include_router(jarvis_approval.router)

from app.routes import invisible_office_edit
app.include_router(invisible_office_edit.router)

from app.routes import gps_tracking
app.include_router(gps_tracking.router)

from app.routes import account_management
app.include_router(account_management.router)

from app.routes import jarvis_command
app.include_router(jarvis_command.router)


from app.routes import crew_home
app.include_router(crew_home.router)

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




# ============================================================
# JARVIS BRAIN LEVEL 6 COMMAND DESK
# Adds /jarvis-brain/desk without replacing Level 5.
# ============================================================

import os as _j6_os
import json as _j6_json
import html as _j6_html
import hashlib as _j6_hashlib
from datetime import datetime as _j6_datetime, date as _j6_date

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_DESK_VERSION = "level-6-command-desk-2026-07-04"


def _j6_now():
    return _j6_datetime.now().isoformat(timespec="seconds")


def _j6_today():
    return _j6_date.today().isoformat()


def _j6_storage_dir():
    path = _j6_os.path.join(_j6_os.getcwd(), "jarvis_storage")
    _j6_os.makedirs(path, exist_ok=True)
    return path


def _j6_file(name):
    return _j6_os.path.join(_j6_storage_dir(), name)


def _j6_esc(value):
    return _j6_html.escape(str(value or ""))


def _j6_read_jsonl_all(name):
    path = _j6_file(name)
    if not _j6_os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(_j6_json.loads(line))
            except Exception:
                pass
    return items


def _j6_write_jsonl_all(name, items):
    path = _j6_file(name)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(_j6_json.dumps(item, ensure_ascii=False) + "\n")


def _j6_item_id(item):
    base = "|".join([
        str(item.get("created_at") or ""),
        str(item.get("category") or ""),
        str(item.get("title") or ""),
        str(item.get("body") or ""),
    ])
    return _j6_hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _j6_status(item):
    return str(item.get("status") or "Open").strip()


def _j6_is_open(item):
    return _j6_status(item).lower() not in ("done", "closed", "complete", "completed")


def _j6_mark_done(item_id):
    items = _j6_read_jsonl_all("jarvis_memory.jsonl")
    changed = False

    for item in items:
        if _j6_item_id(item) == item_id:
            item["status"] = "Done"
            item["completed_at"] = _j6_now()
            changed = True
            break

    if changed:
        _j6_write_jsonl_all("jarvis_memory.jsonl", items)

    return changed


def _j6_user(request):
    try:
        f = globals().get("current_user")
        if callable(f):
            u = f(request)
            if u:
                return u
    except Exception:
        pass

    try:
        if hasattr(request, "session"):
            return request.session.get("user") or {}
    except Exception:
        pass

    return {}


def _j6_name(user):
    return str((user or {}).get("name") or (user or {}).get("username") or (user or {}).get("email") or "Mike").strip()


def _j6_role(user):
    role = str((user or {}).get("role") or "admin").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j6_rows(sql, params=()):
    try:
        f = globals().get("rows")
        if callable(f):
            return f(sql, params) or []
    except Exception:
        pass
    return []


def _j6_columns(table):
    try:
        f = globals().get("table_columns")
        if callable(f):
            return list(f(table) or [])
    except Exception:
        pass
    return []


def _j6_table_count(table):
    cols = _j6_columns(table)
    if not cols:
        return None
    try:
        r = _j6_rows(f"SELECT COUNT(*) AS c FROM {table}", ())
        if r:
            return r[0].get("c") if hasattr(r[0], "get") else list(r[0])[0]
    except Exception:
        pass
    return None


def _j6_group_items(items):
    groups = {
        "Billing Note": [],
        "Material Needed": [],
        "Follow Up": [],
        "Problem Found": [],
        "Field Log": [],
        "General Note": [],
        "Other": [],
    }

    for item in items:
        cat = str(item.get("category") or "General Note").strip()
        if cat not in groups:
            cat = "Other"
        groups[cat].append(item)

    return groups


def _j6_today_items(items):
    today = _j6_today()
    return [x for x in items if str(x.get("created_at") or "")[:10] == today]


def _j6_render_item(item):
    item_id = _j6_item_id(item)
    cat = _j6_esc(item.get("category"))
    created = _j6_esc(item.get("created_at"))
    title = _j6_esc(item.get("title"))
    body = _j6_esc(item.get("body"))
    priority = _j6_esc(item.get("priority") or "Normal")
    status = _j6_esc(_j6_status(item))

    return f"""
    <div class="desk-item">
      <div class="desk-top">
        <b>{cat}</b>
        <span>{created}</span>
      </div>
      <div class="desk-title">{title}</div>
      <div class="desk-body">{body}</div>
      <div class="desk-meta">Priority: {priority} ? Status: {status}</div>
      <form method="post" action="/jarvis-brain/desk/done">
        <input type="hidden" name="item_id" value="{item_id}">
        <button class="small" type="submit">Mark Done</button>
      </form>
    </div>
    """


def _j6_next_actions(open_items):
    billing = [x for x in open_items if str(x.get("category") or "") == "Billing Note"]
    materials = [x for x in open_items if str(x.get("category") or "") == "Material Needed"]
    followups = [x for x in open_items if str(x.get("category") or "") == "Follow Up"]
    problems = [x for x in open_items if str(x.get("category") or "") == "Problem Found"]
    fields = [x for x in open_items if str(x.get("category") or "") == "Field Log"]

    actions = []

    if billing:
        actions.append(f"Review {len(billing)} billing note(s) before they disappear.")
    if problems:
        actions.append(f"Handle {len(problems)} problem item(s) before they become bigger problems.")
    if materials:
        actions.append(f"Check {len(materials)} material-needed item(s) before the next job run.")
    if followups:
        actions.append(f"Make {len(followups)} follow-up call/text/email item(s).")
    if fields:
        actions.append(f"Review {len(fields)} field log item(s) and make sure the job history is protected.")

    if not actions:
        actions.append("No open Jarvis memory is screaming right now. Keep feeding me job notes, billing notes, and field logs.")

    return actions


@app.get("/jarvis-brain/desk", response_class=HTMLResponse)
def jarvis_brain_level6_command_desk(request: Request):
    user = _j6_user(request)
    name = _j6_name(user).split()[0]
    role = _j6_role(user)

    all_items = _j6_read_jsonl_all("jarvis_memory.jsonl")
    all_items.reverse()

    open_items = [x for x in all_items if _j6_is_open(x)]
    done_items = [x for x in all_items if not _j6_is_open(x)]
    today_items = _j6_today_items(all_items)
    groups = _j6_group_items(open_items)
    next_actions = _j6_next_actions(open_items)

    group_html = ""
    for group_name, items in groups.items():
        if not items:
            continue
        group_html += f"""
        <div class="card">
          <h2>{_j6_esc(group_name)} <span>{len(items)}</span></h2>
          {''.join(_j6_render_item(x) for x in items[:20])}
        </div>
        """

    if not group_html:
        group_html = """
        <div class="card">
          <h2>Open Memory</h2>
          <p>No open Jarvis memory right now.</p>
        </div>
        """

    today_html = ""
    for item in today_items[:12]:
        today_html += _j6_render_item(item)
    if not today_html:
        today_html = "<p>No Jarvis items captured today yet.</p>"

    reports = _j6_read_jsonl_all("jarvis_daily_reports.jsonl")
    reports.reverse()
    report_html = ""
    for report in reports[:5]:
        report_html += f"""
        <div class="desk-item">
          <div class="desk-top"><b>Daily Closeout</b><span>{_j6_esc(report.get('created_at'))}</span></div>
          <div class="desk-body">{_j6_esc(report.get('summary'))}</div>
        </div>
        """
    if not report_html:
        report_html = "<p>No daily closeout reports saved yet. Say: Jarvis, end my day.</p>"

    actions_html = "".join([f"<li>{_j6_esc(x)}</li>" for x in next_actions])

    jobs_count = _j6_table_count("poolops2_jobs")
    office_count = _j6_table_count("invisible_office_items")
    logs_count = _j6_table_count("field_logs")

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis Command Desk</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }}
    .wrap {{ max-width:1250px; margin:0 auto; padding:26px; }}
    .hero {{ background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:24px; box-shadow:0 20px 60px rgba(0,0,0,.45); }}
    h1 {{ margin:0 0 8px; font-size:34px; letter-spacing:.08em; }}
    .sub {{ color:#d9b56d; margin-bottom:20px; }}
    .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:16px 0; }}
    @media(max-width:800px) {{ .stats {{ grid-template-columns:repeat(2,1fr); }} }}
    .stat {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:14px; }}
    .stat b {{ font-size:28px; color:#d9b56d; }}
    .grid {{ display:grid; grid-template-columns:1.05fr .95fr; gap:16px; }}
    @media(max-width:950px) {{ .grid {{ grid-template-columns:1fr; }} }}
    .card {{ background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; margin-top:16px; }}
    .card h2 {{ display:flex; justify-content:space-between; align-items:center; gap:10px; }}
    textarea {{ width:100%; min-height:120px; box-sizing:border-box; border-radius:14px; border:1px solid #6b4b1f; background:#05070b; color:#fff; padding:14px; font-size:16px; }}
    button {{ margin-top:10px; padding:12px 16px; border:0; border-radius:12px; background:#b8873a; color:#111; font-weight:900; cursor:pointer; }}
    button.small {{ padding:8px 11px; font-size:13px; }}
    .reply {{ margin-top:12px; padding:13px; border-radius:12px; background:#05070b; border:1px solid #2d2113; min-height:24px; line-height:1.45; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:9px; margin-top:10px; }}
    .chip {{ border:1px solid #6b4b1f; border-radius:999px; padding:9px 11px; background:#070a0f; color:#f5efe3; cursor:pointer; }}
    .desk-item {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:13px; margin:10px 0; }}
    .desk-top {{ display:flex; justify-content:space-between; gap:12px; color:#d9b56d; font-size:13px; }}
    .desk-title {{ font-weight:900; margin-top:8px; }}
    .desk-body {{ margin-top:8px; color:#e8dcc7; line-height:1.4; }}
    .desk-meta {{ margin-top:9px; color:#a99572; font-size:13px; }}
    a {{ color:#d9a64a; }}
    li {{ margin-bottom:10px; }}
    .result {{ padding:10px; border:1px solid #2d2113; border-radius:12px; margin:8px 0; background:#070a0f; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>J.A.R.V.I.S. COMMAND DESK</h1>
    <div class="sub">Good to go, {_j6_esc(name)}. This is the office brain queue. Role: {_j6_esc(role)}.</div>

    <div class="stats">
      <div class="stat"><b>{len(open_items)}</b><br>Open Jarvis items</div>
      <div class="stat"><b>{len(today_items)}</b><br>Captured today</div>
      <div class="stat"><b>{len(done_items)}</b><br>Completed</div>
      <div class="stat"><b>{len(all_items)}</b><br>Total memory</div>
    </div>

    <div class="grid">
      <div>
        <div class="card">
          <h2>Command</h2>
          <textarea id="cmd" placeholder="Jarvis, add this to billing: "></textarea>
          <br>
          <button onclick="sendCmd()">Send</button>
          <button onclick="startVoice()">?? Voice</button>
          <button onclick="speakLast()">?? Read Back</button>
          <div class="reply" id="reply">Waiting for command.</div>

          <div class="chips">
            <button class="chip" onclick="fillCmd('Jarvis, start my day')">Start Day</button>
            <button class="chip" onclick="fillCmd('Jarvis, end my day')">End Day</button>
            <button class="chip" onclick="fillCmd('Jarvis, what did I do today?')">Today Summary</button>
            <button class="chip" onclick="fillCmd('Jarvis, find ')">Find</button>
            <button class="chip" onclick="fillCmd('Jarvis, add this to billing: ')">Billing</button>
            <button class="chip" onclick="fillCmd('Jarvis, field log: ')">Field Log</button>
            <button class="chip" onclick="fillCmd('Jarvis, material needed: ')">Material</button>
            <button class="chip" onclick="fillCmd('Jarvis, remind me to follow up with ')">Follow Up</button>
          </div>
        </div>

        <div class="card">
          <h2>What Jarvis Thinks Is Next</h2>
          <ul>{actions_html}</ul>
        </div>

        <div class="card">
          <h2>Today?s Captured Items</h2>
          {today_html}
        </div>

        <div class="card">
          <h2>Daily Closeouts</h2>
          {report_html}
        </div>
      </div>

      <div>
        <div class="card">
          <h2>System Links</h2>
          <p>
            <a href="/jarvis-brain">Jarvis Brain</a>
            |
            <a href="/jarvis-brain/install-check">Install Check</a>
            |
            <a href="/jarvis-brain/export.json">Export</a>
            |
            <a href="/invisible-office">Invisible Office</a>
            |
            <a href="/">Home</a>
          </p>
          <p><b>Jobs table:</b> {_j6_esc(jobs_count)}</p>
          <p><b>Invisible Office rows:</b> {_j6_esc(office_count)}</p>
          <p><b>Field Log rows:</b> {_j6_esc(logs_count)}</p>
        </div>

        {group_html}
      </div>
    </div>
  </div>
</div>

<script>
let lastReply = "";

function fillCmd(t){{
  document.getElementById("cmd").value = t;
  document.getElementById("cmd").focus();
}}

function escapeHtml(str){{
  return String(str || "").replace(/[&<>"']/g, function(m){{
    return ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}})[m];
  }});
}}

function speak(text){{
  if(!("speechSynthesis" in window)){{ return; }}
  window.speechSynthesis.cancel();
  const msg = new SpeechSynthesisUtterance(text);
  msg.rate = 1;
  msg.pitch = 1;
  window.speechSynthesis.speak(msg);
}}

function speakLast(){{
  const text = lastReply || document.getElementById("reply").innerText || "Nothing to read back yet.";
  speak(text);
}}

async function sendCmd(){{
  const box = document.getElementById("cmd");
  const reply = document.getElementById("reply");
  const text = box.value.trim();

  if(!text){{
    reply.innerText = "Tell me what needs handled.";
    lastReply = reply.innerText;
    return;
  }}

  reply.innerText = "Handling it...";
  lastReply = reply.innerText;

  try {{
    const res = await fetch("/jarvis-brain/command", {{
      method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{text:text}})
    }});

    const data = await res.json();
    let html = escapeHtml(data.reply || JSON.stringify(data));
    lastReply = data.reply || JSON.stringify(data);

    if(data.links && data.links.length){{
      html += "<br><br><b>Matches:</b>";
      data.links.forEach(function(x){{
        html += '<div class="result"><b>' + escapeHtml(x.kind) + '</b>: ';
        html += '<a href="' + escapeHtml(x.url) + '">' + escapeHtml(x.title) + '</a>';
        if(x.detail){{ html += '<br><small>' + escapeHtml(x.detail) + '</small>'; }}
        html += '</div>';
      }});
    }}

    reply.innerHTML = html;
    speak(lastReply);

    if(data.ok && (!data.links || !data.links.length)){{
      setTimeout(() => window.location.reload(), 1200);
    }}
  }} catch(err) {{
    reply.innerText = "Jarvis command failed: " + err;
    lastReply = reply.innerText;
    speak(lastReply);
  }}
}}

function startVoice(){{
  const reply = document.getElementById("reply");
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){{
    reply.innerText = "Voice is not available in this browser. Use Chrome or Edge.";
    lastReply = reply.innerText;
    speakLast();
    return;
  }}

  const rec = new SR();
  rec.lang = "en-US";
  rec.interimResults = false;
  rec.maxAlternatives = 1;

  reply.innerText = "Listening...";
  lastReply = reply.innerText;
  rec.onresult = function(event){{
    const text = event.results[0][0].transcript;
    document.getElementById("cmd").value = text;
    sendCmd();
  }};
  rec.onerror = function(event){{
    reply.innerText = "Voice error: " + event.error;
    lastReply = reply.innerText;
  }};
  rec.start();
}}
</script>
</body>
</html>
"""
    return HTMLResponse(html)


@app.post("/jarvis-brain/desk/done")
async def jarvis_brain_level6_mark_done(request: Request):
    try:
        form = await request.form()
        item_id = str(form.get("item_id") or "").strip()
    except Exception:
        item_id = ""

    if item_id:
        _j6_mark_done(item_id)

    return RedirectResponse("/jarvis-brain/desk", status_code=303)


@app.get("/jarvis-brain/desk.json")
def jarvis_brain_level6_desk_json():
    all_items = _j6_read_jsonl_all("jarvis_memory.jsonl")
    all_items.reverse()
    open_items = [x for x in all_items if _j6_is_open(x)]
    done_items = [x for x in all_items if not _j6_is_open(x)]
    today_items = _j6_today_items(all_items)

    return JSONResponse({
        "ok": True,
        "version": JARVIS_DESK_VERSION,
        "open_count": len(open_items),
        "done_count": len(done_items),
        "today_count": len(today_items),
        "next_actions": _j6_next_actions(open_items),
        "open_items": open_items[:200],
        "today_items": today_items[:100],
    })


@app.get("/jarvis-brain/command-desk", response_class=HTMLResponse)
def jarvis_brain_level6_command_desk_alias(request: Request):
    return RedirectResponse("/jarvis-brain/desk", status_code=303)

# ============================================================
# END JARVIS BRAIN LEVEL 6 COMMAND DESK
# ============================================================


# ============================================================
# JARVIS BRAIN LAYER - HEINLIN FIELD OPS
# LEVEL 7 JOB CONTEXT MODE
# ============================================================

import os as _j7_os
import re as _j7_re
import json as _j7_json
import html as _j7_html
from datetime import datetime as _j7_datetime, date as _j7_date

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_BRAIN_VERSION = "level-7-job-context-2026-07-04"
JARVIS_TAKEOVER = True


def _j7_now():
    return _j7_datetime.now().isoformat(timespec="seconds")


def _j7_today():
    return _j7_date.today().isoformat()


def _j7_storage_dir():
    path = _j7_os.path.join(_j7_os.getcwd(), "jarvis_storage")
    _j7_os.makedirs(path, exist_ok=True)
    return path


def _j7_file(name):
    return _j7_os.path.join(_j7_storage_dir(), name)


def _j7_write_json(name, data):
    with open(_j7_file(name), "w", encoding="utf-8") as f:
        _j7_json.dump(data, f, ensure_ascii=False, indent=2)


def _j7_read_json(name, default=None):
    path = _j7_file(name)
    if not _j7_os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _j7_json.load(f)
    except Exception:
        return default


def _j7_write_jsonl(name, item):
    item = dict(item or {})
    item.setdefault("created_at", _j7_now())
    with open(_j7_file(name), "a", encoding="utf-8") as f:
        f.write(_j7_json.dumps(item, ensure_ascii=False) + "\n")


def _j7_read_jsonl(name, limit=25):
    path = _j7_file(name)
    if not _j7_os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                items.append(_j7_json.loads(line.strip()))
            except Exception:
                pass
    items.reverse()
    return items[:limit]


def _j7_user(request):
    try:
        f = globals().get("current_user")
        if callable(f):
            u = f(request)
            if u:
                return u
    except Exception:
        pass
    try:
        if hasattr(request, "session"):
            return request.session.get("user") or {}
    except Exception:
        pass
    return {}


def _j7_name(user):
    return str((user or {}).get("name") or (user or {}).get("username") or (user or {}).get("email") or "Mike").strip()


def _j7_email(user):
    return str((user or {}).get("email") or "").strip()


def _j7_role(user):
    role = str((user or {}).get("role") or "admin").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j7_esc(value):
    return _j7_html.escape(str(value or ""))


def _j7_rows(sql, params=()):
    try:
        f = globals().get("rows")
        if callable(f):
            return f(sql, params) or []
    except Exception as exc:
        print("Jarvis rows skipped:", exc)
    return []


def _j7_exec(sql, params=()):
    try:
        f = globals().get("exec_sql")
        if callable(f):
            return f(sql, params)
    except Exception as exc:
        print("Jarvis exec skipped:", exc)
    return None


def _j7_columns(table):
    try:
        f = globals().get("table_columns")
        if callable(f):
            return list(f(table) or [])
    except Exception:
        pass
    return []


def _j7_table_exists(table):
    return bool(_j7_columns(table))


def _j7_insert_existing(table, data):
    cols = _j7_columns(table)
    if not cols:
        return False

    final = {}
    for k, v in data.items():
        if k in cols:
            final[k] = v

    if not final:
        return False

    names = list(final.keys())
    placeholders = ",".join(["?"] * len(names))
    sql = f"INSERT INTO {table} ({','.join(names)}) VALUES ({placeholders})"
    _j7_exec(sql, tuple(final[k] for k in names))
    return True


def _j7_update_existing(table, updates, where_sql, where_params):
    cols = _j7_columns(table)
    if not cols:
        return False

    final = {}
    for k, v in updates.items():
        if k in cols:
            final[k] = v

    if not final:
        return False

    names = list(final.keys())
    set_sql = ", ".join([f"{k}=?" for k in names])
    params = tuple(final[k] for k in names) + tuple(where_params or ())
    _j7_exec(f"UPDATE {table} SET {set_sql} WHERE {where_sql}", params)
    return True


def _j7_classify(text):
    raw = str(text or "").strip()
    low = raw.lower()

    intent = "memory"
    category = "General Note"
    priority = "Normal"

    if any(x in low for x in ["clock me in", "clock in", "start gps"]):
        intent = "clock_in"
        category = "Time Clock"
    elif any(x in low for x in ["clock me out", "clock out"]):
        intent = "clock_out"
        category = "Time Clock"
    elif any(x in low for x in ["set active job", "active job", "i'm at", "im at", "working on", "we are at", "we're at"]):
        intent = "set_context"
        category = "Job Context"
    elif any(x in low for x in ["end my day", "daily closeout", "close out my day", "wrap up my day"]):
        intent = "daily_closeout"
        category = "Daily Closeout"
    elif any(x in low for x in ["start my day", "morning briefing", "daily briefing"]):
        intent = "start_day"
        category = "Daily Briefing"
    elif any(x in low for x in ["what did i do today", "today summary", "summarize today"]):
        intent = "today_summary"
        category = "Today Summary"
    elif _j7_re.search(r"\b(find|search|look up|show me)\b", low):
        intent = "search"
        category = "Search"
    elif any(x in low for x in ["billing", "bill", "invoice", "charge", "paid", "payment"]):
        intent = "billing_note"
        category = "Billing Note"
    elif any(x in low for x in ["field log", "we did", "installed", "cleaned", "replaced", "poured", "formed", "fixed", "dug", "plumbed"]):
        intent = "field_log"
        category = "Field Log"
    elif any(x in low for x in ["material", "materials", "need", "pickup", "pick up", "pipe", "union", "cement", "rebar", "concrete", "fitting"]):
        intent = "material_needed"
        category = "Material Needed"
    elif any(x in low for x in ["remind", "follow up", "call", "text", "email"]):
        intent = "follow_up"
        category = "Follow Up"
    elif any(x in low for x in ["what am i forgetting", "what matters", "what next", "what do i do"]):
        intent = "briefing"
        category = "Briefing"
    elif any(x in low for x in ["problem", "issue", "broken", "leak", "buzzing", "not working", "error", "failed"]):
        intent = "problem_found"
        category = "Problem Found"

    if any(x in low for x in ["urgent", "asap", "today", "right now", "gas", "electrical", "danger"]):
        priority = "High"

    title = raw[:90] if raw else "Jarvis Note"
    if len(raw) > 90:
        title += "..."

    return {
        "intent": intent,
        "category": category,
        "priority": priority,
        "title": title,
        "body": raw,
    }


def _j7_all_jobs(limit=300):
    if not _j7_table_exists("poolops2_jobs"):
        return []
    return _j7_rows("SELECT * FROM poolops2_jobs ORDER BY id DESC LIMIT ?", (limit,))


def _j7_job_date(job):
    for key in ["scheduled_start", "schedule_date", "date", "start_date", "created_at"]:
        val = (job or {}).get(key)
        if val:
            return str(val)[:10]
    return ""


def _j7_job_status(job):
    return str((job or {}).get("status") or "").lower().strip()


def _j7_job_title(job):
    if not job:
        return ""
    return str(
        job.get("client")
        or job.get("property")
        or job.get("address")
        or job.get("job_type")
        or f"Job #{job.get('id')}"
    )


def _j7_job_context(job):
    if not job:
        return {}
    return {
        "job_id": job.get("id"),
        "client": job.get("client") or "",
        "property": job.get("property") or "",
        "address": job.get("address") or "",
        "job_type": job.get("job_type") or "",
        "status": job.get("status") or "",
        "date": _j7_job_date(job),
        "title": _j7_job_title(job),
        "updated_at": _j7_now(),
    }


def _j7_clean_context_query(text):
    q = str(text or "").strip()
    q = _j7_re.sub(r"^jarvis[,\s]*", "", q, flags=_j7_re.I).strip()
    q = _j7_re.sub(r"^(set\s+active\s+job\s+to|set\s+active\s+job|active\s+job|i'm\s+at|im\s+at|working\s+on|we\s+are\s+at|we're\s+at)\s+", "", q, flags=_j7_re.I).strip()
    q = _j7_re.sub(r"^(find|search|look up|show me)\s+", "", q, flags=_j7_re.I).strip()
    return q


def _j7_match_job(text):
    q = _j7_clean_context_query(text)
    low = q.lower().strip()
    if not low:
        return None

    jobs = _j7_all_jobs()
    best = None
    best_score = 0

    for job in jobs:
        hay_parts = [
            str(job.get("client") or ""),
            str(job.get("property") or ""),
            str(job.get("address") or ""),
            str(job.get("job_type") or ""),
            str(job.get("notes") or ""),
            str(job.get("status") or ""),
        ]
        hay = " ".join(hay_parts).lower()

        score = 0
        if low and low in hay:
            score += 100

        for token in [x for x in _j7_re.split(r"[^a-zA-Z0-9]+", low) if len(x) >= 3]:
            if token in hay:
                score += 10

        client = str(job.get("client") or "").lower()
        prop = str(job.get("property") or "").lower()
        addr = str(job.get("address") or "").lower()

        if low == client:
            score += 50
        if low == prop:
            score += 50
        if low and low in addr:
            score += 25

        if score > best_score:
            best_score = score
            best = job

    return best if best_score > 0 else None


def _j7_active_context():
    return _j7_read_json("jarvis_active_context.json", {}) or {}


def _j7_set_active_context(job, user=None):
    ctx = _j7_job_context(job)
    ctx["set_by"] = _j7_name(user or {})
    _j7_write_json("jarvis_active_context.json", ctx)
    return ctx


def _j7_resolve_context(text, user=None):
    matched = _j7_match_job(text)
    if matched:
        return _j7_job_context(matched), "matched_command"
    active = _j7_active_context()
    if active:
        return active, "active_job"
    return {}, "none"


def _j7_dashboard_stats():
    today = _j7_today()
    jobs = _j7_all_jobs()
    today_jobs = []
    overdue_jobs = []

    for j in jobs:
        ds = _j7_job_date(j)
        status = _j7_job_status(j)
        if ds == today:
            today_jobs.append(j)
        if ds and ds < today and status not in ("complete", "completed", "done", "closed", "cancelled"):
            overdue_jobs.append(j)

    memory = _j7_read_jsonl("jarvis_memory.jsonl", 300)
    todays_memory = [m for m in memory if str(m.get("created_at") or "")[:10] == today]

    return {
        "today": today,
        "job_count_seen": len(jobs),
        "today_jobs": today_jobs[:8],
        "overdue_jobs": overdue_jobs[:8],
        "today_jobs_count": len(today_jobs),
        "overdue_jobs_count": len(overdue_jobs),
        "memory_count": len(memory),
        "todays_memory_count": len(todays_memory),
        "todays_memory": todays_memory[:50],
        "active_context": _j7_active_context(),
    }


def _j7_next_steps(user):
    role = _j7_role(user)
    stats = _j7_dashboard_stats()
    active = stats.get("active_context") or {}
    steps = []

    if active:
        steps.append(f"Active job is {active.get('title') or active.get('client') or active.get('address')}. New notes will attach there unless Jarvis matches another job.")

    if role == "client":
        return [
            "View your project update.",
            "Send a service request or question.",
            "Check approved photos and schedule notes.",
        ]

    if role == "crew":
        steps.append("Clock in when you arrive.")
        steps.append("Take arrival photos before work starts.")
        if stats["today_jobs_count"]:
            steps.append("Open today?s job and follow the first task.")
        else:
            steps.append("No job is scheduled for today in the table I can read. Ask Mike before starting.")
        steps.append("Before leaving, say: Jarvis, field log: then tell me what got done.")
        return steps

    if stats["overdue_jobs_count"]:
        steps.append(f"Clean up {stats['overdue_jobs_count']} overdue job(s): status, schedule, notes, or follow-up.")
    if stats["today_jobs_count"]:
        steps.append(f"You have {stats['today_jobs_count']} job(s) scheduled today.")
    else:
        steps.append("No jobs are scheduled for today in the table I can read.")
    steps.append("Say: Jarvis, set active job to Alexander ? before logging job-specific notes.")
    steps.append("Use billing notes immediately when something becomes money.")
    steps.append("End the day with: Jarvis, end my day.")
    return steps


def _j7_log_command(request, text, reply, intent):
    user = _j7_user(request)
    _j7_write_jsonl("jarvis_command_log.jsonl", {
        "created_at": _j7_now(),
        "created_by": _j7_name(user),
        "user_role": _j7_role(user),
        "command_text": text,
        "intent": intent,
        "reply": reply,
    })


def _j7_action_save(request, text, reply):
    user = _j7_user(request)
    c = _j7_classify(text)
    ctx, ctx_source = _j7_resolve_context(text, user)

    item = {
        "created_at": _j7_now(),
        "created_by": _j7_name(user),
        "user_role": _j7_role(user),
        "intent": c["intent"],
        "category": c["category"],
        "priority": c["priority"],
        "title": c["title"],
        "body": c["body"],
        "status": "Open",
        "reply": reply,
        "context_source": ctx_source,
        "job_id": ctx.get("job_id"),
        "client": ctx.get("client") or "",
        "property": ctx.get("property") or "",
        "address": ctx.get("address") or "",
        "job_type": ctx.get("job_type") or "",
    }

    _j7_write_jsonl("jarvis_memory.jsonl", item)
    _j7_log_command(request, text, reply, c["intent"])

    invisible_saved = False
    field_log_saved = False

    office_data = {
        "source": "Jarvis Brain",
        "category": c["category"],
        "title": c["title"],
        "body": c["body"],
        "priority": c["priority"],
        "status": "Open",
        "created_by": item["created_by"],
        "created_at": item["created_at"],
        "job_id": item["job_id"],
        "client": item["client"],
        "property": item["property"] or item["address"],
    }

    if c["intent"] in ("billing_note", "material_needed", "follow_up", "problem_found", "memory"):
        invisible_saved = _j7_insert_existing("invisible_office_items", office_data)

    if c["intent"] == "field_log":
        field_log_saved = _j7_insert_existing("field_logs", {
            "employee_name": item["created_by"],
            "client": item["client"],
            "property": item["property"] or item["address"],
            "address": item["address"],
            "date": _j7_today(),
            "work_completed": c["body"],
            "issues": "",
            "next_steps": "",
            "materials_used": "",
            "tools_used": "",
            "equipment_used": "",
            "weather": "",
            "created_at": item["created_at"],
        })

        invisible_saved = _j7_insert_existing("invisible_office_items", dict(office_data, category="Field Log")) or invisible_saved

    item["invisible_saved"] = bool(invisible_saved)
    item["field_log_saved"] = bool(field_log_saved)
    return item


def _j7_clock(request, direction):
    user = _j7_user(request)
    cols = _j7_columns("poolops2_employees")
    if not cols:
        return False, "I could not find the employee table."

    name = _j7_name(user)
    email = _j7_email(user)
    active = direction == "in"
    now = _j7_now()

    updates = {
        "clocked_in": 1 if active else 0,
        "clocked_in_at": now if active else "",
        "clocked_out_at": now if not active else "",
        "last_seen_at": now,
    }

    possible_where = []
    possible_params = []

    if email and "email" in cols:
        possible_where.append("email=?")
        possible_params.append(email)

    if name and "name" in cols:
        possible_where.append("name=?")
        possible_params.append(name)

    if not possible_where:
        _j7_log_command(request, f"clock {direction}", "Clock table exists, but I could not match your employee record.", "clock_" + direction)
        return False, "Clock table exists, but I could not match your employee record by name or email."

    ok = _j7_update_existing("poolops2_employees", updates, " OR ".join(possible_where), tuple(possible_params))
    reply = "You are clocked in." if active else "You are clocked out."
    if not ok:
        reply = "I saw the clock command, but your employee table does not have the clock columns I expected."

    _j7_log_command(request, f"clock {direction}", reply, "clock_" + direction)
    return ok, reply


def _j7_clean_search_query(text):
    q = str(text or "").strip()
    q = _j7_re.sub(r"^jarvis[,\s]*", "", q, flags=_j7_re.I).strip()
    q = _j7_re.sub(r"^(find|search|look up|show me)\s+", "", q, flags=_j7_re.I).strip()
    return q


def _j7_search(text):
    q = _j7_clean_search_query(text)
    if not q:
        return []

    like = f"%{q}%"
    results = []

    table_sets = [
        ("poolops2_clients", "/clients", "Client", ["name", "contact_name", "phone", "email", "notes"]),
        ("poolops2_properties", "/properties", "Property", ["client", "property_name", "address", "notes", "equipment_notes"]),
        ("poolops2_jobs", "/jobs", "Job", ["client", "property", "address", "job_type", "status", "notes"]),
        ("invisible_office_items", "/invisible-office", "Invisible Office", ["title", "body", "client", "property", "category"]),
        ("field_logs", "/field-logs", "Field Log", ["employee_name", "client", "property", "work_completed", "issues", "next_steps"]),
    ]

    for table, url, kind, candidates in table_sets:
        cols = _j7_columns(table)
        have = [c for c in candidates if c in cols]
        if not have:
            continue

        where = " OR ".join([f"CAST({c} AS TEXT) LIKE ?" for c in have])
        order = "ORDER BY id DESC" if "id" in cols else ""
        rows = _j7_rows(f"SELECT * FROM {table} WHERE {where} {order} LIMIT 8", tuple([like] * len(have)))

        for r in rows:
            title = (
                r.get("name")
                or r.get("property_name")
                or r.get("property")
                or r.get("title")
                or r.get("client")
                or r.get("work_completed")
                or kind
            )
            detail = r.get("address") or r.get("job_type") or r.get("category") or r.get("status") or ""
            rid = r.get("id")
            link = url
            if rid and url in ("/clients", "/properties", "/jobs"):
                link = f"{url}/{rid}"
            results.append({
                "kind": kind,
                "title": str(title)[:120],
                "detail": str(detail)[:160],
                "url": link,
            })

    for item in _j7_read_jsonl("jarvis_memory.jsonl", 300):
        body = str(item.get("body") or "")
        title = str(item.get("title") or "")
        client = str(item.get("client") or "")
        address = str(item.get("address") or "")
        hay = " ".join([body, title, client, address]).lower()
        if q.lower() in hay:
            results.append({
                "kind": "Jarvis Memory",
                "title": title[:120],
                "detail": body[:160],
                "url": "/jarvis-brain/desk",
            })

    return results[:12]


def _j7_today_memory():
    today = _j7_today()
    return [m for m in _j7_read_jsonl("jarvis_memory.jsonl", 500) if str(m.get("created_at") or "")[:10] == today]


def _j7_daily_report(request):
    user = _j7_user(request)
    stats = _j7_dashboard_stats()
    items = _j7_today_memory()

    categories = {}
    clients = {}
    for item in items:
        cat = str(item.get("category") or "General Note")
        categories[cat] = categories.get(cat, 0) + 1
        client = str(item.get("client") or "").strip()
        if client:
            clients[client] = clients.get(client, 0) + 1

    lines = []
    lines.append(f"Daily closeout for {_j7_today()}.")
    lines.append(f"Jarvis captured {len(items)} item(s) today.")
    lines.append(f"Jobs today: {stats['today_jobs_count']}. Overdue jobs still visible: {stats['overdue_jobs_count']}.")

    if categories:
        pieces = [f"{k}: {v}" for k, v in sorted(categories.items())]
        lines.append("Breakdown: " + "; ".join(pieces) + ".")

    if clients:
        pieces = [f"{k}: {v}" for k, v in sorted(clients.items())]
        lines.append("Job context captured for: " + "; ".join(pieces) + ".")

    money_items = [x for x in items if str(x.get("category") or "").lower() == "billing note"]
    field_items = [x for x in items if str(x.get("category") or "").lower() == "field log"]
    material_items = [x for x in items if str(x.get("category") or "").lower() == "material needed"]

    if money_items:
        lines.append(f"Money watch: {len(money_items)} billing note(s) need reviewed.")
    if field_items:
        lines.append(f"Field history: {len(field_items)} field log item(s) captured.")
    if material_items:
        lines.append(f"Materials: {len(material_items)} material-needed item(s) captured.")

    if not items:
        lines.append("No Jarvis memory was captured today. Tomorrow I need to prompt harder.")

    report = {
        "created_at": _j7_now(),
        "created_by": _j7_name(user),
        "date": _j7_today(),
        "summary": " ".join(lines),
        "stats": stats,
        "category_counts": categories,
        "client_counts": clients,
        "items": items[:100],
    }

    _j7_write_jsonl("jarvis_daily_reports.jsonl", report)

    _j7_insert_existing("invisible_office_items", {
        "source": "Jarvis Brain",
        "category": "Daily Closeout",
        "title": f"Daily Closeout - {_j7_today()}",
        "body": report["summary"],
        "priority": "Normal",
        "status": "Open",
        "created_by": _j7_name(user),
        "created_at": report["created_at"],
    })

    _j7_log_command(request, "Jarvis, end my day", report["summary"], "daily_closeout")
    return report


def _j7_start_day_reply(user):
    stats = _j7_dashboard_stats()
    steps = _j7_next_steps(user)
    active = stats.get("active_context") or {}
    active_line = ""
    if active:
        active_line = f" Active job is {active.get('title') or active.get('client') or active.get('address')}."
    return "Morning briefing: " + f"I can see {stats['today_jobs_count']} job(s) today, {stats['overdue_jobs_count']} overdue job(s), and {stats['memory_count']} total Jarvis memory item(s)." + active_line + " " + " ".join(steps[:4])


@app.middleware("http")
async def jarvis_level7_takeover(request, call_next):
    if JARVIS_TAKEOVER and request.url.path == "/jarvis":
        return RedirectResponse("/jarvis-brain", status_code=303)
    return await call_next(request)


@app.get("/jarvis-brain/install-check")
def jarvis_brain_install_check_level7():
    stats = _j7_dashboard_stats()
    return JSONResponse({
        "ok": True,
        "message": "Jarvis Brain Level 7 is installed and running.",
        "version": JARVIS_BRAIN_VERSION,
        "storage_folder": _j7_storage_dir(),
        "active_context": _j7_active_context(),
        "tables_seen": {
            "poolops2_jobs": _j7_table_exists("poolops2_jobs"),
            "poolops2_clients": _j7_table_exists("poolops2_clients"),
            "poolops2_properties": _j7_table_exists("poolops2_properties"),
            "poolops2_employees": _j7_table_exists("poolops2_employees"),
            "invisible_office_items": _j7_table_exists("invisible_office_items"),
            "field_logs": _j7_table_exists("field_logs"),
        },
        "stats": stats,
    })


@app.get("/jarvis-brain", response_class=HTMLResponse)
def jarvis_brain_level7_page(request: Request):
    user = _j7_user(request)
    name = _j7_name(user).split()[0]
    role = _j7_role(user)
    recent = _j7_read_jsonl("jarvis_memory.jsonl", 12)
    stats = _j7_dashboard_stats()
    active = stats.get("active_context") or {}

    memory_cards = ""
    if recent:
        for item in recent:
            context_line = ""
            if item.get("client") or item.get("address"):
                context_line = f"<div class='memory-meta'>Job: {_j7_esc(item.get('client'))} ? {_j7_esc(item.get('property') or item.get('address'))}</div>"
            memory_cards += f"""
            <div class="memory-card">
              <div class="memory-top"><b>{_j7_esc(item.get('category'))}</b><span>{_j7_esc(item.get('created_at'))}</span></div>
              <div class="memory-title">{_j7_esc(item.get('title'))}</div>
              <div class="memory-body">{_j7_esc(item.get('body'))}</div>
              {context_line}
              <div class="memory-meta">Priority: {_j7_esc(item.get('priority'))} ? Invisible Office: {_j7_esc(item.get('invisible_saved'))} ? Field Log: {_j7_esc(item.get('field_log_saved'))}</div>
            </div>
            """
    else:
        memory_cards = "<p>No Jarvis memory saved yet. Feed me commands and I will start building the brain.</p>"

    job_cards = ""
    for job in stats["today_jobs"]:
        title = _j7_job_title(job)
        detail = job.get("job_type") or job.get("status") or job.get("address") or ""
        job_cards += f"<li><b>{_j7_esc(title)}</b><br><span>{_j7_esc(detail)}</span></li>"
    if not job_cards:
        job_cards = "<li>No jobs found for today from the table I can read.</li>"

    next_steps = "".join([f"<li>{_j7_esc(x)}</li>" for x in _j7_next_steps(user)])

    active_html = "<p>No active job set. Say: <b>Jarvis, set active job to Alexander</b>.</p>"
    if active:
        active_html = f"""
        <p><b>{_j7_esc(active.get('title'))}</b></p>
        <p>{_j7_esc(active.get('address'))}</p>
        <p>Status: {_j7_esc(active.get('status'))} ? Type: {_j7_esc(active.get('job_type'))}</p>
        """

    template = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis Brain</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }
    .wrap { max-width:1180px; margin:0 auto; padding:28px; }
    .hero { background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:26px; box-shadow:0 20px 60px rgba(0,0,0,.45); }
    h1 { margin:0 0 8px; font-size:34px; letter-spacing:.08em; }
    .sub { color:#d9b56d; margin-bottom:22px; }
    .grid { display:grid; grid-template-columns:1.1fr .9fr; gap:18px; }
    @media(max-width:850px) { .grid { grid-template-columns:1fr; } }
    .card { background:#101722; border:1px solid #2d2113; border-radius:18px; padding:20px; margin-top:18px; }
    textarea { width:100%; min-height:145px; box-sizing:border-box; border-radius:14px; border:1px solid #6b4b1f; background:#05070b; color:#fff; padding:14px; font-size:16px; }
    button { margin-top:12px; padding:13px 18px; border:0; border-radius:12px; background:#b8873a; color:#111; font-weight:900; cursor:pointer; }
    .reply { margin-top:14px; padding:14px; border-radius:12px; background:#05070b; border:1px solid #2d2113; min-height:24px; line-height:1.45; }
    .chips { display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }
    .chip { border:1px solid #6b4b1f; border-radius:999px; padding:10px 12px; background:#070a0f; color:#f5efe3; cursor:pointer; }
    .stats { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
    @media(max-width:700px) { .stats { grid-template-columns:repeat(2,1fr); } }
    .stat { background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:14px; }
    .stat b { font-size:28px; color:#d9b56d; }
    .memory-card { background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:14px; margin:10px 0; }
    .memory-top { display:flex; justify-content:space-between; gap:12px; color:#d9b56d; font-size:13px; }
    .memory-title { font-weight:900; margin-top:8px; }
    .memory-body { margin-top:8px; color:#e8dcc7; line-height:1.4; }
    .memory-meta { margin-top:10px; color:#a99572; font-size:13px; }
    a { color:#d9a64a; }
    li { margin-bottom:12px; }
    .result { padding:10px; border:1px solid #2d2113; border-radius:12px; margin:8px 0; background:#070a0f; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>J.A.R.V.I.S. BRAIN</h1>
      <div class="sub">Good to go, __NAME__. Level 7 Job Context is active. Role: __ROLE__.</div>

      <div class="stats">
        <div class="stat"><b>__TODAY_COUNT__</b><br>Jobs today</div>
        <div class="stat"><b>__OVERDUE_COUNT__</b><br>Overdue jobs</div>
        <div class="stat"><b>__TODAY_MEMORY__</b><br>Captured today</div>
        <div class="stat"><b>__MEMORY_COUNT__</b><br>Total memory</div>
      </div>

      <div class="grid">
        <div class="card">
          <h2>Command Jarvis</h2>
          <textarea id="cmd" placeholder="Jarvis, set active job to Alexander."></textarea>
          <br>
          <button onclick="sendCmd()">Send</button>
          <button onclick="startVoice()">?? Voice</button>
          <button onclick="speakLast()">?? Read Back</button>
          <div class="reply" id="reply">Waiting for command.</div>

          <div class="chips">
            <button class="chip" onclick="fillCmd('Jarvis, set active job to ')">Set Active Job</button>
            <button class="chip" onclick="fillCmd('Jarvis, start my day')">Start My Day</button>
            <button class="chip" onclick="fillCmd('Jarvis, end my day')">End My Day</button>
            <button class="chip" onclick="fillCmd('Jarvis, find ')">Find</button>
            <button class="chip" onclick="fillCmd('Jarvis, add this to billing: ')">Billing</button>
            <button class="chip" onclick="fillCmd('Jarvis, field log: ')">Field log</button>
            <button class="chip" onclick="fillCmd('Jarvis, material needed: ')">Material</button>
          </div>
        </div>

        <div class="card">
          <h2>Active Job</h2>
          __ACTIVE_JOB__
          <h2>What next</h2>
          <ul>__NEXT_STEPS__</ul>
          <h2>Today</h2>
          <ul>__JOB_CARDS__</ul>
          <p>
            <a href="/jarvis-brain/desk">Command Desk</a>
            |
            <a href="/jarvis-brain/install-check">Install Check</a>
            |
            <a href="/jarvis-brain/export.json">Export</a>
            |
            <a href="/invisible-office">Invisible Office</a>
            |
            <a href="/">Home</a>
          </p>
        </div>
      </div>

      <div class="card">
        <h2>Recent Jarvis Memory</h2>
        __MEMORY_CARDS__
      </div>
    </div>
  </div>

<script>
let lastReply = "";

function fillCmd(t){
  document.getElementById("cmd").value = t;
  document.getElementById("cmd").focus();
}

function escapeHtml(str){
  return String(str || "").replace(/[&<>"']/g, function(m){
    return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'})[m];
  });
}

function speak(text){
  if(!("speechSynthesis" in window)){ return; }
  window.speechSynthesis.cancel();
  const msg = new SpeechSynthesisUtterance(text);
  msg.rate = 1;
  msg.pitch = 1;
  window.speechSynthesis.speak(msg);
}

function speakLast(){
  const text = lastReply || document.getElementById("reply").innerText || "Nothing to read back yet.";
  speak(text);
}

async function sendCmd(){
  const box = document.getElementById("cmd");
  const reply = document.getElementById("reply");
  const text = box.value.trim();

  if(!text){
    reply.innerText = "Tell me what needs handled.";
    lastReply = reply.innerText;
    return;
  }

  reply.innerText = "Handling it...";
  lastReply = reply.innerText;

  try {
    const res = await fetch("/jarvis-brain/command", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({text:text})
    });

    const data = await res.json();
    let html = escapeHtml(data.reply || JSON.stringify(data));
    lastReply = data.reply || JSON.stringify(data);

    if(data.links && data.links.length){
      html += "<br><br><b>Matches:</b>";
      data.links.forEach(function(x){
        html += '<div class="result"><b>' + escapeHtml(x.kind) + '</b>: ';
        html += '<a href="' + escapeHtml(x.url) + '">' + escapeHtml(x.title) + '</a>';
        if(x.detail){ html += '<br><small>' + escapeHtml(x.detail) + '</small>'; }
        html += '</div>';
      });
    }

    reply.innerHTML = html;
    speak(lastReply);

    if(data.ok && (!data.links || !data.links.length)){
      setTimeout(() => window.location.reload(), 1200);
    }
  } catch(err) {
    reply.innerText = "Jarvis command failed: " + err;
    lastReply = reply.innerText;
    speak(lastReply);
  }
}

function startVoice(){
  const reply = document.getElementById("reply");
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){
    reply.innerText = "Voice is not available in this browser. Use Chrome or Edge.";
    lastReply = reply.innerText;
    speakLast();
    return;
  }

  const rec = new SR();
  rec.lang = "en-US";
  rec.interimResults = false;
  rec.maxAlternatives = 1;

  reply.innerText = "Listening...";
  lastReply = reply.innerText;
  rec.onresult = function(event){
    const text = event.results[0][0].transcript;
    document.getElementById("cmd").value = text;
    sendCmd();
  };
  rec.onerror = function(event){
    reply.innerText = "Voice error: " + event.error;
    lastReply = reply.innerText;
  };
  rec.start();
}
</script>
</body>
</html>
"""
    html = template
    html = html.replace("__NAME__", _j7_esc(name))
    html = html.replace("__ROLE__", _j7_esc(role))
    html = html.replace("__TODAY_COUNT__", str(stats["today_jobs_count"]))
    html = html.replace("__OVERDUE_COUNT__", str(stats["overdue_jobs_count"]))
    html = html.replace("__TODAY_MEMORY__", str(stats["todays_memory_count"]))
    html = html.replace("__MEMORY_COUNT__", str(stats["memory_count"]))
    html = html.replace("__NEXT_STEPS__", next_steps)
    html = html.replace("__JOB_CARDS__", job_cards)
    html = html.replace("__MEMORY_CARDS__", memory_cards)
    html = html.replace("__ACTIVE_JOB__", active_html)
    return HTMLResponse(html)


@app.post("/jarvis-brain/command")
async def jarvis_brain_level7_command(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    text = str(payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "reply": "Tell me what needs handled."})

    c = _j7_classify(text)
    user = _j7_user(request)

    if c["intent"] == "set_context":
        job = _j7_match_job(text)
        if not job:
            reply = "I tried to set the active job, but I could not find a matching job. Try: Jarvis, find Alexander."
            _j7_log_command(request, text, reply, "set_context_failed")
            return JSONResponse({"ok": False, "version": JARVIS_BRAIN_VERSION, "reply": reply})

        ctx = _j7_set_active_context(job, user)
        reply = f"Active job set to {ctx.get('title') or ctx.get('client') or ctx.get('address')}."
        if ctx.get("address"):
            reply += f" Address: {ctx.get('address')}."
        _j7_log_command(request, text, reply, "set_context")
        return JSONResponse({"ok": True, "version": JARVIS_BRAIN_VERSION, "reply": reply, "active_context": ctx})

    if c["intent"] == "clock_in":
        ok, reply = _j7_clock(request, "in")
        return JSONResponse({"ok": ok, "version": JARVIS_BRAIN_VERSION, "reply": reply})

    if c["intent"] == "clock_out":
        ok, reply = _j7_clock(request, "out")
        return JSONResponse({"ok": ok, "version": JARVIS_BRAIN_VERSION, "reply": reply})

    if c["intent"] == "search":
        links = _j7_search(text)
        reply = f"I found {len(links)} match(es)." if links else "I searched what I can see, but I did not find a solid match."
        _j7_log_command(request, text, reply, "search")
        return JSONResponse({"ok": True, "version": JARVIS_BRAIN_VERSION, "reply": reply, "links": links})

    if c["intent"] == "start_day":
        reply = _j7_start_day_reply(user)
        _j7_log_command(request, text, reply, "start_day")
        return JSONResponse({"ok": True, "version": JARVIS_BRAIN_VERSION, "reply": reply, "stats": _j7_dashboard_stats()})

    if c["intent"] == "daily_closeout":
        report = _j7_daily_report(request)
        return JSONResponse({"ok": True, "version": JARVIS_BRAIN_VERSION, "reply": report["summary"], "report": report})

    if c["intent"] == "today_summary":
        report = _j7_daily_report(request)
        return JSONResponse({"ok": True, "version": JARVIS_BRAIN_VERSION, "reply": report["summary"], "report": report})

    if c["intent"] == "briefing":
        reply = _j7_start_day_reply(user)
        _j7_log_command(request, text, reply, "briefing")
        return JSONResponse({"ok": True, "version": JARVIS_BRAIN_VERSION, "reply": reply, "stats": _j7_dashboard_stats()})

    if c["intent"] == "billing_note":
        reply = "I saved that as a billing note and tied it to the active or matched job if I could."
    elif c["intent"] == "field_log":
        reply = "I saved that as a field log and tied it to the active or matched job if I could."
    elif c["intent"] == "material_needed":
        reply = "I saved that as a material-needed item and tied it to the active or matched job if I could."
    elif c["intent"] == "follow_up":
        reply = "I saved that as a follow-up item and tied it to the active or matched job if I could."
    elif c["intent"] == "problem_found":
        reply = "I saved that as a problem found. That protects the job history."
    else:
        reply = "I saved that to Jarvis memory."

    item = _j7_action_save(request, text, reply)

    if item.get("client") or item.get("address"):
        reply += f" Job context: {item.get('client') or ''} {item.get('property') or item.get('address') or ''}."
    if item.get("invisible_saved"):
        reply += " Invisible Office save confirmed."
    if item.get("field_log_saved"):
        reply += " Field Log save confirmed."

    return JSONResponse({
        "ok": True,
        "version": JARVIS_BRAIN_VERSION,
        "reply": reply,
        "item": item,
    })


@app.get("/jarvis-brain/export.json")
def jarvis_brain_level7_export():
    return JSONResponse({
        "ok": True,
        "version": JARVIS_BRAIN_VERSION,
        "active_context": _j7_active_context(),
        "memory": _j7_read_jsonl("jarvis_memory.jsonl", 500),
        "command_log": _j7_read_jsonl("jarvis_command_log.jsonl", 500),
        "daily_reports": _j7_read_jsonl("jarvis_daily_reports.jsonl", 100),
        "stats": _j7_dashboard_stats(),
    })


@app.get("/jarvis-brain/daily-report.json")
def jarvis_brain_level7_daily_report():
    return JSONResponse({
        "ok": True,
        "version": JARVIS_BRAIN_VERSION,
        "daily_reports": _j7_read_jsonl("jarvis_daily_reports.jsonl", 100),
    })


@app.get("/jarvis-brain/context.json")
def jarvis_brain_level7_context_json():
    return JSONResponse({
        "ok": True,
        "version": JARVIS_BRAIN_VERSION,
        "active_context": _j7_active_context(),
    })


@app.get("/brain", response_class=HTMLResponse)
def brain_alias_level7(request: Request):
    return RedirectResponse("/jarvis-brain", status_code=303)

# ============================================================
# END JARVIS BRAIN LAYER
# ============================================================

