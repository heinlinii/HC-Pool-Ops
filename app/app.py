from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
from datetime import datetime, date, timedelta, timedelta, timezone
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
import logging
import urllib.request
import urllib.parse
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

FIELDY_API_KEY = os.getenv("FIELDY_API_KEY", "")
FIELDY_PRIVATE_TOKEN = os.getenv("FIELDY_WEBHOOK_TOKEN", "")


@app.get("/integrations/fieldy/health")
def fieldy_health():
    return {
        "ok": True,
        "integration": "fieldy",
        "message": "Fieldy integration is alive"
    }


@app.get("/integrations/fieldy/recent")
def fieldy_recent(token: str = ""):
    if token != FIELDY_PRIVATE_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not FIELDY_API_KEY:
        raise HTTPException(status_code=500, detail="FIELDY_API_KEY is not set")

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=3)

    params = urllib.parse.urlencode({
        "startTime": start_time.isoformat().replace("+00:00", "Z"),
        "endTime": end_time.isoformat().replace("+00:00", "Z"),
        "pageSize": 10,
    })

    url = f"https://api.fieldy.ai/api/public/v2/conversations?{params}"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {FIELDY_API_KEY}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
    except Exception as e:
        logging.exception("Fieldy API request failed")
        raise HTTPException(status_code=500, detail=f"Fieldy API error: {str(e)}")

    return {
        "ok": True,
        "source": "fieldy",
        "range": "last_3_days",
        "data": data,
    }


def fetch_fieldy_notes(days: int = 3, page_size: int = 50):
    if not FIELDY_API_KEY:
        raise HTTPException(status_code=500, detail="FIELDY_API_KEY is not set")

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days)

    params = urllib.parse.urlencode({
        "startTime": start_time.isoformat().replace("+00:00", "Z"),
        "endTime": end_time.isoformat().replace("+00:00", "Z"),
        "pageSize": page_size,
    })

    url = f"https://api.fieldy.ai/api/public/v2/conversations?{params}"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {FIELDY_API_KEY}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
    except Exception as e:
        logging.exception("Fieldy fetch failed")
        raise HTTPException(status_code=500, detail=f"Fieldy API error: {str(e)}")

    return data.get("items", [])


def extract_jarvis_commands_from_note(note):
    commands = []

    note_id = note.get("id", "")
    title = note.get("title") or "Untitled Fieldy Note"
    summary = note.get("summary") or ""
    content = note.get("content") or ""
    start_time = note.get("startTime") or ""
    quotes = note.get("quotes") or []

    text_blocks = []

    if summary:
        text_blocks.append(summary)

    if content:
        text_blocks.append(content)

    for q in quotes:
        q_text = q.get("text", "")
        if q_text:
            text_blocks.append(q_text)

    combined = "\n".join(text_blocks)

    if "jarvis" not in combined.lower():
        return commands

    # Finds phrases like:
    # Jarvis, I'm at Scheller's house doing the opening.
    # Jarvis add this to today's log: cleaned filter and checked heater.
    pattern = re.compile(
        r"(jarvis[\s,:\-]+.*?)(?=(?:\n|\. |\? |! |$))",
        re.IGNORECASE | re.DOTALL
    )

    matches = pattern.findall(combined)

    for raw in matches:
        cleaned = " ".join(raw.replace("\n", " ").split()).strip()

        if not cleaned:
            continue

        lower = cleaned.lower()

        command_type = "General Note"
        customer_guess = ""
        work_guess = cleaned

        if "remind me" in lower:
            command_type = "Reminder"
        elif "follow up" in lower or "call" in lower or "text" in lower:
            command_type = "Follow Up"
        elif "material" in lower or "materials" in lower or "order" in lower:
            command_type = "Material List"
        elif "today's log" in lower or "todays log" in lower or "daily log" in lower:
            command_type = "Daily Log"
        elif "i'm at" in lower or "im at" in lower or "i am at" in lower:
            command_type = "Job Log"
        elif "customer note" in lower:
            command_type = "Customer Note"

        # Simple customer guess from:
        # "I'm at Scheller's house..."
        customer_patterns = [
            r"i[' ]?m at ([A-Za-z0-9 .'\-]+?)(?:'s)? house",
            r"im at ([A-Za-z0-9 .'\-]+?)(?:'s)? house",
            r"i am at ([A-Za-z0-9 .'\-]+?)(?:'s)? house",
            r"at ([A-Za-z0-9 .'\-]+?)(?:'s)? house",
            r"for ([A-Za-z0-9 .'\-]+?)(?:'s)? job",
        ]

        for cp in customer_patterns:
            m = re.search(cp, cleaned, re.IGNORECASE)
            if m:
                customer_guess = m.group(1).strip(" .'")
                break

        # Simple work guess from:
        # "doing opening work"
        work_patterns = [
            r"doing (.+)",
            r"working on (.+)",
            r"here to (.+)",
            r"add this to today'?s log[:\- ]+(.+)",
            r"customer note[:\- ]+(.+)",
        ]

        for wp in work_patterns:
            m = re.search(wp, cleaned, re.IGNORECASE)
            if m:
                work_guess = m.group(1).strip()
                break

        commands.append({
            "note_id": note_id,
            "title": title,
            "start_time": start_time,
            "type": command_type,
            "customer_guess": customer_guess,
            "work_guess": work_guess,
            "raw": cleaned,
        })

    return commands


@app.get("/fieldy/commands", response_class=HTMLResponse)
def fieldy_commands(request: Request, days: int = 3):
    u = require_login(request)
    if not u:
        return login_redirect()

    notes = fetch_fieldy_notes(days=days, page_size=75)

    commands = []
    for note in notes:
        commands.extend(extract_jarvis_commands_from_note(note))

    return templates.TemplateResponse(
        "fieldy_commands.html",
        ctx(
            request,
            user=u,
            commands=commands,
            days=days,
        )
    )

@app.get("/fieldy", response_class=HTMLResponse)
def fieldy_inbox(request: Request, days: int = 3):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not FIELDY_API_KEY:
        raise HTTPException(status_code=500, detail="FIELDY_API_KEY is not set")

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days)

    params = urllib.parse.urlencode({
        "startTime": start_time.isoformat().replace("+00:00", "Z"),
        "endTime": end_time.isoformat().replace("+00:00", "Z"),
        "pageSize": 25,
    })

    url = f"https://api.fieldy.ai/api/public/v2/conversations?{params}"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {FIELDY_API_KEY}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
    except Exception as e:
        logging.exception("Fieldy inbox request failed")
        raise HTTPException(status_code=500, detail=f"Fieldy API error: {str(e)}")

    notes = data.get("items", [])

    return templates.TemplateResponse(
        "fieldy_inbox.html",
        ctx(
            request,
            user=u,
            notes=notes,
            days=days,
        )
    )

FIELDY_WEBHOOK_TOKEN = os.getenv("FIELDY_WEBHOOK_TOKEN", "")


@app.post("/integrations/fieldy/webhook")
async def fieldy_webhook(request: Request, token: str = ""):
    if not FIELDY_WEBHOOK_TOKEN:
        raise HTTPException(status_code=500, detail="FIELDY_WEBHOOK_TOKEN is not set")

    if token != FIELDY_WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized Fieldy webhook")

    payload = await request.json()

    logging.warning("FIELDY WEBHOOK RECEIVED:")
    logging.warning(json.dumps(payload, indent=2)[:10000])

    return {
        "ok": True,
        "received": True
    }

FIELDY_API_KEY = os.getenv("FIELDY_API_KEY", "")


@app.get("/integrations/fieldy/recent")
def fieldy_recent(token: str = ""):
    if token != os.getenv("FIELDY_WEBHOOK_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not FIELDY_API_KEY:
        raise HTTPException(status_code=500, detail="FIELDY_API_KEY is not set")

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=3)

    params = urllib.parse.urlencode({
        "startTime": start_time.isoformat().replace("+00:00", "Z"),
        "endTime": end_time.isoformat().replace("+00:00", "Z"),
        "pageSize": 10,
    })

    url = f"https://api.fieldy.ai/api/public/v2/conversations?{params}"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {FIELDY_API_KEY}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fieldy API error: {str(e)}")

    return {
        "ok": True,
        "source": "fieldy",
        "data": data,
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

FIELDY_WEBHOOK_TOKEN = os.getenv("FIELDY_WEBHOOK_TOKEN", "")

@app.get("/integrations/fieldy/health")
def fieldy_health():
    return {
        "ok": True,
        "integration": "fieldy",
        "message": "Fieldy webhook receiver is alive"
    }


@app.post("/integrations/fieldy/webhook")
async def fieldy_webhook(request: Request, token: str = ""):
    if not FIELDY_WEBHOOK_TOKEN:
        raise HTTPException(status_code=500, detail="FIELDY_WEBHOOK_TOKEN is not set")

    if token != FIELDY_WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized Fieldy webhook")

    payload = await request.json()

    logging.warning("FIELDY WEBHOOK RECEIVED:")
    logging.warning(json.dumps(payload, indent=2)[:10000])

    return {
        "ok": True,
        "received": True
    }

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

@app.post("/jarvis/action/{action_id}/done")
def jarvis_action_done(request: Request, action_id: int):
    u = require_login(request)
    if not u:
        return login_redirect()

    exec_sql(
        "UPDATE jarvis_actions SET status=?, completed_at=? WHERE id=?",
        (
            "Done",
            datetime.now().strftime("%Y-%m-%d %I:%M %p"),
            action_id
        )
    )

    return RedirectResponse("/jarvis", status_code=303)

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


# ============================================================
# JARVIS BRAIN LEVEL 8 ACTIVE JOB CENTER
# Adds /jarvis-brain/job without replacing Level 7.
# ============================================================

import os as _j8_os
import json as _j8_json
import html as _j8_html
from datetime import datetime as _j8_datetime, date as _j8_date

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_JOB_CENTER_VERSION = "level-8-active-job-center-2026-07-04"


def _j8_now():
    return _j8_datetime.now().isoformat(timespec="seconds")


def _j8_today():
    return _j8_date.today().isoformat()


def _j8_storage_dir():
    path = _j8_os.path.join(_j8_os.getcwd(), "jarvis_storage")
    _j8_os.makedirs(path, exist_ok=True)
    return path


def _j8_file(name):
    return _j8_os.path.join(_j8_storage_dir(), name)


def _j8_esc(value):
    return _j8_html.escape(str(value or ""))


def _j8_read_json(name, default=None):
    path = _j8_file(name)
    if not _j8_os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _j8_json.load(f)
    except Exception:
        return default


def _j8_write_json(name, data):
    with open(_j8_file(name), "w", encoding="utf-8") as f:
        _j8_json.dump(data, f, ensure_ascii=False, indent=2)


def _j8_read_jsonl_all(name):
    path = _j8_file(name)
    if not _j8_os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                items.append(_j8_json.loads(line.strip()))
            except Exception:
                pass
    return items


def _j8_user(request):
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


def _j8_name(user):
    return str((user or {}).get("name") or (user or {}).get("username") or (user or {}).get("email") or "Mike").strip()


def _j8_role(user):
    role = str((user or {}).get("role") or "admin").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j8_active_context():
    return _j8_read_json("jarvis_active_context.json", {}) or {}


def _j8_clear_active_context():
    _j8_write_json("jarvis_active_context.json", {})
    return True


def _j8_match_active_item(item, active):
    if not active:
        return False

    item_job_id = str(item.get("job_id") or "").strip()
    active_job_id = str(active.get("job_id") or "").strip()

    if item_job_id and active_job_id and item_job_id == active_job_id:
        return True

    item_client = str(item.get("client") or "").lower().strip()
    active_client = str(active.get("client") or "").lower().strip()

    item_address = str(item.get("address") or "").lower().strip()
    active_address = str(active.get("address") or "").lower().strip()

    item_property = str(item.get("property") or "").lower().strip()
    active_property = str(active.get("property") or "").lower().strip()

    if active_client and item_client and active_client == item_client:
        return True

    if active_address and item_address and active_address == item_address:
        return True

    if active_property and item_property and active_property == item_property:
        return True

    return False


def _j8_active_job_items():
    active = _j8_active_context()
    items = _j8_read_jsonl_all("jarvis_memory.jsonl")
    items.reverse()

    if not active:
        return []

    return [x for x in items if _j8_match_active_item(x, active)]


def _j8_group_items(items):
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


def _j8_status(item):
    return str(item.get("status") or "Open").strip()


def _j8_is_open(item):
    return _j8_status(item).lower() not in ("done", "closed", "complete", "completed")


def _j8_render_item(item):
    cat = _j8_esc(item.get("category"))
    created = _j8_esc(item.get("created_at"))
    title = _j8_esc(item.get("title"))
    body = _j8_esc(item.get("body"))
    priority = _j8_esc(item.get("priority") or "Normal")
    status = _j8_esc(_j8_status(item))

    return f"""
    <div class="job-item">
      <div class="job-top">
        <b>{cat}</b>
        <span>{created}</span>
      </div>
      <div class="job-title">{title}</div>
      <div class="job-body">{body}</div>
      <div class="job-meta">Priority: {priority} ? Status: {status}</div>
    </div>
    """


def _j8_job_summary(active, items):
    groups = _j8_group_items(items)
    open_items = [x for x in items if _j8_is_open(x)]

    summary = {
        "active_job": active,
        "total_items": len(items),
        "open_items": len(open_items),
        "billing_notes": len(groups.get("Billing Note", [])),
        "materials": len(groups.get("Material Needed", [])),
        "followups": len(groups.get("Follow Up", [])),
        "problems": len(groups.get("Problem Found", [])),
        "field_logs": len(groups.get("Field Log", [])),
        "general": len(groups.get("General Note", [])),
    }

    next_actions = []

    if summary["billing_notes"]:
        next_actions.append(f"Review {summary['billing_notes']} billing note(s) for this job.")
    if summary["problems"]:
        next_actions.append(f"Handle {summary['problems']} problem item(s) for this job.")
    if summary["materials"]:
        next_actions.append(f"Check {summary['materials']} material-needed item(s) before going back.")
    if summary["followups"]:
        next_actions.append(f"Make {summary['followups']} follow-up item(s) for this job.")
    if summary["field_logs"]:
        next_actions.append(f"Review {summary['field_logs']} field log item(s) for job history.")

    if not next_actions:
        next_actions.append("No job-specific Jarvis memory yet. Start by adding a field log, billing note, material item, or follow-up.")

    summary["next_actions"] = next_actions
    return summary


@app.get("/jarvis-brain/job", response_class=HTMLResponse)
def jarvis_brain_level8_active_job_center(request: Request):
    user = _j8_user(request)
    name = _j8_name(user).split()[0]
    role = _j8_role(user)

    active = _j8_active_context()
    items = _j8_active_job_items()
    groups = _j8_group_items(items)
    summary = _j8_job_summary(active, items)

    if not active:
        active_html = """
        <div class="card">
          <h2>No Active Job Set</h2>
          <p>Go back to Jarvis Brain and say:</p>
          <p><b>Jarvis, set active job to Alexander</b></p>
          <p>Then come back here.</p>
          <p><a href="/jarvis-brain">Open Jarvis Brain</a></p>
        </div>
        """
    else:
        active_html = f"""
        <div class="card">
          <h2>Active Job</h2>
          <p><b>{_j8_esc(active.get('title'))}</b></p>
          <p>{_j8_esc(active.get('client'))}</p>
          <p>{_j8_esc(active.get('address'))}</p>
          <p>Type: {_j8_esc(active.get('job_type'))} ? Status: {_j8_esc(active.get('status'))}</p>
          <form method="post" action="/jarvis-brain/job/clear">
            <button type="submit">Clear Active Job</button>
          </form>
        </div>
        """

    action_html = "".join([f"<li>{_j8_esc(x)}</li>" for x in summary["next_actions"]])

    grouped_html = ""
    for group_name, group_items in groups.items():
        if not group_items:
            continue
        grouped_html += f"""
        <div class="card">
          <h2>{_j8_esc(group_name)} <span>{len(group_items)}</span></h2>
          {''.join(_j8_render_item(x) for x in group_items[:30])}
        </div>
        """

    if not grouped_html:
        grouped_html = """
        <div class="card">
          <h2>No Job Memory Yet</h2>
          <p>Use the command box to start capturing this job.</p>
        </div>
        """

    active_label = active.get("title") or active.get("client") or active.get("address") or "this job"

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis Active Job</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }}
    .wrap {{ max-width:1220px; margin:0 auto; padding:26px; }}
    .hero {{ background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:24px; box-shadow:0 20px 60px rgba(0,0,0,.45); }}
    h1 {{ margin:0 0 8px; font-size:34px; letter-spacing:.08em; }}
    .sub {{ color:#d9b56d; margin-bottom:20px; }}
    .stats {{ display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin:16px 0; }}
    @media(max-width:950px) {{ .stats {{ grid-template-columns:repeat(2,1fr); }} }}
    .stat {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:14px; }}
    .stat b {{ font-size:28px; color:#d9b56d; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    @media(max-width:950px) {{ .grid {{ grid-template-columns:1fr; }} }}
    .card {{ background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; margin-top:16px; }}
    .card h2 {{ display:flex; justify-content:space-between; align-items:center; gap:10px; }}
    textarea {{ width:100%; min-height:125px; box-sizing:border-box; border-radius:14px; border:1px solid #6b4b1f; background:#05070b; color:#fff; padding:14px; font-size:16px; }}
    button {{ margin-top:10px; padding:12px 16px; border:0; border-radius:12px; background:#b8873a; color:#111; font-weight:900; cursor:pointer; }}
    .reply {{ margin-top:12px; padding:13px; border-radius:12px; background:#05070b; border:1px solid #2d2113; min-height:24px; line-height:1.45; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:9px; margin-top:10px; }}
    .chip {{ border:1px solid #6b4b1f; border-radius:999px; padding:9px 11px; background:#070a0f; color:#f5efe3; cursor:pointer; }}
    .job-item {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:13px; margin:10px 0; }}
    .job-top {{ display:flex; justify-content:space-between; gap:12px; color:#d9b56d; font-size:13px; }}
    .job-title {{ font-weight:900; margin-top:8px; }}
    .job-body {{ margin-top:8px; color:#e8dcc7; line-height:1.4; }}
    .job-meta {{ margin-top:9px; color:#a99572; font-size:13px; }}
    a {{ color:#d9a64a; }}
    li {{ margin-bottom:10px; }}
    .result {{ padding:10px; border:1px solid #2d2113; border-radius:12px; margin:8px 0; background:#070a0f; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>J.A.R.V.I.S. ACTIVE JOB</h1>
    <div class="sub">Good to go, {_j8_esc(name)}. This is the job brain for {_j8_esc(active_label)}. Role: {_j8_esc(role)}.</div>

    <div class="stats">
      <div class="stat"><b>{summary['total_items']}</b><br>Total items</div>
      <div class="stat"><b>{summary['open_items']}</b><br>Open</div>
      <div class="stat"><b>{summary['billing_notes']}</b><br>Billing</div>
      <div class="stat"><b>{summary['materials']}</b><br>Materials</div>
      <div class="stat"><b>{summary['problems']}</b><br>Problems</div>
      <div class="stat"><b>{summary['field_logs']}</b><br>Field Logs</div>
    </div>

    <div class="grid">
      <div>
        {active_html}

        <div class="card">
          <h2>Command This Job</h2>
          <textarea id="cmd" placeholder="Jarvis, field log: "></textarea>
          <button onclick="sendCmd()">Send</button>
          <button onclick="startVoice()">?? Voice</button>
          <button onclick="speakLast()">?? Read Back</button>
          <div class="reply" id="reply">Waiting for job command.</div>

          <div class="chips">
            <button class="chip" onclick="fillCmd('Jarvis, field log: ')">Field Log</button>
            <button class="chip" onclick="fillCmd('Jarvis, add this to billing: ')">Billing</button>
            <button class="chip" onclick="fillCmd('Jarvis, material needed: ')">Material</button>
            <button class="chip" onclick="fillCmd('Jarvis, problem found: ')">Problem</button>
            <button class="chip" onclick="fillCmd('Jarvis, remind me to follow up with ')">Follow Up</button>
            <button class="chip" onclick="fillCmd('Jarvis, what did I do today?')">Today Summary</button>
          </div>
        </div>

        <div class="card">
          <h2>Next For This Job</h2>
          <ul>{action_html}</ul>
        </div>

        <div class="card">
          <h2>Links</h2>
          <p>
            <a href="/jarvis-brain">Jarvis Brain</a>
            |
            <a href="/jarvis-brain/desk">Command Desk</a>
            |
            <a href="/jarvis-brain/job.json">Job JSON</a>
            |
            <a href="/invisible-office">Invisible Office</a>
            |
            <a href="/">Home</a>
          </p>
        </div>
      </div>

      <div>
        {grouped_html}
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


@app.post("/jarvis-brain/job/clear")
def jarvis_brain_level8_clear_active_job():
    _j8_clear_active_context()
    return RedirectResponse("/jarvis-brain/job", status_code=303)


@app.get("/jarvis-brain/job.json")
def jarvis_brain_level8_active_job_json():
    active = _j8_active_context()
    items = _j8_active_job_items()
    summary = _j8_job_summary(active, items)

    return JSONResponse({
        "ok": True,
        "version": JARVIS_JOB_CENTER_VERSION,
        "active_context": active,
        "summary": summary,
        "items": items[:500],
    })


@app.get("/jarvis-brain/active-job", response_class=HTMLResponse)
def jarvis_brain_level8_active_job_alias(request: Request):
    return RedirectResponse("/jarvis-brain/job", status_code=303)

# ============================================================
# END JARVIS BRAIN LEVEL 8 ACTIVE JOB CENTER
# ============================================================


# ============================================================
# JARVIS BRAIN LEVEL 9 CREW FIELD FLOW
# Adds /jarvis-brain/crew without replacing Level 7 or Level 8.
# ============================================================

import os as _j9_os
import json as _j9_json
import html as _j9_html
from datetime import datetime as _j9_datetime, date as _j9_date

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_CREW_FLOW_VERSION = "level-9-crew-field-flow-2026-07-04"


def _j9_now():
    return _j9_datetime.now().isoformat(timespec="seconds")


def _j9_today():
    return _j9_date.today().isoformat()


def _j9_storage_dir():
    path = _j9_os.path.join(_j9_os.getcwd(), "jarvis_storage")
    _j9_os.makedirs(path, exist_ok=True)
    return path


def _j9_file(name):
    return _j9_os.path.join(_j9_storage_dir(), name)


def _j9_esc(value):
    return _j9_html.escape(str(value or ""))


def _j9_read_json(name, default=None):
    path = _j9_file(name)
    if not _j9_os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _j9_json.load(f)
    except Exception:
        return default


def _j9_write_json(name, data):
    with open(_j9_file(name), "w", encoding="utf-8") as f:
        _j9_json.dump(data, f, ensure_ascii=False, indent=2)


def _j9_read_jsonl_all(name):
    path = _j9_file(name)
    if not _j9_os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                items.append(_j9_json.loads(line.strip()))
            except Exception:
                pass
    return items


def _j9_user(request):
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


def _j9_name(user):
    return str((user or {}).get("name") or (user or {}).get("username") or (user or {}).get("email") or "Crew").strip()


def _j9_email(user):
    return str((user or {}).get("email") or "").strip()


def _j9_role(user):
    role = str((user or {}).get("role") or "admin").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j9_rows(sql, params=()):
    try:
        f = globals().get("rows")
        if callable(f):
            return f(sql, params) or []
    except Exception:
        pass
    return []


def _j9_exec(sql, params=()):
    try:
        f = globals().get("exec_sql")
        if callable(f):
            return f(sql, params)
    except Exception:
        pass
    return None


def _j9_columns(table):
    try:
        f = globals().get("table_columns")
        if callable(f):
            return list(f(table) or [])
    except Exception:
        pass
    return []


def _j9_table_exists(table):
    return bool(_j9_columns(table))


def _j9_active_context():
    return _j9_read_json("jarvis_active_context.json", {}) or {}


def _j9_today_memory():
    today = _j9_today()
    items = _j9_read_jsonl_all("jarvis_memory.jsonl")
    items.reverse()
    return [x for x in items if str(x.get("created_at") or "")[:10] == today]


def _j9_match_active_item(item, active):
    if not active:
        return False

    item_job_id = str(item.get("job_id") or "").strip()
    active_job_id = str(active.get("job_id") or "").strip()

    if item_job_id and active_job_id and item_job_id == active_job_id:
        return True

    item_client = str(item.get("client") or "").lower().strip()
    active_client = str(active.get("client") or "").lower().strip()

    item_address = str(item.get("address") or "").lower().strip()
    active_address = str(active.get("address") or "").lower().strip()

    if active_client and item_client and active_client == item_client:
        return True

    if active_address and item_address and active_address == item_address:
        return True

    return False


def _j9_active_job_memory():
    active = _j9_active_context()
    items = _j9_read_jsonl_all("jarvis_memory.jsonl")
    items.reverse()

    if not active:
        return []

    return [x for x in items if _j9_match_active_item(x, active)]


def _j9_employee_status(user):
    cols = _j9_columns("poolops2_employees")
    if not cols:
        return {"table": False, "matched": False, "clocked_in": False, "message": "Employee table not found."}

    name = _j9_name(user)
    email = _j9_email(user)

    where = []
    params = []

    if email and "email" in cols:
        where.append("email=?")
        params.append(email)

    if name and "name" in cols:
        where.append("name=?")
        params.append(name)

    if not where:
        return {"table": True, "matched": False, "clocked_in": False, "message": "Could not match employee by name or email."}

    try:
        row = _j9_rows(f"SELECT * FROM poolops2_employees WHERE {' OR '.join(where)} LIMIT 1", tuple(params))
        emp = row[0] if row else None
    except Exception:
        emp = None

    if not emp:
        return {"table": True, "matched": False, "clocked_in": False, "message": "Employee record not found."}

    clocked = False
    if "clocked_in" in cols:
        clocked = str(emp.get("clocked_in") or "").lower() in ("1", "true", "yes", "on")

    return {
        "table": True,
        "matched": True,
        "clocked_in": clocked,
        "name": emp.get("name") or name,
        "clocked_in_at": emp.get("clocked_in_at") or "",
        "last_seen_at": emp.get("last_seen_at") or "",
        "message": "Clocked in." if clocked else "Not clocked in.",
    }


def _j9_crew_steps(user):
    active = _j9_active_context()
    status = _j9_employee_status(user)
    today = _j9_today_memory()
    job_items = _j9_active_job_memory()

    field_logs = [x for x in job_items if str(x.get("category") or "") == "Field Log"]
    billing = [x for x in job_items if str(x.get("category") or "") == "Billing Note"]
    materials = [x for x in job_items if str(x.get("category") or "") == "Material Needed"]
    problems = [x for x in job_items if str(x.get("category") or "") == "Problem Found"]

    steps = []

    steps.append({
        "num": 1,
        "title": "Set the active job",
        "status": "done" if active else "needed",
        "detail": "Tell Jarvis where you are before saving job notes.",
        "command": "Jarvis, set active job to ",
    })

    steps.append({
        "num": 2,
        "title": "Clock in",
        "status": "done" if status.get("clocked_in") else "needed",
        "detail": status.get("message") or "Clock status unknown.",
        "command": "Jarvis, clock me in",
    })

    steps.append({
        "num": 3,
        "title": "Take arrival photos",
        "status": "prompt",
        "detail": "Use Photos page for arrival/progress/completion photos. This protects Mike and the job history.",
        "href": "/photos",
    })

    steps.append({
        "num": 4,
        "title": "Log the work",
        "status": "done" if field_logs else "needed",
        "detail": f"{len(field_logs)} field log item(s) captured for the active job.",
        "command": "Jarvis, field log: ",
    })

    steps.append({
        "num": 5,
        "title": "Add materials, problems, or billing notes",
        "status": "prompt",
        "detail": f"Materials: {len(materials)} ? Problems: {len(problems)} ? Billing: {len(billing)}",
        "command": "Jarvis, material needed: ",
    })

    steps.append({
        "num": 6,
        "title": "Take completion photos",
        "status": "prompt",
        "detail": "Before leaving, take completion photos and anything that protects the story.",
        "href": "/photos",
    })

    steps.append({
        "num": 7,
        "title": "Clock out",
        "status": "needed" if status.get("clocked_in") else "prompt",
        "detail": "Clock out after the field log and photos are handled.",
        "command": "Jarvis, clock me out",
    })

    return {
        "active_job": active,
        "employee_status": status,
        "today_items": today[:25],
        "active_job_items": job_items[:50],
        "steps": steps,
    }


def _j9_render_step(step):
    status = str(step.get("status") or "prompt")
    status_label = {
        "done": "DONE",
        "needed": "NEEDED",
        "prompt": "PROMPT",
    }.get(status, status.upper())

    action = ""
    if step.get("command"):
        action = f"<button class='small' onclick=\"fillCmd('{_j9_esc(step.get('command'))}')\">Use Command</button>"
    elif step.get("href"):
        action = f"<a class='buttonlink' href='{_j9_esc(step.get('href'))}'>Open</a>"

    return f"""
    <div class="flow-step {status}">
      <div class="step-num">{_j9_esc(step.get('num'))}</div>
      <div class="step-main">
        <div class="step-top">
          <b>{_j9_esc(step.get('title'))}</b>
          <span>{_j9_esc(status_label)}</span>
        </div>
        <div class="step-detail">{_j9_esc(step.get('detail'))}</div>
        {action}
      </div>
    </div>
    """


def _j9_render_memory_item(item):
    cat = _j9_esc(item.get("category"))
    created = _j9_esc(item.get("created_at"))
    body = _j9_esc(item.get("body"))
    client = _j9_esc(item.get("client"))
    address = _j9_esc(item.get("address") or item.get("property"))

    context = ""
    if client or address:
        context = f"<div class='mem-meta'>Job: {client} ? {address}</div>"

    return f"""
    <div class="mem-item">
      <div class="mem-top"><b>{cat}</b><span>{created}</span></div>
      <div class="mem-body">{body}</div>
      {context}
    </div>
    """


@app.get("/jarvis-brain/crew", response_class=HTMLResponse)
def jarvis_brain_level9_crew_flow(request: Request):
    user = _j9_user(request)
    name = _j9_name(user).split()[0]
    role = _j9_role(user)
    data = _j9_crew_steps(user)
    active = data["active_job"]
    emp = data["employee_status"]

    active_html = "<p>No active job set yet. Say: <b>Jarvis, set active job to Alexander</b>.</p>"
    if active:
        active_html = f"""
        <p><b>{_j9_esc(active.get('title') or active.get('client') or active.get('address'))}</b></p>
        <p>{_j9_esc(active.get('address'))}</p>
        <p>Type: {_j9_esc(active.get('job_type'))} ? Status: {_j9_esc(active.get('status'))}</p>
        """

    steps_html = "".join([_j9_render_step(x) for x in data["steps"]])

    job_memory_html = ""
    for item in data["active_job_items"][:20]:
        job_memory_html += _j9_render_memory_item(item)
    if not job_memory_html:
        job_memory_html = "<p>No memory tied to the active job yet.</p>"

    today_html = ""
    for item in data["today_items"][:15]:
        today_html += _j9_render_memory_item(item)
    if not today_html:
        today_html = "<p>No Jarvis items captured today yet.</p>"

    clock_text = "Clocked In" if emp.get("clocked_in") else "Not Clocked In"

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis Crew Flow</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }}
    .wrap {{ max-width:1180px; margin:0 auto; padding:24px; }}
    .hero {{ background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:24px; box-shadow:0 20px 60px rgba(0,0,0,.45); }}
    h1 {{ margin:0 0 8px; font-size:34px; letter-spacing:.08em; }}
    .sub {{ color:#d9b56d; margin-bottom:18px; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    @media(max-width:900px) {{ .grid {{ grid-template-columns:1fr; }} }}
    .stats {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:16px 0; }}
    @media(max-width:700px) {{ .stats {{ grid-template-columns:1fr; }} }}
    .stat {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:14px; }}
    .stat b {{ font-size:24px; color:#d9b56d; }}
    .card {{ background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; margin-top:16px; }}
    textarea {{ width:100%; min-height:120px; box-sizing:border-box; border-radius:14px; border:1px solid #6b4b1f; background:#05070b; color:#fff; padding:14px; font-size:16px; }}
    button, .buttonlink {{ display:inline-block; margin-top:10px; padding:12px 16px; border:0; border-radius:12px; background:#b8873a; color:#111; font-weight:900; cursor:pointer; text-decoration:none; }}
    button.small {{ padding:8px 11px; font-size:13px; }}
    .reply {{ margin-top:12px; padding:13px; border-radius:12px; background:#05070b; border:1px solid #2d2113; min-height:24px; line-height:1.45; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:9px; margin-top:10px; }}
    .chip {{ border:1px solid #6b4b1f; border-radius:999px; padding:9px 11px; background:#070a0f; color:#f5efe3; cursor:pointer; }}
    .flow-step {{ display:flex; gap:12px; background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:13px; margin:10px 0; }}
    .flow-step.done {{ border-color:#496b2a; }}
    .flow-step.needed {{ border-color:#8a392f; }}
    .step-num {{ min-width:38px; height:38px; border-radius:999px; display:flex; align-items:center; justify-content:center; background:#b8873a; color:#111; font-weight:900; }}
    .step-main {{ flex:1; }}
    .step-top {{ display:flex; justify-content:space-between; gap:12px; color:#d9b56d; }}
    .step-detail {{ margin-top:8px; color:#e8dcc7; line-height:1.4; }}
    .mem-item {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:13px; margin:10px 0; }}
    .mem-top {{ display:flex; justify-content:space-between; gap:12px; color:#d9b56d; font-size:13px; }}
    .mem-body {{ margin-top:8px; color:#e8dcc7; line-height:1.4; }}
    .mem-meta {{ margin-top:8px; color:#a99572; font-size:13px; }}
    a {{ color:#d9a64a; }}
    .result {{ padding:10px; border:1px solid #2d2113; border-radius:12px; margin:8px 0; background:#070a0f; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>J.A.R.V.I.S. CREW FLOW</h1>
    <div class="sub">Good to go, {_j9_esc(name)}. This page tells the crew what to do next. Role: {_j9_esc(role)}.</div>

    <div class="stats">
      <div class="stat"><b>{_j9_esc(clock_text)}</b><br>Clock status</div>
      <div class="stat"><b>{len(data['active_job_items'])}</b><br>Active job notes</div>
      <div class="stat"><b>{len(data['today_items'])}</b><br>Captured today</div>
    </div>

    <div class="grid">
      <div>
        <div class="card">
          <h2>Command</h2>
          <textarea id="cmd" placeholder="Jarvis, field log: "></textarea>
          <button onclick="sendCmd()">Send</button>
          <button onclick="startVoice()">?? Voice</button>
          <button onclick="speakLast()">?? Read Back</button>
          <div class="reply" id="reply">Waiting for crew command.</div>

          <div class="chips">
            <button class="chip" onclick="fillCmd('Jarvis, set active job to ')">Set Job</button>
            <button class="chip" onclick="fillCmd('Jarvis, clock me in')">Clock In</button>
            <button class="chip" onclick="fillCmd('Jarvis, field log: ')">Field Log</button>
            <button class="chip" onclick="fillCmd('Jarvis, material needed: ')">Material</button>
            <button class="chip" onclick="fillCmd('Jarvis, problem found: ')">Problem</button>
            <button class="chip" onclick="fillCmd('Jarvis, clock me out')">Clock Out</button>
          </div>
        </div>

        <div class="card">
          <h2>Active Job</h2>
          {active_html}
        </div>

        <div class="card">
          <h2>Step-by-Step Crew Flow</h2>
          {steps_html}
        </div>

        <div class="card">
          <h2>Links</h2>
          <p>
            <a href="/jarvis-brain">Jarvis Brain</a>
            |
            <a href="/jarvis-brain/job">Active Job</a>
            |
            <a href="/jarvis-brain/desk">Command Desk</a>
            |
            <a href="/photos">Photos</a>
            |
            <a href="/field-logs">Field Logs</a>
            |
            <a href="/">Home</a>
          </p>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>Active Job Memory</h2>
          {job_memory_html}
        </div>

        <div class="card">
          <h2>Today?s Captured Items</h2>
          {today_html}
        </div>
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


@app.get("/jarvis-brain/crew.json")
def jarvis_brain_level9_crew_json(request: Request):
    user = _j9_user(request)
    return JSONResponse({
        "ok": True,
        "version": JARVIS_CREW_FLOW_VERSION,
        "crew_flow": _j9_crew_steps(user),
        "tables_seen": {
            "poolops2_employees": _j9_table_exists("poolops2_employees"),
            "field_logs": _j9_table_exists("field_logs"),
            "poolops2_jobs": _j9_table_exists("poolops2_jobs"),
        },
    })


@app.get("/crew/jarvis", response_class=HTMLResponse)
def jarvis_brain_level9_crew_alias(request: Request):
    return RedirectResponse("/jarvis-brain/crew", status_code=303)


@app.get("/employee/jarvis", response_class=HTMLResponse)
def jarvis_brain_level9_employee_alias(request: Request):
    return RedirectResponse("/jarvis-brain/crew", status_code=303)

# ============================================================
# END JARVIS BRAIN LEVEL 9 CREW FIELD FLOW
# ============================================================


# ============================================================
# JARVIS BRAIN LEVEL 10 ROLE FRONT DOOR + CLIENT FLOW
# Adds /jarvis-brain/start and /jarvis-brain/client.
# Does not replace Levels 7, 8, or 9.
# ============================================================

import os as _j10_os
import json as _j10_json
import html as _j10_html
from datetime import datetime as _j10_datetime, date as _j10_date

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_ROLE_FRONT_DOOR_VERSION = "level-10-role-frontdoor-client-flow-2026-07-04"


def _j10_now():
    return _j10_datetime.now().isoformat(timespec="seconds")


def _j10_today():
    return _j10_date.today().isoformat()


def _j10_storage_dir():
    path = _j10_os.path.join(_j10_os.getcwd(), "jarvis_storage")
    _j10_os.makedirs(path, exist_ok=True)
    return path


def _j10_file(name):
    return _j10_os.path.join(_j10_storage_dir(), name)


def _j10_esc(value):
    return _j10_html.escape(str(value or ""))


def _j10_write_jsonl(name, item):
    item = dict(item or {})
    item.setdefault("created_at", _j10_now())
    with open(_j10_file(name), "a", encoding="utf-8") as f:
        f.write(_j10_json.dumps(item, ensure_ascii=False) + "\n")


def _j10_read_jsonl_all(name):
    path = _j10_file(name)
    if not _j10_os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                items.append(_j10_json.loads(line.strip()))
            except Exception:
                pass
    return items


def _j10_user(request):
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


def _j10_name(user):
    return str((user or {}).get("name") or (user or {}).get("username") or (user or {}).get("email") or "Client").strip()


def _j10_email(user):
    return str((user or {}).get("email") or "").strip()


def _j10_role(user):
    role = str((user or {}).get("role") or "admin").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j10_rows(sql, params=()):
    try:
        f = globals().get("rows")
        if callable(f):
            return f(sql, params) or []
    except Exception:
        pass
    return []


def _j10_exec(sql, params=()):
    try:
        f = globals().get("exec_sql")
        if callable(f):
            return f(sql, params)
    except Exception:
        pass
    return None


def _j10_columns(table):
    try:
        f = globals().get("table_columns")
        if callable(f):
            return list(f(table) or [])
    except Exception:
        pass
    return []


def _j10_table_exists(table):
    return bool(_j10_columns(table))


def _j10_insert_existing(table, data):
    cols = _j10_columns(table)
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
    _j10_exec(sql, tuple(final[k] for k in names))
    return True


def _j10_client_filter_conditions(table, user):
    cols = _j10_columns(table)
    name = _j10_name(user)
    email = _j10_email(user)

    where = []
    params = []

    if "client" in cols and name:
        where.append("CAST(client AS TEXT) LIKE ?")
        params.append(f"%{name}%")

    if "client_name" in cols and name:
        where.append("CAST(client_name AS TEXT) LIKE ?")
        params.append(f"%{name}%")

    if "name" in cols and name and table == "poolops2_clients":
        where.append("CAST(name AS TEXT) LIKE ?")
        params.append(f"%{name}%")

    if "email" in cols and email:
        where.append("CAST(email AS TEXT) LIKE ?")
        params.append(f"%{email}%")

    if "client_email" in cols and email:
        where.append("CAST(client_email AS TEXT) LIKE ?")
        params.append(f"%{email}%")

    if not where:
        return "", ()

    return " OR ".join(where), tuple(params)


def _j10_client_jobs(user):
    if not _j10_table_exists("poolops2_jobs"):
        return []

    where, params = _j10_client_filter_conditions("poolops2_jobs", user)
    if where:
        return _j10_rows(f"SELECT * FROM poolops2_jobs WHERE {where} ORDER BY id DESC LIMIT 12", params)

    return []


def _j10_client_properties(user):
    if not _j10_table_exists("poolops2_properties"):
        return []

    where, params = _j10_client_filter_conditions("poolops2_properties", user)
    if where:
        return _j10_rows(f"SELECT * FROM poolops2_properties WHERE {where} ORDER BY id DESC LIMIT 12", params)

    return []


def _j10_client_photos(user):
    if not _j10_table_exists("poolops2_photo_logs"):
        return []

    where, params = _j10_client_filter_conditions("poolops2_photo_logs", user)
    if where:
        return _j10_rows(f"SELECT * FROM poolops2_photo_logs WHERE {where} ORDER BY id DESC LIMIT 12", params)

    return []


def _j10_client_requests(user):
    name = _j10_name(user).lower()
    email = _j10_email(user).lower()

    items = _j10_read_jsonl_all("jarvis_client_requests.jsonl")
    items.reverse()

    if not name and not email:
        return items[:20]

    out = []
    for item in items:
        item_name = str(item.get("client_name") or "").lower()
        item_email = str(item.get("client_email") or "").lower()
        if (name and name in item_name) or (email and email == item_email):
            out.append(item)

    return out[:20]


def _j10_save_client_request(request, message, request_type="Project Question"):
    user = _j10_user(request)
    client_name = _j10_name(user)
    client_email = _j10_email(user)

    title = str(message or "").strip()[:90] or "Client Request"
    if len(str(message or "")) > 90:
        title += "..."

    item = {
        "created_at": _j10_now(),
        "source": "Client Jarvis",
        "category": "Client Request",
        "request_type": request_type or "Project Question",
        "title": title,
        "body": str(message or "").strip(),
        "client_name": client_name,
        "client_email": client_email,
        "status": "Open",
        "priority": "Normal",
    }

    _j10_write_jsonl("jarvis_client_requests.jsonl", item)

    memory_item = {
        "created_at": item["created_at"],
        "created_by": client_name,
        "user_role": _j10_role(user),
        "intent": "client_request",
        "category": "Client Request",
        "priority": "Normal",
        "title": title,
        "body": item["body"],
        "status": "Open",
        "reply": "Client request saved.",
        "client": client_name,
        "client_email": client_email,
        "source": "Client Jarvis",
    }

    _j10_write_jsonl("jarvis_memory.jsonl", memory_item)

    office_saved = _j10_insert_existing("invisible_office_items", {
        "source": "Client Jarvis",
        "category": "Client Request",
        "title": title,
        "body": item["body"],
        "client": client_name,
        "priority": "Normal",
        "status": "Open",
        "created_by": client_name,
        "created_at": item["created_at"],
    })

    item["invisible_saved"] = bool(office_saved)
    return item


def _j10_render_row(title, detail="", href=""):
    link = ""
    if href:
        link = f"<p><a href='{_j10_esc(href)}'>Open</a></p>"

    return f"""
    <div class="item">
      <div class="item-title">{_j10_esc(title)}</div>
      <div class="item-detail">{_j10_esc(detail)}</div>
      {link}
    </div>
    """


def _j10_render_job(job):
    title = job.get("property") or job.get("client") or job.get("address") or f"Job #{job.get('id')}"
    detail = job.get("job_type") or job.get("status") or job.get("notes") or ""
    return _j10_render_row(title, detail)


def _j10_render_property(prop):
    title = prop.get("property_name") or prop.get("address") or prop.get("client") or f"Property #{prop.get('id')}"
    detail = prop.get("address") or prop.get("equipment_notes") or prop.get("notes") or ""
    return _j10_render_row(title, detail)


def _j10_render_request(item):
    title = item.get("title") or "Client Request"
    detail = f"{item.get('request_type') or 'Request'} ? {item.get('created_at') or ''} ? {item.get('status') or 'Open'}"
    body = item.get("body") or ""

    return f"""
    <div class="item">
      <div class="item-title">{_j10_esc(title)}</div>
      <div class="item-detail">{_j10_esc(detail)}</div>
      <p>{_j10_esc(body)}</p>
    </div>
    """


@app.get("/jarvis-brain/start")
def jarvis_brain_level10_role_front_door(request: Request):
    user = _j10_user(request)
    role = _j10_role(user)

    if role == "client":
        return RedirectResponse("/jarvis-brain/client", status_code=303)

    if role == "crew":
        return RedirectResponse("/jarvis-brain/crew", status_code=303)

    return RedirectResponse("/jarvis-brain", status_code=303)


@app.get("/jarvis-start")
def jarvis_brain_level10_start_alias(request: Request):
    return RedirectResponse("/jarvis-brain/start", status_code=303)


@app.get("/jarvis-brain/client", response_class=HTMLResponse)
def jarvis_brain_level10_client_page(request: Request):
    user = _j10_user(request)
    name = _j10_name(user).split()[0]
    role = _j10_role(user)

    jobs = _j10_client_jobs(user)
    properties = _j10_client_properties(user)
    photos = _j10_client_photos(user)
    requests = _j10_client_requests(user)

    jobs_html = "".join([_j10_render_job(x) for x in jobs[:8]]) or "<p>No project jobs are visible to this login yet.</p>"
    props_html = "".join([_j10_render_property(x) for x in properties[:8]]) or "<p>No properties are visible to this login yet.</p>"
    requests_html = "".join([_j10_render_request(x) for x in requests[:8]]) or "<p>No client requests saved yet.</p>"

    photo_html = ""
    for p in photos[:8]:
        title = p.get("title") or p.get("filename") or p.get("caption") or "Photo"
        detail = p.get("created_at") or p.get("date") or p.get("client") or ""
        url = p.get("url") or p.get("image_url") or p.get("public_url") or ""
        photo_html += _j10_render_row(title, detail, url)
    if not photo_html:
        photo_html = "<p>No approved photo records are visible to this login yet.</p>"

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Client Jarvis</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }}
    .wrap {{ max-width:1100px; margin:0 auto; padding:24px; }}
    .hero {{ background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:24px; box-shadow:0 20px 60px rgba(0,0,0,.45); }}
    h1 {{ margin:0 0 8px; font-size:34px; letter-spacing:.08em; }}
    .sub {{ color:#d9b56d; margin-bottom:18px; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    @media(max-width:850px) {{ .grid {{ grid-template-columns:1fr; }} }}
    .card {{ background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; margin-top:16px; }}
    textarea, select {{ width:100%; box-sizing:border-box; border-radius:14px; border:1px solid #6b4b1f; background:#05070b; color:#fff; padding:14px; font-size:16px; }}
    textarea {{ min-height:125px; }}
    button {{ margin-top:10px; padding:12px 16px; border:0; border-radius:12px; background:#b8873a; color:#111; font-weight:900; cursor:pointer; }}
    .item {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:13px; margin:10px 0; }}
    .item-title {{ font-weight:900; color:#f5efe3; }}
    .item-detail {{ color:#d9b56d; font-size:13px; margin-top:6px; }}
    a {{ color:#d9a64a; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>CLIENT J.A.R.V.I.S.</h1>
    <div class="sub">Welcome, {_j10_esc(name)}. This page is client-safe. Role: {_j10_esc(role)}.</div>

    <div class="grid">
      <div>
        <div class="card">
          <h2>Send Mike a Request</h2>
          <form method="post" action="/jarvis-brain/client/request">
            <label>Request Type</label>
            <select name="request_type">
              <option>Project Question</option>
              <option>Service Request</option>
              <option>Schedule Question</option>
              <option>Photo / Progress Question</option>
              <option>Billing Question</option>
              <option>Warranty / Issue</option>
            </select>
            <br><br>
            <label>Message</label>
            <textarea name="message" placeholder="Tell Mike what you need..."></textarea>
            <button type="submit">Send Request</button>
          </form>
        </div>

        <div class="card">
          <h2>Your Requests</h2>
          {requests_html}
        </div>

        <div class="card">
          <h2>Links</h2>
          <p>
            <a href="/client-portal">Client Portal</a>
            |
            <a href="/jarvis-brain/client.json">Client JSON</a>
            |
            <a href="/jarvis-brain/start">Jarvis Start</a>
            |
            <a href="/">Home</a>
          </p>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>Visible Projects</h2>
          {jobs_html}
        </div>

        <div class="card">
          <h2>Visible Properties</h2>
          {props_html}
        </div>

        <div class="card">
          <h2>Visible Photos</h2>
          {photo_html}
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""
    return HTMLResponse(html)


@app.post("/jarvis-brain/client/request")
async def jarvis_brain_level10_client_request(request: Request):
    try:
        form = await request.form()
        message = str(form.get("message") or "").strip()
        request_type = str(form.get("request_type") or "Project Question").strip()
    except Exception:
        message = ""
        request_type = "Project Question"

    if message:
        _j10_save_client_request(request, message, request_type)

    return RedirectResponse("/jarvis-brain/client", status_code=303)


@app.get("/jarvis-brain/client.json")
def jarvis_brain_level10_client_json(request: Request):
    user = _j10_user(request)

    return JSONResponse({
        "ok": True,
        "version": JARVIS_ROLE_FRONT_DOOR_VERSION,
        "role": _j10_role(user),
        "client_name": _j10_name(user),
        "client_email": _j10_email(user),
        "jobs": _j10_client_jobs(user),
        "properties": _j10_client_properties(user),
        "photos": _j10_client_photos(user),
        "requests": _j10_client_requests(user),
        "tables_seen": {
            "poolops2_jobs": _j10_table_exists("poolops2_jobs"),
            "poolops2_properties": _j10_table_exists("poolops2_properties"),
            "poolops2_photo_logs": _j10_table_exists("poolops2_photo_logs"),
            "invisible_office_items": _j10_table_exists("invisible_office_items"),
        },
    })


@app.get("/client/jarvis", response_class=HTMLResponse)
def jarvis_brain_level10_client_alias_one(request: Request):
    return RedirectResponse("/jarvis-brain/client", status_code=303)


@app.get("/client-jarvis", response_class=HTMLResponse)
def jarvis_brain_level10_client_alias_two(request: Request):
    return RedirectResponse("/jarvis-brain/client", status_code=303)

# ============================================================
# END JARVIS BRAIN LEVEL 10 ROLE FRONT DOOR + CLIENT FLOW
# ============================================================


# ============================================================
# JARVIS BRAIN LEVEL 11 LAUNCH PAD
# Adds /jarvis-brain/launch and smarter /jarvis redirect.
# Does not replace Levels 7, 8, 9, or 10.
# ============================================================

import os as _j11_os
import json as _j11_json
import html as _j11_html
from datetime import datetime as _j11_datetime

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_LAUNCH_VERSION = "level-11-launch-pad-2026-07-04"


def _j11_now():
    return _j11_datetime.now().isoformat(timespec="seconds")


def _j11_storage_dir():
    path = _j11_os.path.join(_j11_os.getcwd(), "jarvis_storage")
    _j11_os.makedirs(path, exist_ok=True)
    return path


def _j11_file(name):
    return _j11_os.path.join(_j11_storage_dir(), name)


def _j11_read_json(name, default=None):
    path = _j11_file(name)
    if not _j11_os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _j11_json.load(f)
    except Exception:
        return default


def _j11_read_jsonl_all(name):
    path = _j11_file(name)
    if not _j11_os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                items.append(_j11_json.loads(line.strip()))
            except Exception:
                pass
    return items


def _j11_esc(value):
    return _j11_html.escape(str(value or ""))


def _j11_user(request):
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


def _j11_name(user):
    return str((user or {}).get("name") or (user or {}).get("username") or (user or {}).get("email") or "Mike").strip()


def _j11_role(user):
    role = str((user or {}).get("role") or "admin").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j11_columns(table):
    try:
        f = globals().get("table_columns")
        if callable(f):
            return list(f(table) or [])
    except Exception:
        pass
    return []


def _j11_rows(sql, params=()):
    try:
        f = globals().get("rows")
        if callable(f):
            return f(sql, params) or []
    except Exception:
        pass
    return []


def _j11_table_count(table):
    cols = _j11_columns(table)
    if not cols:
        return None
    try:
        r = _j11_rows(f"SELECT COUNT(*) AS c FROM {table}", ())
        if r:
            first = r[0]
            return first.get("c") if hasattr(first, "get") else list(first)[0]
    except Exception:
        pass
    return None


def _j11_active_context():
    return _j11_read_json("jarvis_active_context.json", {}) or {}


def _j11_memory_counts():
    items = _j11_read_jsonl_all("jarvis_memory.jsonl")
    open_items = []
    for item in items:
        status = str(item.get("status") or "Open").lower()
        if status not in ("done", "closed", "complete", "completed"):
            open_items.append(item)

    counts = {
        "total": len(items),
        "open": len(open_items),
        "billing": 0,
        "materials": 0,
        "followups": 0,
        "problems": 0,
        "field_logs": 0,
        "client_requests": 0,
    }

    for item in open_items:
        cat = str(item.get("category") or "")
        if cat == "Billing Note":
            counts["billing"] += 1
        elif cat == "Material Needed":
            counts["materials"] += 1
        elif cat == "Follow Up":
            counts["followups"] += 1
        elif cat == "Problem Found":
            counts["problems"] += 1
        elif cat == "Field Log":
            counts["field_logs"] += 1
        elif cat == "Client Request":
            counts["client_requests"] += 1

    return counts


def _j11_cards_for_role(role):
    base = []

    if role == "client":
        return [
            {
                "title": "Client Jarvis",
                "desc": "View visible project info and send Mike a request.",
                "href": "/jarvis-brain/client",
                "tag": "Client Safe",
            },
            {
                "title": "Client Portal",
                "desc": "Open the standard client portal.",
                "href": "/client-portal",
                "tag": "Portal",
            },
            {
                "title": "Jarvis Start",
                "desc": "Smart role front door.",
                "href": "/jarvis-brain/start",
                "tag": "Start",
            },
        ]

    if role == "crew":
        return [
            {
                "title": "Crew Flow",
                "desc": "Step-by-step field workflow: set job, clock in, photos, logs, materials, clock out.",
                "href": "/jarvis-brain/crew",
                "tag": "Crew",
            },
            {
                "title": "Active Job",
                "desc": "The job brain for the current active job.",
                "href": "/jarvis-brain/job",
                "tag": "Job",
            },
            {
                "title": "Photos",
                "desc": "Upload arrival, progress, and completion photos.",
                "href": "/photos",
                "tag": "Protect",
            },
            {
                "title": "Field Logs",
                "desc": "Open field log page.",
                "href": "/field-logs",
                "tag": "Logs",
            },
            {
                "title": "Jarvis Brain",
                "desc": "Main command page.",
                "href": "/jarvis-brain",
                "tag": "Brain",
            },
        ]

    return [
        {
            "title": "Mike Brain",
            "desc": "Main Jarvis command center: voice, search, memory, active job, briefing.",
            "href": "/jarvis-brain",
            "tag": "Admin",
        },
        {
            "title": "Command Desk",
            "desc": "Open billing, material, follow-up, problem, field-log, and client request queue.",
            "href": "/jarvis-brain/desk",
            "tag": "Queue",
        },
        {
            "title": "Active Job",
            "desc": "Job-specific brain for the active job.",
            "href": "/jarvis-brain/job",
            "tag": "Job",
        },
        {
            "title": "Crew Flow",
            "desc": "See exactly what the crew page looks like and how they are prompted.",
            "href": "/jarvis-brain/crew",
            "tag": "Crew",
        },
        {
            "title": "Client Jarvis",
            "desc": "Client-safe request and project page.",
            "href": "/jarvis-brain/client",
            "tag": "Client",
        },
        {
            "title": "Invisible Office",
            "desc": "Office queue where Jarvis files billing notes, follow-ups, problems, and closeouts.",
            "href": "/invisible-office",
            "tag": "Office",
        },
        {
            "title": "Photos",
            "desc": "Arrival, progress, completion, and job protection photos.",
            "href": "/photos",
            "tag": "Photos",
        },
        {
            "title": "Field Logs",
            "desc": "Work completed, problems, materials, next steps.",
            "href": "/field-logs",
            "tag": "Logs",
        },
        {
            "title": "Jobs",
            "desc": "Open your jobs list.",
            "href": "/jobs",
            "tag": "Jobs",
        },
        {
            "title": "Schedule",
            "desc": "Open schedule/calendar.",
            "href": "/schedule",
            "tag": "Calendar",
        },
    ]


@app.middleware("http")
async def jarvis_level11_launch_takeover(request, call_next):
    # This newer middleware makes the old /jarvis entry go to the role-aware front door.
    if request.url.path == "/jarvis":
        return RedirectResponse("/jarvis-brain/start", status_code=303)
    return await call_next(request)


@app.get("/jarvis-brain/launch", response_class=HTMLResponse)
def jarvis_brain_level11_launch_pad(request: Request):
    user = _j11_user(request)
    name = _j11_name(user).split()[0]
    role = _j11_role(user)
    active = _j11_active_context()
    counts = _j11_memory_counts()
    cards = _j11_cards_for_role(role)

    card_html = ""
    for card in cards:
        card_html += f"""
        <a class="tile" href="{_j11_esc(card.get('href'))}">
          <div class="tag">{_j11_esc(card.get('tag'))}</div>
          <h2>{_j11_esc(card.get('title'))}</h2>
          <p>{_j11_esc(card.get('desc'))}</p>
        </a>
        """

    active_html = "<p>No active job set.</p>"
    if active:
        active_html = f"""
        <p><b>{_j11_esc(active.get('title') or active.get('client') or active.get('address'))}</b></p>
        <p>{_j11_esc(active.get('address'))}</p>
        <p>Status: {_j11_esc(active.get('status'))} ? Type: {_j11_esc(active.get('job_type'))}</p>
        """

    jobs_count = _j11_table_count("poolops2_jobs")
    clients_count = _j11_table_count("poolops2_clients")
    props_count = _j11_table_count("poolops2_properties")
    office_count = _j11_table_count("invisible_office_items")
    logs_count = _j11_table_count("field_logs")

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis Launch Pad</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }}
    .wrap {{ max-width:1220px; margin:0 auto; padding:26px; }}
    .hero {{ background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:24px; box-shadow:0 20px 60px rgba(0,0,0,.45); }}
    h1 {{ margin:0 0 8px; font-size:36px; letter-spacing:.08em; }}
    .sub {{ color:#d9b56d; margin-bottom:20px; }}
    .stats {{ display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin:16px 0; }}
    @media(max-width:950px) {{ .stats {{ grid-template-columns:repeat(2,1fr); }} }}
    .stat {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:14px; }}
    .stat b {{ font-size:26px; color:#d9b56d; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    @media(max-width:900px) {{ .grid {{ grid-template-columns:1fr; }} }}
    .tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:14px; margin-top:16px; }}
    .tile {{ display:block; text-decoration:none; color:#f5efe3; background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; min-height:130px; }}
    .tile:hover {{ border-color:#b8873a; transform:translateY(-1px); }}
    .tile h2 {{ margin:8px 0; }}
    .tile p {{ color:#e8dcc7; line-height:1.4; }}
    .tag {{ display:inline-block; padding:6px 10px; border:1px solid #6b4b1f; border-radius:999px; color:#d9b56d; font-size:12px; }}
    .card {{ background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; margin-top:16px; }}
    a {{ color:#d9a64a; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>J.A.R.V.I.S. LAUNCH PAD</h1>
    <div class="sub">Good to go, {_j11_esc(name)}. This is the clean front door. Role: {_j11_esc(role)}.</div>

    <div class="stats">
      <div class="stat"><b>{counts['open']}</b><br>Open brain items</div>
      <div class="stat"><b>{counts['billing']}</b><br>Billing</div>
      <div class="stat"><b>{counts['materials']}</b><br>Materials</div>
      <div class="stat"><b>{counts['problems']}</b><br>Problems</div>
      <div class="stat"><b>{counts['field_logs']}</b><br>Field logs</div>
      <div class="stat"><b>{counts['client_requests']}</b><br>Client requests</div>
    </div>

    <div class="grid">
      <div class="card">
        <h2>Active Job</h2>
        {active_html}
        <p><a href="/jarvis-brain/job">Open Active Job Center</a></p>
      </div>

      <div class="card">
        <h2>System Snapshot</h2>
        <p>Jobs: {_j11_esc(jobs_count)} ? Clients: {_j11_esc(clients_count)} ? Properties: {_j11_esc(props_count)}</p>
        <p>Invisible Office: {_j11_esc(office_count)} ? Field Logs: {_j11_esc(logs_count)}</p>
        <p>Version: {_j11_esc(JARVIS_LAUNCH_VERSION)}</p>
      </div>
    </div>

    <div class="tiles">
      {card_html}
    </div>
  </div>
</div>
</body>
</html>
"""
    return HTMLResponse(html)


@app.get("/jarvis-launch", response_class=HTMLResponse)
def jarvis_brain_level11_launch_alias(request: Request):
    return RedirectResponse("/jarvis-brain/launch", status_code=303)


@app.get("/jarvis-brain/launch.json")
def jarvis_brain_level11_launch_json(request: Request):
    user = _j11_user(request)
    role = _j11_role(user)

    return JSONResponse({
        "ok": True,
        "version": JARVIS_LAUNCH_VERSION,
        "role": role,
        "name": _j11_name(user),
        "active_context": _j11_active_context(),
        "memory_counts": _j11_memory_counts(),
        "tables": {
            "jobs": _j11_table_count("poolops2_jobs"),
            "clients": _j11_table_count("poolops2_clients"),
            "properties": _j11_table_count("poolops2_properties"),
            "invisible_office": _j11_table_count("invisible_office_items"),
            "field_logs": _j11_table_count("field_logs"),
        },
        "cards": _j11_cards_for_role(role),
    })


# ============================================================
# END JARVIS BRAIN LEVEL 11 LAUNCH PAD
# ============================================================


# ============================================================
# JARVIS BRAIN LEVEL 12 HELP + SYSTEM CHECK
# Adds /jarvis-brain/help and /jarvis-brain/system.
# Safe add-on only.
# ============================================================

import os as _j12_os
import json as _j12_json
import html as _j12_html
from datetime import datetime as _j12_datetime

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_HELP_SYSTEM_VERSION = "level-12-help-system-check-2026-07-04"


def _j12_now():
    return _j12_datetime.now().isoformat(timespec="seconds")


def _j12_storage_dir():
    path = _j12_os.path.join(_j12_os.getcwd(), "jarvis_storage")
    _j12_os.makedirs(path, exist_ok=True)
    return path


def _j12_file(name):
    return _j12_os.path.join(_j12_storage_dir(), name)


def _j12_esc(value):
    return _j12_html.escape(str(value or ""))


def _j12_read_jsonl_all(name):
    path = _j12_file(name)
    if not _j12_os.path.exists(path):
        return []

    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                items.append(_j12_json.loads(line.strip()))
            except Exception:
                pass
    return items


def _j12_user(request):
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


def _j12_name(user):
    return str((user or {}).get("name") or (user or {}).get("username") or (user or {}).get("email") or "Mike").strip()


def _j12_role(user):
    role = str((user or {}).get("role") or "admin").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j12_rows(sql, params=()):
    try:
        f = globals().get("rows")
        if callable(f):
            return f(sql, params) or []
    except Exception:
        pass
    return []


def _j12_columns(table):
    try:
        f = globals().get("table_columns")
        if callable(f):
            return list(f(table) or [])
    except Exception:
        pass
    return []


def _j12_table_count(table):
    cols = _j12_columns(table)
    if not cols:
        return None

    try:
        r = _j12_rows(f"SELECT COUNT(*) AS c FROM {table}", ())
        if r:
            first = r[0]
            return first.get("c") if hasattr(first, "get") else list(first)[0]
    except Exception:
        pass

    return None


def _j12_route_methods(path):
    methods = []
    try:
        for route in app.routes:
            if getattr(route, "path", "") == path:
                for m in sorted(getattr(route, "methods", []) or []):
                    if m not in methods:
                        methods.append(m)
    except Exception:
        pass
    return methods


def _j12_route_exists(path):
    return bool(_j12_route_methods(path))


def _j12_storage_counts():
    files = [
        "jarvis_memory.jsonl",
        "jarvis_command_log.jsonl",
        "jarvis_daily_reports.jsonl",
        "jarvis_client_requests.jsonl",
    ]

    out = {}
    for name in files:
        out[name] = len(_j12_read_jsonl_all(name))

    ctx_path = _j12_file("jarvis_active_context.json")
    out["jarvis_active_context.json"] = 1 if _j12_os.path.exists(ctx_path) else 0

    return out


def _j12_expected_routes():
    return [
        {"path": "/jarvis", "label": "Old Jarvis redirect / smart front door"},
        {"path": "/jarvis-brain/start", "label": "Role front door"},
        {"path": "/jarvis-brain/launch", "label": "Launch Pad"},
        {"path": "/jarvis-brain", "label": "Main Mike Brain"},
        {"path": "/jarvis-brain/desk", "label": "Command Desk"},
        {"path": "/jarvis-brain/job", "label": "Active Job Center"},
        {"path": "/jarvis-brain/crew", "label": "Crew Field Flow"},
        {"path": "/jarvis-brain/client", "label": "Client Jarvis"},
        {"path": "/jarvis-brain/help", "label": "Help / command sheet"},
        {"path": "/jarvis-brain/system", "label": "System check"},
        {"path": "/jarvis-brain/install-check", "label": "Install check"},
        {"path": "/jarvis-brain/export.json", "label": "Jarvis export"},
        {"path": "/jarvis-brain/job.json", "label": "Active job JSON"},
        {"path": "/jarvis-brain/crew.json", "label": "Crew JSON"},
        {"path": "/jarvis-brain/client.json", "label": "Client JSON"},
        {"path": "/jarvis-brain/launch.json", "label": "Launch JSON"},
    ]


def _j12_command_groups(role="admin"):
    admin = [
        "Jarvis, start my day",
        "Jarvis, what am I forgetting?",
        "Jarvis, set active job to Alexander",
        "Jarvis, find Alexander",
        "Jarvis, add this to billing: customer approved extra pump time.",
        "Jarvis, field log: cleaned heater orifice and tested operation.",
        "Jarvis, material needed: 2 inch unions and PVC cement.",
        "Jarvis, problem found: gas valve is buzzing during ignition.",
        "Jarvis, remind me to follow up with Jamie about crew hours.",
        "Jarvis, what did I do today?",
        "Jarvis, end my day",
    ]

    crew = [
        "Jarvis, set active job to Alexander",
        "Jarvis, clock me in",
        "Jarvis, field log: arrived on site, checked conditions, started layout.",
        "Jarvis, material needed: drain lid and masonry bit.",
        "Jarvis, problem found: drain lid is loose and needs secured.",
        "Jarvis, clock me out",
    ]

    client = [
        "Use Client Jarvis to send a Project Question.",
        "Use Client Jarvis to send a Service Request.",
        "Use Client Jarvis to ask a Schedule Question.",
        "Use Client Jarvis to ask a Photo / Progress Question.",
    ]

    if role == "client":
        return {"Client": client}

    if role == "crew":
        return {"Crew": crew, "Useful Search": ["Jarvis, find Alexander", "Jarvis, what next?"]}

    return {
        "Mike / Admin": admin,
        "Crew": crew,
        "Client": client,
    }


def _j12_system_payload(request=None):
    user = _j12_user(request) if request is not None else {}
    role = _j12_role(user)

    routes = []
    for item in _j12_expected_routes():
        path = item["path"]
        routes.append({
            "path": path,
            "label": item["label"],
            "exists": _j12_route_exists(path),
            "methods": _j12_route_methods(path),
        })

    tables = {
        "poolops2_jobs": _j12_table_count("poolops2_jobs"),
        "poolops2_clients": _j12_table_count("poolops2_clients"),
        "poolops2_properties": _j12_table_count("poolops2_properties"),
        "poolops2_employees": _j12_table_count("poolops2_employees"),
        "poolops2_photo_logs": _j12_table_count("poolops2_photo_logs"),
        "invisible_office_items": _j12_table_count("invisible_office_items"),
        "field_logs": _j12_table_count("field_logs"),
    }

    return {
        "ok": True,
        "version": JARVIS_HELP_SYSTEM_VERSION,
        "checked_at": _j12_now(),
        "user": {
            "name": _j12_name(user),
            "role": role,
        },
        "routes": routes,
        "tables": tables,
        "storage_counts": _j12_storage_counts(),
        "storage_folder": _j12_storage_dir(),
    }


@app.get("/jarvis-brain/help", response_class=HTMLResponse)
def jarvis_brain_level12_help(request: Request):
    user = _j12_user(request)
    name = _j12_name(user).split()[0]
    role = _j12_role(user)
    groups = _j12_command_groups(role)

    groups_html = ""
    for group_name, commands in groups.items():
        cmd_html = ""
        for cmd in commands:
            safe_cmd = _j12_esc(cmd)
            cmd_html += f"""
            <div class="cmd">
              <code>{safe_cmd}</code>
              <button onclick="copyText('{safe_cmd}')">Copy</button>
            </div>
            """

        groups_html += f"""
        <div class="card">
          <h2>{_j12_esc(group_name)}</h2>
          {cmd_html}
        </div>
        """

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis Help</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }}
    .wrap {{ max-width:1120px; margin:0 auto; padding:26px; }}
    .hero {{ background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:24px; box-shadow:0 20px 60px rgba(0,0,0,.45); }}
    h1 {{ margin:0 0 8px; font-size:34px; letter-spacing:.08em; }}
    .sub {{ color:#d9b56d; margin-bottom:20px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(290px,1fr)); gap:16px; }}
    .card {{ background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; margin-top:16px; }}
    .cmd {{ display:flex; align-items:center; justify-content:space-between; gap:10px; background:#05070b; border:1px solid #2d2113; border-radius:12px; padding:12px; margin:10px 0; }}
    code {{ color:#f5efe3; white-space:normal; }}
    button {{ padding:9px 12px; border:0; border-radius:10px; background:#b8873a; color:#111; font-weight:900; cursor:pointer; }}
    a {{ color:#d9a64a; }}
    .links a {{ display:inline-block; margin:6px 10px 6px 0; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>J.A.R.V.I.S. HELP</h1>
    <div class="sub">Good to go, {_j12_esc(name)}. These are the commands worth remembering. Role: {_j12_esc(role)}.</div>

    <div class="card links">
      <h2>Main Pages</h2>
      <a href="/jarvis-brain/launch">Launch Pad</a>
      <a href="/jarvis-brain/start">Role Start</a>
      <a href="/jarvis-brain">Mike Brain</a>
      <a href="/jarvis-brain/desk">Command Desk</a>
      <a href="/jarvis-brain/job">Active Job</a>
      <a href="/jarvis-brain/crew">Crew Flow</a>
      <a href="/jarvis-brain/client">Client Jarvis</a>
      <a href="/jarvis-brain/system">System Check</a>
    </div>

    <div class="grid">
      {groups_html}
    </div>
  </div>
</div>

<script>
function copyText(text){{
  navigator.clipboard.writeText(text).then(function(){{
    alert("Copied: " + text);
  }}).catch(function(){{
    alert(text);
  }});
}}
</script>
</body>
</html>
"""
    return HTMLResponse(html)


@app.get("/jarvis-brain/system", response_class=HTMLResponse)
def jarvis_brain_level12_system(request: Request):
    data = _j12_system_payload(request)
    user = data["user"]

    route_html = ""
    for r in data["routes"]:
        status = "OK" if r["exists"] else "MISSING"
        cls = "ok" if r["exists"] else "bad"
        methods = ", ".join(r["methods"]) if r["methods"] else "-"
        route_html += f"""
        <tr>
          <td><span class="{cls}">{status}</span></td>
          <td><a href="{_j12_esc(r['path'])}">{_j12_esc(r['path'])}</a></td>
          <td>{_j12_esc(r['label'])}</td>
          <td>{_j12_esc(methods)}</td>
        </tr>
        """

    table_html = ""
    for name, count in data["tables"].items():
        value = "not found" if count is None else str(count)
        cls = "bad" if count is None else "ok"
        table_html += f"""
        <tr>
          <td>{_j12_esc(name)}</td>
          <td><span class="{cls}">{_j12_esc(value)}</span></td>
        </tr>
        """

    storage_html = ""
    for name, count in data["storage_counts"].items():
        storage_html += f"""
        <tr>
          <td>{_j12_esc(name)}</td>
          <td>{_j12_esc(count)}</td>
        </tr>
        """

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis System Check</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }}
    .wrap {{ max-width:1220px; margin:0 auto; padding:26px; }}
    .hero {{ background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:24px; box-shadow:0 20px 60px rgba(0,0,0,.45); }}
    h1 {{ margin:0 0 8px; font-size:34px; letter-spacing:.08em; }}
    .sub {{ color:#d9b56d; margin-bottom:20px; }}
    .grid {{ display:grid; grid-template-columns:1.2fr .8fr; gap:16px; }}
    @media(max-width:900px) {{ .grid {{ grid-template-columns:1fr; }} }}
    .card {{ background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; margin-top:16px; overflow:auto; }}
    table {{ width:100%; border-collapse:collapse; }}
    td, th {{ border-bottom:1px solid #2d2113; padding:10px; text-align:left; vertical-align:top; }}
    .ok {{ color:#a8e063; font-weight:900; }}
    .bad {{ color:#ff7c6b; font-weight:900; }}
    a {{ color:#d9a64a; }}
    code {{ color:#d9b56d; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>J.A.R.V.I.S. SYSTEM CHECK</h1>
    <div class="sub">Checked at {_j12_esc(data['checked_at'])}. User: {_j12_esc(user['name'])}. Role: {_j12_esc(user['role'])}.</div>

    <div class="card">
      <h2>Smoke Test Links</h2>
      <p>
        <a href="/jarvis-brain/launch">Launch</a> |
        <a href="/jarvis-brain/start">Start</a> |
        <a href="/jarvis-brain">Brain</a> |
        <a href="/jarvis-brain/desk">Desk</a> |
        <a href="/jarvis-brain/job">Job</a> |
        <a href="/jarvis-brain/crew">Crew</a> |
        <a href="/jarvis-brain/client">Client</a> |
        <a href="/jarvis-brain/help">Help</a> |
        <a href="/jarvis-brain/system.json">System JSON</a>
      </p>
    </div>

    <div class="grid">
      <div class="card">
        <h2>Routes</h2>
        <table>
          <tr><th>Status</th><th>Path</th><th>Purpose</th><th>Methods</th></tr>
          {route_html}
        </table>
      </div>

      <div>
        <div class="card">
          <h2>Tables</h2>
          <table>
            <tr><th>Table</th><th>Count</th></tr>
            {table_html}
          </table>
        </div>

        <div class="card">
          <h2>Jarvis Storage</h2>
          <p><code>{_j12_esc(data['storage_folder'])}</code></p>
          <table>
            <tr><th>File</th><th>Items</th></tr>
            {storage_html}
          </table>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""
    return HTMLResponse(html)


@app.get("/jarvis-brain/system.json")
def jarvis_brain_level12_system_json(request: Request):
    return JSONResponse(_j12_system_payload(request))


@app.get("/jarvis-help", response_class=HTMLResponse)
def jarvis_brain_level12_help_alias(request: Request):
    return RedirectResponse("/jarvis-brain/help", status_code=303)


@app.get("/jarvis-status", response_class=HTMLResponse)
def jarvis_brain_level12_status_alias(request: Request):
    return RedirectResponse("/jarvis-brain/system", status_code=303)

# ============================================================
# END JARVIS BRAIN LEVEL 12 HELP + SYSTEM CHECK
# ============================================================


# ============================================================
# JARVIS BRAIN LEVEL 13 TODAY OPS BOARD
# Adds /jarvis-brain/today.
# Safe add-on only.
# ============================================================

import os as _j13_os
import json as _j13_json
import html as _j13_html
from datetime import datetime as _j13_datetime, date as _j13_date

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_TODAY_VERSION = "level-13-today-ops-board-2026-07-04"


def _j13_now():
    return _j13_datetime.now().isoformat(timespec="seconds")


def _j13_today():
    return _j13_date.today().isoformat()


def _j13_storage_dir():
    path = _j13_os.path.join(_j13_os.getcwd(), "jarvis_storage")
    _j13_os.makedirs(path, exist_ok=True)
    return path


def _j13_file(name):
    return _j13_os.path.join(_j13_storage_dir(), name)


def _j13_esc(value):
    return _j13_html.escape(str(value or ""))


def _j13_read_json(name, default=None):
    path = _j13_file(name)
    if not _j13_os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _j13_json.load(f)
    except Exception:
        return default


def _j13_read_jsonl_all(name):
    path = _j13_file(name)
    if not _j13_os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                items.append(_j13_json.loads(line.strip()))
            except Exception:
                pass
    return items


def _j13_user(request):
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


def _j13_name(user):
    return str((user or {}).get("name") or (user or {}).get("username") or (user or {}).get("email") or "Mike").strip()


def _j13_role(user):
    role = str((user or {}).get("role") or "admin").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j13_rows(sql, params=()):
    try:
        f = globals().get("rows")
        if callable(f):
            return f(sql, params) or []
    except Exception:
        pass
    return []


def _j13_columns(table):
    try:
        f = globals().get("table_columns")
        if callable(f):
            return list(f(table) or [])
    except Exception:
        pass
    return []


def _j13_table_exists(table):
    return bool(_j13_columns(table))


def _j13_active_context():
    return _j13_read_json("jarvis_active_context.json", {}) or {}


def _j13_all_memory():
    items = _j13_read_jsonl_all("jarvis_memory.jsonl")
    items.reverse()
    return items


def _j13_is_open(item):
    status = str(item.get("status") or "Open").lower().strip()
    return status not in ("done", "closed", "complete", "completed")


def _j13_category(items, category):
    return [x for x in items if str(x.get("category") or "") == category and _j13_is_open(x)]


def _j13_today_memory(items):
    today = _j13_today()
    return [x for x in items if str(x.get("created_at") or "")[:10] == today]


def _j13_job_date(job):
    for key in ["scheduled_start", "schedule_date", "date", "start_date", "created_at"]:
        val = (job or {}).get(key)
        if val:
            return str(val)[:10]
    return ""


def _j13_job_status(job):
    return str((job or {}).get("status") or "").lower().strip()


def _j13_all_jobs(limit=250):
    if not _j13_table_exists("poolops2_jobs"):
        return []
    return _j13_rows("SELECT * FROM poolops2_jobs ORDER BY id DESC LIMIT ?", (limit,))


def _j13_jobs_today_and_overdue():
    today = _j13_today()
    jobs = _j13_all_jobs()
    today_jobs = []
    overdue_jobs = []

    for j in jobs:
        ds = _j13_job_date(j)
        status = _j13_job_status(j)

        if ds == today:
            today_jobs.append(j)

        if ds and ds < today and status not in ("complete", "completed", "done", "closed", "cancelled"):
            overdue_jobs.append(j)

    return today_jobs[:20], overdue_jobs[:20], len(jobs)


def _j13_crew_status():
    cols = _j13_columns("poolops2_employees")
    if not cols:
        return []

    select_cols = ["name", "email", "clocked_in", "clocked_in_at", "last_seen_at"]
    have = [c for c in select_cols if c in cols]
    if not have:
        return []

    order = "ORDER BY name" if "name" in cols else ""
    rows = _j13_rows(f"SELECT {','.join(have)} FROM poolops2_employees {order} LIMIT 50", ())

    out = []
    for r in rows:
        clocked = str(r.get("clocked_in") or "").lower() in ("1", "true", "yes", "on")
        out.append({
            "name": r.get("name") or r.get("email") or "Employee",
            "clocked_in": clocked,
            "clocked_in_at": r.get("clocked_in_at") or "",
            "last_seen_at": r.get("last_seen_at") or "",
        })

    return out


def _j13_client_requests():
    items = _j13_read_jsonl_all("jarvis_client_requests.jsonl")
    items.reverse()
    return [x for x in items if _j13_is_open(x)][:25]


def _j13_ops_payload():
    memory = _j13_all_memory()
    today_memory = _j13_today_memory(memory)
    today_jobs, overdue_jobs, total_jobs = _j13_jobs_today_and_overdue()

    payload = {
        "ok": True,
        "version": JARVIS_TODAY_VERSION,
        "today": _j13_today(),
        "active_context": _j13_active_context(),
        "counts": {
            "memory_total": len(memory),
            "memory_today": len(today_memory),
            "open_billing": len(_j13_category(memory, "Billing Note")),
            "open_materials": len(_j13_category(memory, "Material Needed")),
            "open_followups": len(_j13_category(memory, "Follow Up")),
            "open_problems": len(_j13_category(memory, "Problem Found")),
            "open_field_logs": len(_j13_category(memory, "Field Log")),
            "client_requests": len(_j13_client_requests()),
            "today_jobs": len(today_jobs),
            "overdue_jobs": len(overdue_jobs),
            "total_jobs_seen": total_jobs,
        },
        "today_memory": today_memory[:50],
        "billing": _j13_category(memory, "Billing Note")[:25],
        "materials": _j13_category(memory, "Material Needed")[:25],
        "followups": _j13_category(memory, "Follow Up")[:25],
        "problems": _j13_category(memory, "Problem Found")[:25],
        "field_logs": _j13_category(memory, "Field Log")[:25],
        "client_requests": _j13_client_requests(),
        "today_jobs": today_jobs,
        "overdue_jobs": overdue_jobs,
        "crew": _j13_crew_status(),
        "tables_seen": {
            "poolops2_jobs": _j13_table_exists("poolops2_jobs"),
            "poolops2_employees": _j13_table_exists("poolops2_employees"),
            "invisible_office_items": _j13_table_exists("invisible_office_items"),
            "field_logs": _j13_table_exists("field_logs"),
        },
    }
    return payload


def _j13_render_item(item):
    title = item.get("title") or item.get("body") or "Item"
    body = item.get("body") or ""
    created = item.get("created_at") or ""
    client = item.get("client") or item.get("client_name") or ""
    address = item.get("address") or item.get("property") or ""

    context = ""
    if client or address:
        context = f"<div class='meta'>Job: {_j13_esc(client)} ? {_j13_esc(address)}</div>"

    return f"""
    <div class="item">
      <div class="top"><b>{_j13_esc(title)}</b><span>{_j13_esc(created)}</span></div>
      <div class="body">{_j13_esc(body)}</div>
      {context}
    </div>
    """


def _j13_render_job(job):
    title = job.get("client") or job.get("property") or job.get("address") or f"Job #{job.get('id')}"
    detail = job.get("job_type") or job.get("status") or ""
    date = _j13_job_date(job)

    return f"""
    <div class="item">
      <div class="top"><b>{_j13_esc(title)}</b><span>{_j13_esc(date)}</span></div>
      <div class="body">{_j13_esc(detail)}</div>
      <div class="meta">{_j13_esc(job.get('address') or '')}</div>
    </div>
    """


def _j13_render_crew(row):
    status = "CLOCKED IN" if row.get("clocked_in") else "OUT"
    cls = "good" if row.get("clocked_in") else "muted"

    return f"""
    <div class="item">
      <div class="top"><b>{_j13_esc(row.get('name'))}</b><span class="{cls}">{_j13_esc(status)}</span></div>
      <div class="body">Clocked in at: {_j13_esc(row.get('clocked_in_at'))}</div>
      <div class="meta">Last seen: {_j13_esc(row.get('last_seen_at'))}</div>
    </div>
    """


def _j13_section(title, items, renderer=_j13_render_item, empty="Nothing here right now."):
    if not items:
        body = f"<p>{_j13_esc(empty)}</p>"
    else:
        body = "".join([renderer(x) for x in items[:10]])

    return f"""
    <div class="card">
      <h2>{_j13_esc(title)} <span>{len(items)}</span></h2>
      {body}
    </div>
    """


@app.get("/jarvis-brain/today", response_class=HTMLResponse)
def jarvis_brain_level13_today_ops(request: Request):
    user = _j13_user(request)
    name = _j13_name(user).split()[0]
    role = _j13_role(user)
    data = _j13_ops_payload()
    c = data["counts"]
    active = data["active_context"]

    active_html = "<p>No active job set. Say: <b>Jarvis, set active job to Alexander</b>.</p>"
    if active:
        active_html = f"""
        <p><b>{_j13_esc(active.get('title') or active.get('client') or active.get('address'))}</b></p>
        <p>{_j13_esc(active.get('address'))}</p>
        <p>Type: {_j13_esc(active.get('job_type'))} ? Status: {_j13_esc(active.get('status'))}</p>
        """

    sections = ""
    sections += _j13_section("Today?s Captured Items", data["today_memory"])
    sections += _j13_section("Billing Notes", data["billing"])
    sections += _j13_section("Materials Needed", data["materials"])
    sections += _j13_section("Problems", data["problems"])
    sections += _j13_section("Follow Ups", data["followups"])
    sections += _j13_section("Client Requests", data["client_requests"])
    sections += _j13_section("Today?s Jobs", data["today_jobs"], _j13_render_job, "No jobs scheduled today from the table I can read.")
    sections += _j13_section("Overdue Jobs", data["overdue_jobs"], _j13_render_job, "No overdue jobs found.")
    sections += _j13_section("Crew Clock Status", data["crew"], _j13_render_crew, "No crew clock data found.")

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis Today Ops</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }}
    .wrap {{ max-width:1250px; margin:0 auto; padding:26px; }}
    .hero {{ background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:24px; box-shadow:0 20px 60px rgba(0,0,0,.45); }}
    h1 {{ margin:0 0 8px; font-size:36px; letter-spacing:.08em; }}
    .sub {{ color:#d9b56d; margin-bottom:18px; }}
    .stats {{ display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin:16px 0; }}
    @media(max-width:950px) {{ .stats {{ grid-template-columns:repeat(2,1fr); }} }}
    .stat {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:14px; }}
    .stat b {{ font-size:28px; color:#d9b56d; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    @media(max-width:950px) {{ .grid {{ grid-template-columns:1fr; }} }}
    .card {{ background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; margin-top:16px; }}
    .card h2 {{ display:flex; justify-content:space-between; gap:10px; }}
    textarea {{ width:100%; min-height:120px; box-sizing:border-box; border-radius:14px; border:1px solid #6b4b1f; background:#05070b; color:#fff; padding:14px; font-size:16px; }}
    button {{ margin-top:10px; padding:12px 16px; border:0; border-radius:12px; background:#b8873a; color:#111; font-weight:900; cursor:pointer; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:9px; margin-top:10px; }}
    .chip {{ border:1px solid #6b4b1f; border-radius:999px; padding:9px 11px; background:#070a0f; color:#f5efe3; cursor:pointer; }}
    .reply {{ margin-top:12px; padding:13px; border-radius:12px; background:#05070b; border:1px solid #2d2113; min-height:24px; line-height:1.45; }}
    .item {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:13px; margin:10px 0; }}
    .top {{ display:flex; justify-content:space-between; gap:12px; color:#d9b56d; font-size:13px; }}
    .body {{ margin-top:8px; color:#e8dcc7; line-height:1.4; }}
    .meta {{ margin-top:8px; color:#a99572; font-size:13px; }}
    .good {{ color:#a8e063; font-weight:900; }}
    .muted {{ color:#a99572; }}
    a {{ color:#d9a64a; }}
    .result {{ padding:10px; border:1px solid #2d2113; border-radius:12px; margin:8px 0; background:#070a0f; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>J.A.R.V.I.S. TODAY OPS</h1>
    <div class="sub">Good to go, {_j13_esc(name)}. This is today?s command board. Role: {_j13_esc(role)}. Date: {_j13_esc(data['today'])}.</div>

    <div class="stats">
      <div class="stat"><b>{c['memory_today']}</b><br>Captured today</div>
      <div class="stat"><b>{c['open_billing']}</b><br>Billing</div>
      <div class="stat"><b>{c['open_materials']}</b><br>Materials</div>
      <div class="stat"><b>{c['open_problems']}</b><br>Problems</div>
      <div class="stat"><b>{c['client_requests']}</b><br>Client requests</div>
    </div>

    <div class="grid">
      <div>
        <div class="card">
          <h2>Command</h2>
          <textarea id="cmd" placeholder="Jarvis, start my day"></textarea>
          <button onclick="sendCmd()">Send</button>
          <button onclick="startVoice()">?? Voice</button>
          <button onclick="speakLast()">?? Read Back</button>
          <div class="reply" id="reply">Waiting for command.</div>

          <div class="chips">
            <button class="chip" onclick="fillCmd('Jarvis, start my day')">Start Day</button>
            <button class="chip" onclick="fillCmd('Jarvis, set active job to ')">Set Job</button>
            <button class="chip" onclick="fillCmd('Jarvis, add this to billing: ')">Billing</button>
            <button class="chip" onclick="fillCmd('Jarvis, field log: ')">Field Log</button>
            <button class="chip" onclick="fillCmd('Jarvis, material needed: ')">Material</button>
            <button class="chip" onclick="fillCmd('Jarvis, end my day')">End Day</button>
          </div>
        </div>

        <div class="card">
          <h2>Active Job</h2>
          {active_html}
          <p>
            <a href="/jarvis-brain/job">Active Job Center</a> |
            <a href="/jarvis-brain/desk">Command Desk</a> |
            <a href="/jarvis-brain/launch">Launch Pad</a> |
            <a href="/jarvis-brain/today.json">Today JSON</a>
          </p>
        </div>

        {_j13_section("Today?s Captured Items", data["today_memory"])}
        {_j13_section("Billing Notes", data["billing"])}
        {_j13_section("Materials Needed", data["materials"])}
        {_j13_section("Problems", data["problems"])}
      </div>

      <div>
        {_j13_section("Client Requests", data["client_requests"])}
        {_j13_section("Follow Ups", data["followups"])}
        {_j13_section("Today?s Jobs", data["today_jobs"], _j13_render_job, "No jobs scheduled today from the table I can read.")}
        {_j13_section("Overdue Jobs", data["overdue_jobs"], _j13_render_job, "No overdue jobs found.")}
        {_j13_section("Crew Clock Status", data["crew"], _j13_render_crew, "No crew clock data found.")}
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


@app.get("/jarvis-brain/today.json")
def jarvis_brain_level13_today_json():
    return JSONResponse(_j13_ops_payload())


@app.get("/jarvis-today", response_class=HTMLResponse)
def jarvis_brain_level13_today_alias(request: Request):
    return RedirectResponse("/jarvis-brain/today", status_code=303)

# ============================================================
# END JARVIS BRAIN LEVEL 13 TODAY OPS BOARD
# ============================================================


# ============================================================
# JARVIS BRAIN LEVEL 15 LOGIN SESSION BRIDGE
# Makes admin role-switching set every common session key the app may use.
# Safe add-on only.
# ============================================================

import html as _j15_html
from datetime import datetime as _j15_datetime

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_SESSION_BRIDGE_VERSION = "level-15-login-session-bridge-2026-07-04"


def _j15_now():
    return _j15_datetime.now().isoformat(timespec="seconds")


def _j15_esc(value):
    return _j15_html.escape(str(value or ""))


def _j15_user(request):
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


def _j15_role(user):
    role = str((user or {}).get("role") or (user or {}).get("login_type") or "admin").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j15_name(user):
    return str(
        (user or {}).get("name")
        or (user or {}).get("username")
        or (user or {}).get("email")
        or "User"
    ).strip()


def _j15_email(user):
    return str((user or {}).get("email") or "").strip()


def _j15_rows(sql, params=()):
    try:
        f = globals().get("rows")
        if callable(f):
            return f(sql, params) or []
    except Exception:
        pass
    return []


def _j15_columns(table):
    try:
        f = globals().get("table_columns")
        if callable(f):
            return list(f(table) or [])
    except Exception:
        pass
    return []


def _j15_find_by_id(table, item_id):
    cols = _j15_columns(table)
    if not cols or "id" not in cols:
        return None

    found = _j15_rows(f"SELECT * FROM {table} WHERE id=? LIMIT 1", (item_id,))
    return found[0] if found else None


def _j15_employees():
    cols = _j15_columns("poolops2_employees")
    if not cols:
        return []

    wanted = [c for c in ["id", "name", "email", "role", "clocked_in"] if c in cols]
    if not wanted:
        return []

    order = "ORDER BY name" if "name" in cols else "ORDER BY id DESC" if "id" in cols else ""
    return _j15_rows(f"SELECT {','.join(wanted)} FROM poolops2_employees {order} LIMIT 300", ())


def _j15_clients():
    cols = _j15_columns("poolops2_clients")
    if not cols:
        return []

    wanted = [c for c in ["id", "name", "contact_name", "email", "phone"] if c in cols]
    if not wanted:
        return []

    order = "ORDER BY name" if "name" in cols else "ORDER BY id DESC" if "id" in cols else ""
    return _j15_rows(f"SELECT {','.join(wanted)} FROM poolops2_clients {order} LIMIT 300", ())


def _j15_is_real_admin(request):
    user = _j15_user(request)
    if _j15_role(user) == "admin":
        return True

    try:
        backup = request.session.get("jarvis_real_admin_user")
        if backup and _j15_role(backup) == "admin":
            return True
    except Exception:
        pass

    return False


def _j15_make_target(target_type, target_id="", custom_name="", custom_email=""):
    target_type = str(target_type or "").lower().strip()

    if target_type == "admin":
        return {
            "id": "admin",
            "user_id": "admin",
            "name": custom_name or "Mike",
            "username": custom_name or "Mike",
            "email": custom_email or "",
            "role": "admin",
            "login_type": "admin",
            "is_admin": True,
            "switched_by_jarvis": True,
        }

    if target_type in ("crew", "employee"):
        row = _j15_find_by_id("poolops2_employees", target_id)
        if not row:
            return None

        name = row.get("name") or row.get("email") or f"Employee {target_id}"
        email = row.get("email") or ""

        return {
            "id": row.get("id"),
            "user_id": row.get("id"),
            "employee_id": row.get("id"),
            "name": name,
            "username": name,
            "email": email,
            "role": "crew",
            "login_type": "crew",
            "is_admin": False,
            "is_employee": True,
            "switched_by_jarvis": True,
        }

    if target_type == "client":
        row = _j15_find_by_id("poolops2_clients", target_id)
        if not row:
            return None

        name = row.get("name") or row.get("contact_name") or row.get("email") or f"Client {target_id}"
        email = row.get("email") or ""

        return {
            "id": row.get("id"),
            "user_id": row.get("id"),
            "client_id": row.get("id"),
            "name": name,
            "username": name,
            "email": email,
            "role": "client",
            "login_type": "client",
            "is_admin": False,
            "is_client": True,
            "switched_by_jarvis": True,
        }

    if target_type == "custom_crew":
        name = custom_name or "Crew Test"
        return {
            "id": "custom_crew",
            "user_id": "custom_crew",
            "employee_id": "custom_crew",
            "name": name,
            "username": name,
            "email": custom_email or "",
            "role": "crew",
            "login_type": "crew",
            "is_admin": False,
            "is_employee": True,
            "switched_by_jarvis": True,
        }

    if target_type == "custom_client":
        name = custom_name or "Client Test"
        return {
            "id": "custom_client",
            "user_id": "custom_client",
            "client_id": "custom_client",
            "name": name,
            "username": name,
            "email": custom_email or "",
            "role": "client",
            "login_type": "client",
            "is_admin": False,
            "is_client": True,
            "switched_by_jarvis": True,
        }

    return None


def _j15_apply_session_bridge(request, target):
    if not hasattr(request, "session"):
        return False

    session = request.session
    current = _j15_user(request)

    if _j15_role(current) == "admin" and not session.get("jarvis_real_admin_user"):
        session["jarvis_real_admin_user"] = dict(current)

    role = _j15_role(target)
    name = _j15_name(target)
    email = _j15_email(target)
    uid = target.get("user_id") or target.get("id")

    # Main object used by Jarvis helpers.
    session["user"] = target

    # Common keys older app routes may check.
    session["user_id"] = uid
    session["id"] = uid
    session["username"] = name
    session["name"] = name
    session["email"] = email
    session["role"] = role
    session["login_type"] = role

    # Role flags.
    session["is_admin"] = role == "admin"
    session["is_employee"] = role == "crew"
    session["is_crew"] = role == "crew"
    session["is_client"] = role == "client"

    # Entity-specific ids.
    if role == "crew":
        session["employee_id"] = target.get("employee_id") or uid
        session.pop("client_id", None)

    if role == "client":
        session["client_id"] = target.get("client_id") or uid
        session.pop("employee_id", None)

    if role == "admin":
        session.pop("employee_id", None)
        session.pop("client_id", None)

    session["jarvis_switched_login"] = {
        "active": True,
        "started_at": _j15_now(),
        "target_role": role,
        "target_name": name,
        "target_email": email,
        "target_id": uid,
    }

    return True


def _j15_return_to_admin(request):
    if not hasattr(request, "session"):
        return False

    session = request.session
    admin = session.get("jarvis_real_admin_user")

    if not admin:
        return False

    # Restore using the same bridge so all session keys are reset.
    session["user"] = admin
    role = _j15_role(admin)
    name = _j15_name(admin)
    email = _j15_email(admin)
    uid = admin.get("user_id") or admin.get("id") or "admin"

    session["user_id"] = uid
    session["id"] = uid
    session["username"] = name
    session["name"] = name
    session["email"] = email
    session["role"] = role
    session["login_type"] = role
    session["is_admin"] = True
    session["is_employee"] = False
    session["is_crew"] = False
    session["is_client"] = False
    session.pop("employee_id", None)
    session.pop("client_id", None)
    session.pop("jarvis_switched_login", None)

    return True


def _j15_status(request):
    user = _j15_user(request)
    s = request.session if hasattr(request, "session") else {}

    keys = [
        "user_id", "id", "username", "name", "email", "role", "login_type",
        "is_admin", "is_employee", "is_crew", "is_client",
        "employee_id", "client_id", "jarvis_switched_login"
    ]

    session_view = {}
    for k in keys:
        try:
            session_view[k] = s.get(k)
        except Exception:
            session_view[k] = None

    return {
        "current_user_object": user,
        "current_name": _j15_name(user),
        "current_role": _j15_role(user),
        "current_email": _j15_email(user),
        "session_keys": session_view,
        "has_real_admin_backup": bool(s.get("jarvis_real_admin_user")) if hasattr(request, "session") else False,
        "is_real_admin": _j15_is_real_admin(request),
    }


def _j15_btn(target_type, target_id, label, detail=""):
    return f"""
    <form method="post" action="/jarvis-brain/login-bridge/switch">
      <input type="hidden" name="target_type" value="{_j15_esc(target_type)}">
      <input type="hidden" name="target_id" value="{_j15_esc(target_id)}">
      <button type="submit">
        {_j15_esc(label)}
        <span>{_j15_esc(detail)}</span>
      </button>
    </form>
    """


@app.get("/jarvis-brain/login-bridge", response_class=HTMLResponse)
def jarvis_brain_level15_login_bridge_page(request: Request):
    user = _j15_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    if not _j15_is_real_admin(request):
        return HTMLResponse("<h1>Admin only</h1><p><a href='/login'>Login</a></p>", status_code=403)

    status = _j15_status(request)
    employees = _j15_employees()
    clients = _j15_clients()

    employee_html = ""
    for e in employees:
        label = e.get("name") or e.get("email") or f"Employee {e.get('id')}"
        detail = e.get("email") or "Crew"
        employee_html += _j15_btn("crew", e.get("id"), label, detail)

    if not employee_html:
        employee_html = "<p>No employee rows found.</p>"

    client_html = ""
    for c in clients:
        label = c.get("name") or c.get("contact_name") or c.get("email") or f"Client {c.get('id')}"
        detail = c.get("email") or c.get("phone") or "Client"
        client_html += _j15_btn("client", c.get("id"), label, detail)

    if not client_html:
        client_html = "<p>No client rows found.</p>"

    return_admin_html = ""
    if status["has_real_admin_backup"] or status["current_role"] != "admin":
        return_admin_html = """
        <form method="post" action="/jarvis-brain/login-bridge/return-admin">
          <button class="admin" type="submit">Return to Real Admin <span>Restore Mike/Admin session keys</span></button>
        </form>
        """

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis Login Bridge</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }}
    .wrap {{ max-width:1180px; margin:0 auto; padding:26px; }}
    .hero {{ background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:24px; box-shadow:0 20px 60px rgba(0,0,0,.45); }}
    h1 {{ margin:0 0 8px; font-size:34px; letter-spacing:.08em; }}
    .sub {{ color:#d9b56d; margin-bottom:20px; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    @media(max-width:900px) {{ .grid {{ grid-template-columns:1fr; }} }}
    .card {{ background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; margin-top:16px; }}
    button {{ width:100%; text-align:left; margin:7px 0; padding:13px 15px; border:1px solid #6b4b1f; border-radius:14px; background:#05070b; color:#f5efe3; font-weight:900; cursor:pointer; }}
    button:hover {{ border-color:#b8873a; }}
    button span {{ display:block; margin-top:4px; color:#d9b56d; font-weight:400; font-size:13px; }}
    button.admin {{ background:#b8873a; color:#111; }}
    button.admin span {{ color:#33210d; }}
    input {{ width:100%; box-sizing:border-box; margin:7px 0; padding:12px; border-radius:12px; border:1px solid #6b4b1f; background:#05070b; color:#fff; }}
    pre {{ white-space:pre-wrap; background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:12px; overflow:auto; }}
    a {{ color:#d9a64a; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>JARVIS LOGIN BRIDGE</h1>
    <div class="sub">This sets every common session key so the rest of the app can recognize Admin, Crew, and Client mode.</div>

    <div class="card">
      <h2>Current Session</h2>
      <p><b>Name:</b> {_j15_esc(status['current_name'])}</p>
      <p><b>Role:</b> {_j15_esc(status['current_role'])}</p>
      <p><b>Email:</b> {_j15_esc(status['current_email'])}</p>
      {return_admin_html}
      {_j15_btn("admin", "admin", "Switch to Admin", "Mike/Admin view")}
    </div>

    <div class="grid">
      <div class="card">
        <h2>Crew / Employee</h2>
        {employee_html}

        <h3>Custom Crew Test</h3>
        <form method="post" action="/jarvis-brain/login-bridge/switch">
          <input type="hidden" name="target_type" value="custom_crew">
          <input name="custom_name" placeholder="Crew name">
          <input name="custom_email" placeholder="Crew email optional">
          <button type="submit">Custom Crew <span>Testing only</span></button>
        </form>
      </div>

      <div class="card">
        <h2>Client</h2>
        {client_html}

        <h3>Custom Client Test</h3>
        <form method="post" action="/jarvis-brain/login-bridge/switch">
          <input type="hidden" name="target_type" value="custom_client">
          <input name="custom_name" placeholder="Client name">
          <input name="custom_email" placeholder="Client email optional">
          <button type="submit">Custom Client <span>Testing only</span></button>
        </form>
      </div>
    </div>

    <div class="card">
      <h2>Test After Switching</h2>
      <p>
        <a href="/jarvis-brain/start">Smart Start</a> |
        <a href="/jarvis-brain/launch">Launch Pad</a> |
        <a href="/jarvis-brain/crew">Crew Flow</a> |
        <a href="/jarvis-brain/client">Client Jarvis</a> |
        <a href="/jarvis-brain/login-bridge.json">Bridge JSON</a>
      </p>
    </div>

    <div class="card">
      <h2>Session Debug</h2>
      <pre>{_j15_esc(status)}</pre>
    </div>
  </div>
</div>
</body>
</html>
"""
    return HTMLResponse(html)


@app.post("/jarvis-brain/login-bridge/switch")
async def jarvis_brain_level15_login_bridge_switch(request: Request):
    user = _j15_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    if not _j15_is_real_admin(request):
        return HTMLResponse("<h1>Admin only</h1>", status_code=403)

    try:
        form = await request.form()
        target_type = str(form.get("target_type") or "").strip()
        target_id = str(form.get("target_id") or "").strip()
        custom_name = str(form.get("custom_name") or "").strip()
        custom_email = str(form.get("custom_email") or "").strip()
    except Exception:
        target_type = ""
        target_id = ""
        custom_name = ""
        custom_email = ""

    if target_type == "admin":
        admin = request.session.get("jarvis_real_admin_user") if hasattr(request, "session") else None
        target = admin or _j15_make_target("admin", custom_name="Mike")
    else:
        target = _j15_make_target(target_type, target_id, custom_name, custom_email)

    if not target:
        return RedirectResponse("/jarvis-brain/login-bridge", status_code=303)

    _j15_apply_session_bridge(request, target)

    return RedirectResponse("/jarvis-brain/start", status_code=303)


@app.post("/jarvis-brain/login-bridge/return-admin")
def jarvis_brain_level15_return_admin(request: Request):
    _j15_return_to_admin(request)
    return RedirectResponse("/jarvis-brain/launch", status_code=303)


@app.get("/jarvis-brain/login-bridge.json")
def jarvis_brain_level15_login_bridge_json(request: Request):
    return JSONResponse({
        "ok": True,
        "version": JARVIS_SESSION_BRIDGE_VERSION,
        "status": _j15_status(request),
        "employees_seen": len(_j15_employees()),
        "clients_seen": len(_j15_clients()),
        "tables_seen": {
            "poolops2_employees": bool(_j15_columns("poolops2_employees")),
            "poolops2_clients": bool(_j15_columns("poolops2_clients")),
        },
    })


@app.get("/login-bridge", response_class=HTMLResponse)
def jarvis_brain_level15_login_bridge_alias(request: Request):
    return RedirectResponse("/jarvis-brain/login-bridge", status_code=303)


@app.get("/whoami")
def jarvis_brain_level15_whoami(request: Request):
    return JSONResponse({
        "ok": True,
        "version": JARVIS_SESSION_BRIDGE_VERSION,
        "status": _j15_status(request),
    })

# ============================================================
# END JARVIS BRAIN LEVEL 15 LOGIN SESSION BRIDGE
# ============================================================


# ============================================================
# JARVIS BRAIN LEVEL 17 ADMIN SWITCH BAR
# Adds a permanent top bar to Jarvis pages:
# Return to Admin | Switch Login | Launch Pad | Today Ops | Mike Brain
# ============================================================

import html as _j17_html

try:
    from fastapi.responses import RedirectResponse as _J17RedirectResponse
except Exception:
    pass

try:
    from starlette.responses import Response as _J17Response
except Exception:
    pass

JARVIS_ADMIN_BAR_VERSION = "level-17-admin-switch-bar-2026-07-04"


def _j17_esc(value):
    return _j17_html.escape(str(value or ""))


def _j17_user(request):
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


def _j17_role(user):
    role = str((user or {}).get("role") or (user or {}).get("login_type") or "guest").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j17_name(user):
    return str(
        (user or {}).get("name")
        or (user or {}).get("username")
        or (user or {}).get("email")
        or "User"
    ).strip()


def _j17_has_admin_backup(request):
    try:
        backup = request.session.get("jarvis_real_admin_user")
        return bool(backup)
    except Exception:
        return False


def _j17_is_switched(request):
    try:
        return bool((request.session.get("jarvis_switched_login") or {}).get("active"))
    except Exception:
        return False


def _j17_is_jarvis_html_path(path):
    return (
        path.startswith("/jarvis-brain")
        or path in ("/crew/jarvis", "/employee/jarvis", "/client/jarvis", "/client-jarvis", "/jarvis-launch", "/jarvis-today", "/jarvis-help", "/jarvis-status")
    )


def _j17_restore_admin_session(request):
    if not hasattr(request, "session"):
        return False

    session = request.session
    admin = session.get("jarvis_real_admin_user")

    if not admin:
        return False

    role = "admin"
    name = (
        admin.get("name")
        or admin.get("username")
        or admin.get("email")
        or "Mike"
    )
    email = admin.get("email") or ""
    uid = admin.get("user_id") or admin.get("id") or "admin"

    session["user"] = admin
    session["user_id"] = uid
    session["id"] = uid
    session["username"] = name
    session["name"] = name
    session["email"] = email
    session["role"] = role
    session["login_type"] = role
    session["is_admin"] = True
    session["is_employee"] = False
    session["is_crew"] = False
    session["is_client"] = False
    session.pop("employee_id", None)
    session.pop("client_id", None)
    session.pop("jarvis_switched_login", None)

    return True


def _j17_bar_html(request):
    user = _j17_user(request)
    role = _j17_role(user)
    name = _j17_name(user)
    switched = _j17_is_switched(request)
    has_backup = _j17_has_admin_backup(request)

    return_admin = ""
    if switched or has_backup or role != "admin":
        return_admin = '<a class="j17-danger" href="/jarvis-brain/return-admin">Return to Admin</a>'

    viewing = f"Viewing as: {role.upper()} / {name}"
    if switched:
        viewing += "  ? TEST MODE"

    return f"""
<div id="jarvis-admin-switch-bar">
  <div class="j17-left">
    <strong>{_j17_esc(viewing)}</strong>
  </div>
  <div class="j17-right">
    {return_admin}
    <a href="/jarvis-brain/login-bridge">Switch Login</a>
    <a href="/jarvis-brain/launch">Launch Pad</a>
    <a href="/jarvis-brain/today">Today Ops</a>
    <a href="/jarvis-brain">Mike Brain</a>
  </div>
</div>
<style>
  body {{
    padding-top: 64px !important;
  }}
  #jarvis-admin-switch-bar {{
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 999999;
    min-height: 52px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 8px 16px;
    background: #05070b;
    border-bottom: 1px solid #b8873a;
    box-shadow: 0 8px 22px rgba(0,0,0,.45);
    color: #f5efe3;
    font-family: Arial, sans-serif;
  }}
  #jarvis-admin-switch-bar .j17-left {{
    font-size: 14px;
    color: #f5efe3;
  }}
  #jarvis-admin-switch-bar .j17-right {{
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }}
  #jarvis-admin-switch-bar a {{
    display: inline-block;
    padding: 8px 11px;
    border-radius: 999px;
    border: 1px solid #6b4b1f;
    background: #101722;
    color: #d9b56d !important;
    text-decoration: none;
    font-size: 13px;
    font-weight: 800;
  }}
  #jarvis-admin-switch-bar a.j17-danger {{
    background: #b8873a;
    color: #111 !important;
    border-color: #d9b56d;
  }}
  @media(max-width: 800px) {{
    body {{
      padding-top: 112px !important;
    }}
    #jarvis-admin-switch-bar {{
      display: block;
    }}
    #jarvis-admin-switch-bar .j17-right {{
      margin-top: 8px;
      justify-content: flex-start;
    }}
  }}
</style>
"""


@app.get("/jarvis-brain/return-admin")
def jarvis_brain_level17_return_admin(request: Request):
    ok = _j17_restore_admin_session(request)
    if ok:
        return _J17RedirectResponse("/jarvis-brain/launch", status_code=303)
    return _J17RedirectResponse("/logout", status_code=303)


@app.post("/jarvis-brain/return-admin")
def jarvis_brain_level17_return_admin_post(request: Request):
    ok = _j17_restore_admin_session(request)
    if ok:
        return _J17RedirectResponse("/jarvis-brain/launch", status_code=303)
    return _J17RedirectResponse("/logout", status_code=303)


@app.get("/jarvis-brain/switch")
def jarvis_brain_level17_switch_alias(request: Request):
    return _J17RedirectResponse("/jarvis-brain/login-bridge", status_code=303)


@app.middleware("http")
async def jarvis_level17_admin_bar_middleware(request, call_next):
    response = await call_next(request)

    path = request.url.path
    if not _j17_is_jarvis_html_path(path):
        return response

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        return response

    try:
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        html = body.decode("utf-8", errors="replace")

        if "id=\"jarvis-admin-switch-bar\"" not in html:
            bar = _j17_bar_html(request)

            if "<body" in html.lower():
                import re as _j17_re
                html = _j17_re.sub(r"(<body[^>]*>)", r"\1" + bar, html, count=1, flags=_j17_re.I)
            else:
                html = bar + html

        headers = dict(response.headers)
        headers.pop("content-length", None)

        return _J17Response(
            content=html,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )
    except Exception as exc:
        print("Jarvis admin bar inject skipped:", exc)
        return response


@app.get("/jarvis-brain/admin-bar-check")
def jarvis_brain_level17_admin_bar_check(request: Request):
    user = _j17_user(request)
    return {
        "ok": True,
        "version": JARVIS_ADMIN_BAR_VERSION,
        "role": _j17_role(user),
        "name": _j17_name(user),
        "is_switched": _j17_is_switched(request),
        "has_admin_backup": _j17_has_admin_backup(request),
    }

# ============================================================
# END JARVIS BRAIN LEVEL 17 ADMIN SWITCH BAR
# ============================================================


# ============================================================
# JARVIS BRAIN LEVEL 18 UNIVERSAL ASK BOX
# Adds a floating Ask Jarvis box to Jarvis pages.
# This lets Mike ask questions without leaving the current page.
# ============================================================

try:
    from starlette.responses import Response as _J18Response
except Exception:
    pass

JARVIS_UNIVERSAL_ASK_VERSION = "level-18-universal-ask-box-2026-07-04"


def _j18_is_jarvis_html_path(path):
    return (
        path.startswith("/jarvis-brain")
        or path in (
            "/crew/jarvis",
            "/employee/jarvis",
            "/client/jarvis",
            "/client-jarvis",
            "/jarvis-launch",
            "/jarvis-today",
            "/jarvis-help",
            "/jarvis-status",
        )
    )


def _j18_widget_html():
    return r"""
<div id="jarvis-universal-ask">
  <button id="j18-toggle" type="button" onclick="j18Toggle()">Ask Jarvis</button>

  <div id="j18-panel">
    <div id="j18-head">
      <strong>Ask Jarvis</strong>
      <button type="button" onclick="j18Toggle()">?</button>
    </div>

    <textarea id="j18-text" placeholder="Ask right here. Example: Jarvis, what am I forgetting?"></textarea>

    <div id="j18-buttons">
      <button type="button" onclick="j18Send()">Send</button>
      <button type="button" onclick="j18Voice()">?? Voice</button>
      <button type="button" onclick="j18Speak()">?? Read</button>
    </div>

    <div id="j18-quick">
      <button type="button" onclick="j18Fill('Jarvis, what am I forgetting?')">Forgetting?</button>
      <button type="button" onclick="j18Fill('Jarvis, what is my active job?')">Active Job</button>
      <button type="button" onclick="j18Fill('Jarvis, find ')">Find</button>
      <button type="button" onclick="j18Fill('Jarvis, add this to billing: ')">Billing</button>
      <button type="button" onclick="j18Fill('Jarvis, field log: ')">Field Log</button>
      <button type="button" onclick="j18Fill('Jarvis, material needed: ')">Material</button>
    </div>

    <div id="j18-reply">I?m ready.</div>
  </div>
</div>

<style>
  #jarvis-universal-ask {
    position: fixed;
    right: 18px;
    bottom: 18px;
    z-index: 999998;
    font-family: Arial, sans-serif;
  }

  #j18-toggle {
    border: 1px solid #d9b56d;
    background: #b8873a;
    color: #111;
    border-radius: 999px;
    padding: 14px 18px;
    font-weight: 900;
    box-shadow: 0 10px 30px rgba(0,0,0,.45);
    cursor: pointer;
  }

  #j18-panel {
    display: none;
    width: min(520px, calc(100vw - 30px));
    max-height: min(720px, calc(100vh - 120px));
    overflow: auto;
    background: #05070b;
    color: #f5efe3;
    border: 1px solid #b8873a;
    border-radius: 20px;
    box-shadow: 0 20px 70px rgba(0,0,0,.65);
    padding: 14px;
  }

  #j18-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    color: #d9b56d;
    margin-bottom: 10px;
  }

  #j18-head button {
    background: #101722;
    color: #d9b56d;
    border: 1px solid #6b4b1f;
    border-radius: 10px;
    padding: 6px 10px;
    cursor: pointer;
  }

  #j18-text {
    width: 100%;
    min-height: 115px;
    box-sizing: border-box;
    border-radius: 14px;
    border: 1px solid #6b4b1f;
    background: #101722;
    color: #fff;
    padding: 12px;
    font-size: 15px;
  }

  #j18-buttons, #j18-quick {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 10px;
  }

  #j18-buttons button, #j18-quick button {
    border: 1px solid #6b4b1f;
    border-radius: 999px;
    background: #101722;
    color: #f5efe3;
    padding: 9px 11px;
    cursor: pointer;
    font-weight: 800;
  }

  #j18-buttons button:first-child {
    background: #b8873a;
    color: #111;
  }

  #j18-reply {
    margin-top: 12px;
    background: #101722;
    border: 1px solid #2d2113;
    border-radius: 14px;
    padding: 12px;
    line-height: 1.45;
    white-space: normal;
  }

  .j18-card {
    margin-top: 10px;
    padding: 10px;
    border: 1px solid #2d2113;
    border-radius: 12px;
    background: #05070b;
  }

  .j18-card b {
    color: #d9b56d;
  }

  .j18-card a {
    color: #d9a64a !important;
  }

  @media(max-width: 700px) {
    #jarvis-universal-ask {
      left: 10px;
      right: 10px;
      bottom: 10px;
    }

    #j18-toggle {
      width: 100%;
    }

    #j18-panel {
      width: 100%;
      box-sizing: border-box;
    }
  }
</style>

<script>
(function(){
  if(window.j18Loaded){ return; }
  window.j18Loaded = true;
  window.j18LastReply = "I?m ready.";
})();

function j18Toggle(){
  const panel = document.getElementById("j18-panel");
  const toggle = document.getElementById("j18-toggle");
  if(!panel || !toggle){ return; }

  const open = panel.style.display === "block";
  panel.style.display = open ? "none" : "block";
  toggle.style.display = open ? "inline-block" : "none";

  if(!open){
    setTimeout(function(){
      const box = document.getElementById("j18-text");
      if(box){ box.focus(); }
    }, 100);
  }
}

function j18Fill(text){
  const box = document.getElementById("j18-text");
  if(box){
    box.value = text;
    box.focus();
  }
}

function j18Esc(str){
  return String(str || "").replace(/[&<>"']/g, function(m){
    return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'})[m];
  });
}

function j18Render(data){
  let html = j18Esc(data.reply || JSON.stringify(data));

  const cards = data.links || data.cards || [];
  if(cards && cards.length){
    html += "<br><br>";
    cards.forEach(function(x){
      const kind = j18Esc(x.kind || "Answer");
      const title = j18Esc(x.title || "");
      const detail = j18Esc(x.detail || "");
      const url = j18Esc(x.url || "#");

      html += '<div class="j18-card">';
      html += '<b>' + kind + '</b><br>';

      if(url && url !== "#"){
        html += '<a href="' + url + '">' + title + '</a>';
      } else {
        html += '<strong>' + title + '</strong>';
      }

      if(detail){
        html += '<div>' + detail + '</div>';
      }

      html += '</div>';
    });
  }

  return html;
}

async function j18Send(){
  const box = document.getElementById("j18-text");
  const reply = document.getElementById("j18-reply");
  const text = (box && box.value ? box.value : "").trim();

  if(!text){
    reply.innerText = "Tell me what needs handled.";
    window.j18LastReply = reply.innerText;
    return;
  }

  reply.innerText = "Handling it...";
  window.j18LastReply = reply.innerText;

  try {
    const res = await fetch("/jarvis-brain/command", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text: text})
    });

    const data = await res.json();
    reply.innerHTML = j18Render(data);
    window.j18LastReply = data.reply || JSON.stringify(data);

    j18Speak(false);
  } catch(err) {
    reply.innerText = "Jarvis failed: " + err;
    window.j18LastReply = reply.innerText;
    j18Speak(false);
  }
}

function j18Speak(force){
  const text = window.j18LastReply || "Nothing to read back yet.";
  if(!("speechSynthesis" in window)){ return; }

  window.speechSynthesis.cancel();
  const msg = new SpeechSynthesisUtterance(text);
  msg.rate = 1;
  msg.pitch = 1;
  window.speechSynthesis.speak(msg);
}

function j18Voice(){
  const reply = document.getElementById("j18-reply");
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  if(!SR){
    reply.innerText = "Voice is not available in this browser. Use Chrome or Edge.";
    window.j18LastReply = reply.innerText;
    j18Speak(false);
    return;
  }

  const rec = new SR();
  rec.lang = "en-US";
  rec.interimResults = false;
  rec.maxAlternatives = 1;

  reply.innerText = "Listening...";
  window.j18LastReply = reply.innerText;

  rec.onresult = function(event){
    const text = event.results[0][0].transcript;
    const box = document.getElementById("j18-text");
    if(box){ box.value = text; }
    j18Send();
  };

  rec.onerror = function(event){
    reply.innerText = "Voice error: " + event.error;
    window.j18LastReply = reply.innerText;
  };

  rec.start();
}
</script>
"""


@app.middleware("http")
async def jarvis_level18_universal_ask_box_middleware(request, call_next):
    response = await call_next(request)

    path = request.url.path
    if not _j18_is_jarvis_html_path(path):
        return response

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        return response

    try:
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        html = body.decode("utf-8", errors="replace")

        if "id=\"jarvis-universal-ask\"" not in html:
            widget = _j18_widget_html()

            if "</body>" in html.lower():
                import re as _j18_re
                html = _j18_re.sub(r"</body>", widget + "</body>", html, count=1, flags=_j18_re.I)
            else:
                html += widget

        headers = dict(response.headers)
        headers.pop("content-length", None)

        return _J18Response(
            content=html,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )
    except Exception as exc:
        print("Jarvis universal ask box skipped:", exc)
        return response


@app.get("/jarvis-brain/ask-box-check")
def jarvis_brain_level18_ask_box_check():
    return {
        "ok": True,
        "version": JARVIS_UNIVERSAL_ASK_VERSION,
        "message": "Universal Ask Jarvis box is installed on Jarvis pages.",
    }

# ============================================================
# END JARVIS BRAIN LEVEL 18 UNIVERSAL ASK BOX
# ============================================================


# ============================================================
# JARVIS BRAIN LEVEL 19 CLEAN HOME BUTTONS
# Adds /jarvis-brain/home as the obvious home page.
# ============================================================

import os as _j19_os
import json as _j19_json
import html as _j19_html
from datetime import datetime as _j19_datetime

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_CLEAN_HOME_VERSION = "level-19-clean-home-buttons-2026-07-04"


def _j19_now():
    return _j19_datetime.now().isoformat(timespec="seconds")


def _j19_esc(value):
    return _j19_html.escape(str(value or ""))


def _j19_storage_dir():
    path = _j19_os.path.join(_j19_os.getcwd(), "jarvis_storage")
    _j19_os.makedirs(path, exist_ok=True)
    return path


def _j19_file(name):
    return _j19_os.path.join(_j19_storage_dir(), name)


def _j19_read_jsonl_all(name):
    path = _j19_file(name)
    if not _j19_os.path.exists(path):
        return []

    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                items.append(_j19_json.loads(line.strip()))
            except Exception:
                pass
    return items


def _j19_read_json(name, default=None):
    path = _j19_file(name)
    if not _j19_os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _j19_json.load(f)
    except Exception:
        return default


def _j19_user(request):
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


def _j19_role(user):
    role = str((user or {}).get("role") or (user or {}).get("login_type") or "guest").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _j19_name(user):
    return str(
        (user or {}).get("name")
        or (user or {}).get("username")
        or (user or {}).get("email")
        or "Mike"
    ).strip()


def _j19_has_admin_backup(request):
    try:
        return bool(request.session.get("jarvis_real_admin_user"))
    except Exception:
        return False


def _j19_is_switched(request):
    try:
        return bool((request.session.get("jarvis_switched_login") or {}).get("active"))
    except Exception:
        return False


def _j19_columns(table):
    try:
        f = globals().get("table_columns")
        if callable(f):
            return list(f(table) or [])
    except Exception:
        pass
    return []


def _j19_rows(sql, params=()):
    try:
        f = globals().get("rows")
        if callable(f):
            return f(sql, params) or []
    except Exception:
        pass
    return []


def _j19_table_count(table):
    cols = _j19_columns(table)
    if not cols:
        return None

    try:
        r = _j19_rows(f"SELECT COUNT(*) AS c FROM {table}", ())
        if r:
            first = r[0]
            return first.get("c") if hasattr(first, "get") else list(first)[0]
    except Exception:
        pass

    return None


def _j19_memory_counts():
    items = _j19_read_jsonl_all("jarvis_memory.jsonl")
    open_items = []
    for item in items:
        status = str(item.get("status") or "Open").lower()
        if status not in ("done", "closed", "complete", "completed"):
            open_items.append(item)

    counts = {
        "total": len(items),
        "open": len(open_items),
        "billing": 0,
        "materials": 0,
        "problems": 0,
        "followups": 0,
        "field_logs": 0,
        "client_requests": 0,
    }

    for item in open_items:
        cat = str(item.get("category") or "")
        if cat == "Billing Note":
            counts["billing"] += 1
        elif cat == "Material Needed":
            counts["materials"] += 1
        elif cat == "Problem Found":
            counts["problems"] += 1
        elif cat == "Follow Up":
            counts["followups"] += 1
        elif cat == "Field Log":
            counts["field_logs"] += 1
        elif cat == "Client Request":
            counts["client_requests"] += 1

    return counts


def _j19_active_context():
    return _j19_read_json("jarvis_active_context.json", {}) or {}


def _j19_card(title, desc, href, tag="", danger=False):
    danger_class = " danger" if danger else ""
    return f"""
    <a class="tile{danger_class}" href="{_j19_esc(href)}">
      <div class="tag">{_j19_esc(tag)}</div>
      <h2>{_j19_esc(title)}</h2>
      <p>{_j19_esc(desc)}</p>
    </a>
    """


@app.get("/jarvis-brain/home", response_class=HTMLResponse)
def jarvis_brain_level19_clean_home(request: Request):
    user = _j19_user(request)
    role = _j19_role(user)
    name = _j19_name(user)
    switched = _j19_is_switched(request)
    has_backup = _j19_has_admin_backup(request)
    counts = _j19_memory_counts()
    active = _j19_active_context()

    return_admin_tile = ""
    if switched or has_backup or role != "admin":
        return_admin_tile = _j19_card(
            "Return to Admin",
            "Go back to Mike/Admin session immediately.",
            "/jarvis-brain/return-admin",
            "Admin",
            True,
        )

    active_text = "No active job set."
    if active:
        active_text = f"{active.get('title') or active.get('client') or active.get('address')} ? {active.get('address') or ''}"

    tiles = ""
    tiles += return_admin_tile
    tiles += _j19_card("Switch Login", "Admin testing panel for Crew and Client views.", "/jarvis-brain/login-bridge", "Switch")
    tiles += _j19_card("Today Ops", "The page you should open first every morning.", "/jarvis-brain/today", "Daily")
    tiles += _j19_card("Mike Brain", "Main Jarvis command center.", "/jarvis-brain", "Brain")
    tiles += _j19_card("Command Desk", "Open brain queue: billing, materials, follow-ups, problems.", "/jarvis-brain/desk", "Queue")
    tiles += _j19_card("Active Job", active_text, "/jarvis-brain/job", "Job")
    tiles += _j19_card("Crew Flow", "Step-by-step crew workflow.", "/jarvis-brain/crew", "Crew")
    tiles += _j19_card("Client View", "Client-safe Jarvis page.", "/jarvis-brain/client", "Client")
    tiles += _j19_card("Help", "Command cheat sheet.", "/jarvis-brain/help", "Help")
    tiles += _j19_card("System Check", "Routes, tables, storage, and status.", "/jarvis-brain/system", "Status")
    tiles += _j19_card("Logout", "Fully log out of the app.", "/logout", "Exit", True)

    jobs_count = _j19_table_count("poolops2_jobs")
    clients_count = _j19_table_count("poolops2_clients")
    props_count = _j19_table_count("poolops2_properties")
    office_count = _j19_table_count("invisible_office_items")
    logs_count = _j19_table_count("field_logs")

    mode_text = f"{role.upper()} / {name}"
    if switched:
        mode_text += " ? TEST MODE"

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis Home</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#070a0f; color:#f5efe3; }}
    .wrap {{ max-width:1240px; margin:0 auto; padding:26px; }}
    .hero {{ background:linear-gradient(135deg,#111722,#05070b); border:1px solid #5d421d; border-radius:22px; padding:24px; box-shadow:0 20px 60px rgba(0,0,0,.45); }}
    h1 {{ margin:0 0 8px; font-size:38px; letter-spacing:.08em; }}
    .sub {{ color:#d9b56d; margin-bottom:20px; font-size:18px; }}
    .stats {{ display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin:16px 0; }}
    @media(max-width:950px) {{ .stats {{ grid-template-columns:repeat(2,1fr); }} }}
    .stat {{ background:#05070b; border:1px solid #2d2113; border-radius:14px; padding:14px; }}
    .stat b {{ font-size:28px; color:#d9b56d; }}
    .tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:14px; margin-top:18px; }}
    .tile {{ display:block; text-decoration:none; color:#f5efe3; background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; min-height:140px; }}
    .tile:hover {{ border-color:#b8873a; transform:translateY(-1px); }}
    .tile.danger {{ border-color:#b8873a; background:#1a1308; }}
    .tile h2 {{ margin:8px 0; font-size:24px; }}
    .tile p {{ color:#e8dcc7; line-height:1.4; }}
    .tag {{ display:inline-block; padding:6px 10px; border:1px solid #6b4b1f; border-radius:999px; color:#d9b56d; font-size:12px; }}
    .card {{ background:#101722; border:1px solid #2d2113; border-radius:18px; padding:18px; margin-top:16px; }}
    a {{ color:#d9a64a; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>J.A.R.V.I.S. HOME</h1>
    <div class="sub">Good to go. Viewing as: {_j19_esc(mode_text)}.</div>

    <div class="stats">
      <div class="stat"><b>{counts['open']}</b><br>Open brain items</div>
      <div class="stat"><b>{counts['billing']}</b><br>Billing</div>
      <div class="stat"><b>{counts['materials']}</b><br>Materials</div>
      <div class="stat"><b>{counts['problems']}</b><br>Problems</div>
      <div class="stat"><b>{counts['field_logs']}</b><br>Field logs</div>
      <div class="stat"><b>{counts['client_requests']}</b><br>Client requests</div>
    </div>

    <div class="card">
      <h2>Active Job</h2>
      <p>{_j19_esc(active_text)}</p>
      <p>Jobs: {_j19_esc(jobs_count)} ? Clients: {_j19_esc(clients_count)} ? Properties: {_j19_esc(props_count)} ? Invisible Office: {_j19_esc(office_count)} ? Field Logs: {_j19_esc(logs_count)}</p>
    </div>

    <div class="tiles">
      {tiles}
    </div>
  </div>
</div>
</body>
</html>
"""
    return HTMLResponse(html)


@app.get("/jarvis-home", response_class=HTMLResponse)
def jarvis_brain_level19_home_alias(request: Request):
    return RedirectResponse("/jarvis-brain/home", status_code=303)


@app.get("/jarvis-brain/home.json")
def jarvis_brain_level19_home_json(request: Request):
    user = _j19_user(request)
    return JSONResponse({
        "ok": True,
        "version": JARVIS_CLEAN_HOME_VERSION,
        "role": _j19_role(user),
        "name": _j19_name(user),
        "is_switched": _j19_is_switched(request),
        "has_admin_backup": _j19_has_admin_backup(request),
        "memory_counts": _j19_memory_counts(),
        "active_context": _j19_active_context(),
        "tables": {
            "jobs": _j19_table_count("poolops2_jobs"),
            "clients": _j19_table_count("poolops2_clients"),
            "properties": _j19_table_count("poolops2_properties"),
            "invisible_office": _j19_table_count("invisible_office_items"),
            "field_logs": _j19_table_count("field_logs"),
        },
    })

# ============================================================
# END JARVIS BRAIN LEVEL 19 CLEAN HOME BUTTONS
# ============================================================


# ============================================================
# JARVIS EASY CONTROL PANEL
# Big obvious buttons. Safe add-on only.
# Does NOT touch login, logout, or front-door redirects.
# ============================================================

import html as _jcp_html
import json as _jcp_json
from datetime import datetime as _jcp_datetime

try:
    from fastapi import Request
except Exception:
    pass

try:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except Exception:
    pass

JARVIS_CONTROL_PANEL_VERSION = "easy-control-panel-2026-07-04"


def _jcp_now():
    return _jcp_datetime.now().isoformat(timespec="seconds")


def _jcp_esc(value):
    return _jcp_html.escape(str(value or ""))


def _jcp_user(request):
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


def _jcp_role(user):
    role = str((user or {}).get("role") or (user or {}).get("login_type") or "guest").lower().strip()
    if role == "employee":
        role = "crew"
    return role


def _jcp_name(user):
    return str(
        (user or {}).get("name")
        or (user or {}).get("username")
        or (user or {}).get("email")
        or "User"
    ).strip()


def _jcp_has_admin_backup(request):
    try:
        return bool(request.session.get("jarvis_real_admin_user"))
    except Exception:
        return False


def _jcp_is_switched(request):
    try:
        return bool((request.session.get("jarvis_switched_login") or {}).get("active"))
    except Exception:
        return False


def _jcp_restore_admin(request):
    if not hasattr(request, "session"):
        return False

    session = request.session
    admin = session.get("jarvis_real_admin_user")

    if not admin:
        return False

    name = admin.get("name") or admin.get("username") or admin.get("email") or "Mike"
    email = admin.get("email") or ""
    uid = admin.get("user_id") or admin.get("id") or "admin"

    session["user"] = admin
    session["user_id"] = uid
    session["id"] = uid
    session["username"] = name
    session["name"] = name
    session["email"] = email
    session["role"] = "admin"
    session["login_type"] = "admin"
    session["is_admin"] = True
    session["is_employee"] = False
    session["is_crew"] = False
    session["is_client"] = False
    session.pop("employee_id", None)
    session.pop("client_id", None)
    session.pop("jarvis_switched_login", None)

    return True


def _jcp_card(title, desc, href, tag="", danger=False):
    danger_class = " danger" if danger else ""
    return f"""
    <a class="tile{danger_class}" href="{_jcp_esc(href)}">
      <div class="tag">{_jcp_esc(tag)}</div>
      <h2>{_jcp_esc(title)}</h2>
      <p>{_jcp_esc(desc)}</p>
    </a>
    """


@app.get("/jarvis-brain/control-panel", response_class=HTMLResponse)
def jarvis_easy_control_panel(request: Request):
    user = _jcp_user(request)

    if not user:
        return RedirectResponse("/login", status_code=303)

    role = _jcp_role(user)
    name = _jcp_name(user)
    switched = _jcp_is_switched(request)
    has_admin_backup = _jcp_has_admin_backup(request)

    mode = f"{role.upper()} / {name}"
    if switched:
        mode += " ? TEST MODE"

    return_admin_tile = ""
    if switched or has_admin_backup or role != "admin":
        return_admin_tile = _jcp_card(
            "RETURN TO ADMIN",
            "Get back to Mike/Admin immediately.",
            "/jarvis-brain/control-panel/return-admin",
            "Admin",
            True,
        )

    tiles = ""
    tiles += return_admin_tile
    tiles += _jcp_card("Switch Login", "Switch between Admin, Crew, and Client views.", "/jarvis-brain/login-bridge", "Switch")
    tiles += _jcp_card("Today Ops", "Daily board: billing, materials, jobs, crew, problems.", "/jarvis-brain/today", "Daily")
    tiles += _jcp_card("Ask / Mike Brain", "Main Jarvis command center.", "/jarvis-brain", "Brain")
    tiles += _jcp_card("Command Desk", "Open Jarvis queue and mark items done.", "/jarvis-brain/desk", "Queue")
    tiles += _jcp_card("Active Job", "Job-specific Jarvis memory.", "/jarvis-brain/job", "Job")
    tiles += _jcp_card("Crew Flow", "Step-by-step crew page.", "/jarvis-brain/crew", "Crew")
    tiles += _jcp_card("Client View", "Client-safe Jarvis page.", "/jarvis-brain/client", "Client")
    tiles += _jcp_card("Help", "Jarvis command cheat sheet.", "/jarvis-brain/help", "Help")
    tiles += _jcp_card("System Check", "Check routes, tables, and storage.", "/jarvis-brain/system", "Status")
    tiles += _jcp_card("Logout", "Fully log out.", "/logout", "Exit", True)

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Jarvis Control Panel</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{
      margin:0;
      font-family:Arial,sans-serif;
      background:#070a0f;
      color:#f5efe3;
    }}
    .wrap {{
      max-width:1250px;
      margin:0 auto;
      padding:26px;
    }}
    .hero {{
      background:linear-gradient(135deg,#111722,#05070b);
      border:1px solid #5d421d;
      border-radius:22px;
      padding:24px;
      box-shadow:0 20px 60px rgba(0,0,0,.45);
    }}
    h1 {{
      margin:0 0 8px;
      font-size:38px;
      letter-spacing:.08em;
    }}
    .sub {{
      color:#d9b56d;
      margin-bottom:20px;
      font-size:18px;
    }}
    .ask {{
      background:#101722;
      border:1px solid #2d2113;
      border-radius:18px;
      padding:18px;
      margin-top:16px;
    }}
    textarea {{
      width:100%;
      min-height:115px;
      box-sizing:border-box;
      border-radius:14px;
      border:1px solid #6b4b1f;
      background:#05070b;
      color:#fff;
      padding:14px;
      font-size:16px;
    }}
    button {{
      margin-top:10px;
      padding:13px 18px;
      border:0;
      border-radius:12px;
      background:#b8873a;
      color:#111;
      font-weight:900;
      cursor:pointer;
    }}
    .reply {{
      margin-top:12px;
      padding:13px;
      border-radius:12px;
      background:#05070b;
      border:1px solid #2d2113;
      min-height:24px;
      line-height:1.45;
    }}
    .chips {{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin-top:10px;
    }}
    .chips button {{
      border:1px solid #6b4b1f;
      border-radius:999px;
      background:#05070b;
      color:#f5efe3;
      padding:9px 11px;
      margin:0;
    }}
    .tiles {{
      display:grid;
      grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
      gap:14px;
      margin-top:18px;
    }}
    .tile {{
      display:block;
      text-decoration:none;
      color:#f5efe3;
      background:#101722;
      border:1px solid #2d2113;
      border-radius:18px;
      padding:18px;
      min-height:140px;
    }}
    .tile:hover {{
      border-color:#b8873a;
      transform:translateY(-1px);
    }}
    .tile.danger {{
      border-color:#b8873a;
      background:#1a1308;
    }}
    .tile h2 {{
      margin:8px 0;
      font-size:24px;
    }}
    .tile p {{
      color:#e8dcc7;
      line-height:1.4;
    }}
    .tag {{
      display:inline-block;
      padding:6px 10px;
      border:1px solid #6b4b1f;
      border-radius:999px;
      color:#d9b56d;
      font-size:12px;
    }}
    .result {{
      background:#05070b;
      border:1px solid #2d2113;
      border-radius:12px;
      padding:10px;
      margin-top:10px;
    }}
    .result b {{
      color:#d9b56d;
    }}
    .result a {{
      color:#d9a64a;
    }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>J.A.R.V.I.S. CONTROL PANEL</h1>
    <div class="sub">Viewing as: {_jcp_esc(mode)}</div>

    <div class="ask">
      <h2>Ask Jarvis Right Here</h2>
      <textarea id="cmd" placeholder="Jarvis, what am I forgetting?"></textarea>
      <br>
      <button onclick="sendJarvis()">Ask Jarvis</button>
      <button onclick="startVoice()">?? Voice</button>
      <button onclick="readBack()">?? Read Back</button>

      <div class="chips">
        <button onclick="fillCmd('Jarvis, what am I forgetting?')">Forgetting?</button>
        <button onclick="fillCmd('Jarvis, what is my active job?')">Active Job</button>
        <button onclick="fillCmd('Jarvis, find ')">Find</button>
        <button onclick="fillCmd('Jarvis, add this to billing: ')">Billing</button>
        <button onclick="fillCmd('Jarvis, field log: ')">Field Log</button>
        <button onclick="fillCmd('Jarvis, material needed: ')">Material</button>
      </div>

      <div class="reply" id="reply">Ready.</div>
    </div>

    <div class="tiles">
      {tiles}
    </div>
  </div>
</div>

<script>
let lastReply = "Ready.";

function fillCmd(t) {{
  document.getElementById("cmd").value = t;
  document.getElementById("cmd").focus();
}}

function esc(str) {{
  return String(str || "").replace(/[&<>"']/g, function(m) {{
    return ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}})[m];
  }});
}}

function render(data) {{
  let html = esc(data.reply || JSON.stringify(data));
  const cards = data.links || data.cards || [];

  if(cards && cards.length) {{
    html += "<br><br>";
    cards.forEach(function(x) {{
      html += '<div class="result">';
      html += '<b>' + esc(x.kind || "Answer") + '</b><br>';
      if(x.url && x.url !== "#") {{
        html += '<a href="' + esc(x.url) + '">' + esc(x.title || "") + '</a>';
      }} else {{
        html += '<strong>' + esc(x.title || "") + '</strong>';
      }}
      if(x.detail) {{
        html += '<div>' + esc(x.detail) + '</div>';
      }}
      html += '</div>';
    }});
  }}

  return html;
}}

async function sendJarvis() {{
  const box = document.getElementById("cmd");
  const reply = document.getElementById("reply");
  const text = box.value.trim();

  if(!text) {{
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
    reply.innerHTML = render(data);
    lastReply = data.reply || JSON.stringify(data);
    readBack(false);
  }} catch(err) {{
    reply.innerText = "Jarvis failed: " + err;
    lastReply = reply.innerText;
    readBack(false);
  }}
}}

function readBack() {{
  if(!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const msg = new SpeechSynthesisUtterance(lastReply || "Nothing to read back yet.");
  msg.rate = 1;
  msg.pitch = 1;
  window.speechSynthesis.speak(msg);
}}

function startVoice() {{
  const reply = document.getElementById("reply");
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  if(!SR) {{
    reply.innerText = "Voice is not available in this browser. Use Chrome or Edge.";
    lastReply = reply.innerText;
    return;
  }}

  const rec = new SR();
  rec.lang = "en-US";
  rec.interimResults = false;
  rec.maxAlternatives = 1;

  reply.innerText = "Listening...";
  lastReply = reply.innerText;

  rec.onresult = function(event) {{
    const text = event.results[0][0].transcript;
    document.getElementById("cmd").value = text;
    sendJarvis();
  }};

  rec.onerror = function(event) {{
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


@app.get("/jarvis-control", response_class=HTMLResponse)
def jarvis_easy_control_panel_alias(request: Request):
    return RedirectResponse("/jarvis-brain/control-panel", status_code=303)


@app.get("/jarvis-brain/control-panel/return-admin")
def jarvis_easy_control_panel_return_admin(request: Request):
    ok = _jcp_restore_admin(request)
    if ok:
        return RedirectResponse("/jarvis-brain/control-panel", status_code=303)
    return RedirectResponse("/logout", status_code=303)


@app.get("/jarvis-brain/control-panel.json")
def jarvis_easy_control_panel_json(request: Request):
    user = _jcp_user(request)
    return JSONResponse({
        "ok": True,
        "version": JARVIS_CONTROL_PANEL_VERSION,
        "role": _jcp_role(user),
        "name": _jcp_name(user),
        "is_switched": _jcp_is_switched(request),
        "has_admin_backup": _jcp_has_admin_backup(request),
    })

# ============================================================
# END JARVIS EASY CONTROL PANEL
# ============================================================


# ============================================================
# HEINLIN GLOBAL CREST BACKGROUND
# Injects /static/jarvis-global-crest.css into every HTML page.
# Safe visual-only add-on. Does NOT touch login/logout/routing.
# ============================================================

try:
    from starlette.responses import Response as _CrestResponse
except Exception:
    pass

HEINLIN_GLOBAL_CREST_VERSION = "global-crest-background-2026-07-04"


def _crest_should_inject(path):
    if not path:
        return False

    # Login already has its own full background image.
    # Do not stack the global crest watermark on top of it.
    if path in ("/login", "/login/", "/logout", "/logout/"):
        return False

    if path.startswith(("/static", "/assets", "/api", "/docs", "/openapi")):
        return False

    if path.endswith((".json", ".png", ".jpg", ".jpeg", ".webp", ".css", ".js", ".ico")):
        return False

    return True


def _crest_link_tag():
    return '<link rel="stylesheet" href="/static/jarvis-global-crest.css?v=20260704">'


@app.middleware("http")
async def heinlin_global_crest_background_middleware(request, call_next):
    response = await call_next(request)

    if not _crest_should_inject(request.url.path):
        return response

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        return response

    try:
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        html = body.decode("utf-8", errors="replace")
        link = _crest_link_tag()

        if "/static/jarvis-global-crest.css" not in html:
            if "</head>" in html.lower():
                import re as _crest_re
                html = _crest_re.sub(r"</head>", link + "\n</head>", html, count=1, flags=_crest_re.I)
            else:
                html = link + html

        headers = dict(response.headers)
        headers.pop("content-length", None)

        return _CrestResponse(
            content=html,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )
    except Exception as exc:
        print("Crest background inject skipped:", exc)
        return response


@app.get("/jarvis-brain/crest-check")
def heinlin_global_crest_check():
    from pathlib import Path as _Path
    crest_path = _Path("app/static/heinlin-crest.png")
    css_path = _Path("app/static/jarvis-global-crest.css")

    return {
        "ok": True,
        "version": HEINLIN_GLOBAL_CREST_VERSION,
        "crest_exists": crest_path.exists(),
        "crest_expected_path": str(crest_path),
        "css_exists": css_path.exists(),
        "css_path": str(css_path),
        "note": "If crest_exists is false, put your crest image at app/static/heinlin-crest.png",
    }

# ============================================================
# END HEINLIN GLOBAL CREST BACKGROUND
# ============================================================


# ============================================================
# JARVIS QUESTION INTERCEPT FIX
# Makes questions answer inline instead of saving as job memory.
# ============================================================

import json as _jq_json
import re as _jq_re

try:
    from fastapi.responses import JSONResponse as _JQJSONResponse
except Exception:
    pass


def _jq_card(kind, title, detail="", url="#"):
    return {
        "kind": kind,
        "title": title,
        "detail": detail,
        "url": url,
    }


def _jq_is_question(text):
    low = str(text or "").lower().strip()

    if "?" in low:
        return True

    question_starts = (
        "jarvis what",
        "jarvis why",
        "jarvis how",
        "jarvis when",
        "jarvis where",
        "jarvis who",
        "what ",
        "why ",
        "how ",
        "when ",
        "where ",
        "who ",
        "can you",
        "can i",
        "do i",
        "does",
        "is there",
        "are there",
        "tell me",
        "explain",
    )

    return low.startswith(question_starts)


def _jq_answer(text):
    low = str(text or "").lower().strip()

    if "what" in low and ("cannot do" in low or "can't do" in low or "cant do" in low):
        return {
            "reply": (
                "Right now, I can answer inside Jarvis, save notes, save billing notes, save material notes, "
                "save field logs, track active job context, show job/client/property/search matches, help switch views, "
                "and summarize what I can see. What I still cannot fully do yet is directly edit every part of the app "
                "like a human clicking buttons, create invoices in QuickBooks, send texts/emails automatically, approve photos, "
                "control external systems, or make real admin changes unless that action has been specifically wired into the app."
            ),
            "links": [
                _jq_card("Can Do", "Save job memory", "Billing notes, materials, field logs, problems, follow-ups, active job context."),
                _jq_card("Can Do", "Answer inline", "Questions should now answer here instead of being filed as a note."),
                _jq_card("Not Fully Wired Yet", "True app control", "Jarvis still needs specific action routes before it can edit every app record safely."),
                _jq_card("Not Fully Wired Yet", "Outside systems", "QuickBooks, texts, email, Pentair, and other external systems need integrations before Jarvis can act there."),
            ],
        }

    if "active job" in low:
        return {
            "reply": "Your active job is the job shown on the current Jarvis page. Use ?Jarvis, set active job to Alexander? to change it.",
            "links": [
                _jq_card("Active Job", "Change active job", "Say: Jarvis, set active job to [client name or address]."),
                _jq_card("Open", "Active Job Center", "Open the active job page.", "/jarvis-brain/job"),
            ],
        }

    if "switch login" in low or "switch logins" in low or "return to admin" in low:
        return {
            "reply": "Use the Login Bridge to switch between Admin, Crew, and Client. Use Return to Admin to get back to Mike/Admin.",
            "links": [
                _jq_card("Switch Login", "Login Bridge", "Switch between Admin, Crew, and Client.", "/jarvis-brain/login-bridge"),
                _jq_card("Return", "Return to Admin", "Go back to Mike/Admin.", "/jarvis-brain/return-admin"),
            ],
        }

    if "what am i forgetting" in low or "what matters" in low:
        return {
            "reply": "Check open billing notes, materials, problems, follow-ups, overdue jobs, and client requests. Those are the things most likely to bite you.",
            "links": [
                _jq_card("Open", "Today Ops", "Daily command board.", "/jarvis-brain/today"),
                _jq_card("Open", "Command Desk", "Open Jarvis queue.", "/jarvis-brain/desk"),
            ],
        }

    return {
        "reply": (
            "I heard that as a question, not a job note. I can answer it here now. "
            "If you want me to save something, start with billing note, field log, material needed, problem found, or remind me."
        ),
        "links": [
            _jq_card("Tip", "Ask questions normally", "Example: Jarvis, what am I forgetting?"),
            _jq_card("Tip", "Save notes intentionally", "Example: Jarvis, field log: cleaned heater and tested operation."),
        ],
    }


@app.middleware("http")
async def jarvis_question_intercept_middleware(request, call_next):
    if request.url.path != "/jarvis-brain/command" or request.method.upper() != "POST":
        return await call_next(request)

    try:
        body = await request.body()
        payload = _jq_json.loads(body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    text = str(payload.get("text") or payload.get("message") or "").strip()

    if text and _jq_is_question(text):
        answer = _jq_answer(text)
        return _JQJSONResponse({
            "ok": True,
            "inline_answer_mode": True,
            "reply": answer["reply"],
            "links": answer.get("links", []),
        })

    return await call_next(request)

# ============================================================
# END JARVIS QUESTION INTERCEPT FIX
# ============================================================

