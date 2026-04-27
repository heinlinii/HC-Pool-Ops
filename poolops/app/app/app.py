import csv
import io
import os
import secrets
from calendar import Calendar, month_name
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text
from starlette.middleware.sessions import SessionMiddleware


APP_TITLE = "PoolOps Pro"
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Evansville")
DEFAULT_STATE = os.getenv("DEFAULT_STATE", "IN")
DEFAULT_LAT = float(os.getenv("DEFAULT_LAT", "37.9716"))
DEFAULT_LON = float(os.getenv("DEFAULT_LON", "-87.5711"))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./poolops.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
app = FastAPI(title=APP_TITLE)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "poolops-secret-key-change-this"),
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def is_postgres() -> bool:
    return engine.url.get_backend_name().startswith("postgres")


def id_column() -> str:
    return "SERIAL PRIMARY KEY" if is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"


def db_execute(sql: str, params: Optional[Dict[str, Any]] = None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {})


def db_one(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    with engine.begin() as conn:
        row = conn.execute(text(sql), params or {}).mappings().first()
        return dict(row) if row else None


def db_all(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    with engine.begin() as conn:
        return [dict(row) for row in conn.execute(text(sql), params or {}).mappings().all()]


def render(request: Request, template_name: str, context: Optional[Dict[str, Any]] = None):
    ctx = context or {}
    ctx.setdefault("app_title", APP_TITLE)
    ctx.setdefault("user", current_user(request))
    return templates.TemplateResponse(request, template_name, ctx)


def current_user(request: Request) -> Optional[Dict[str, Any]]:
    return request.session.get("user")


def require_user(request: Request) -> Optional[Dict[str, Any]]:
    user = current_user(request)
    if not user:
        return None
    return user


def redirect_login():
    return RedirectResponse("/login", status_code=303)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def money(value: Any) -> str:
    return f"${safe_float(value):,.2f}"


def ensure_column(table: str, column: str, definition: str):
    try:
        if is_postgres():
            db_execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        else:
            existing = db_all(f"PRAGMA table_info({table})")
            cols = {row["name"] for row in existing}
            if column not in cols:
                db_execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except Exception:
        # Never let a defensive migration take the app down.
        pass


def create_tables():
    pk = id_column()
    db_execute(f"""
    CREATE TABLE IF NOT EXISTS users (
        id {pk},
        full_name TEXT DEFAULT '',
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        active TEXT DEFAULT 'yes',
        created_at TEXT DEFAULT ''
    )
    """)

    db_execute(f"""
    CREATE TABLE IF NOT EXISTS clients (
        id {pk},
        name TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        qb_customer_id TEXT DEFAULT '',
        portal_user_id INTEGER,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT ''
    )
    """)

    db_execute(f"""
    CREATE TABLE IF NOT EXISTS properties (
        id {pk},
        client_id INTEGER,
        name TEXT DEFAULT '',
        address TEXT DEFAULT '',
        city TEXT DEFAULT '',
        state TEXT DEFAULT '',
        zip_code TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        latitude TEXT DEFAULT '',
        longitude TEXT DEFAULT '',
        created_at TEXT DEFAULT ''
    )
    """)

    db_execute(f"""
    CREATE TABLE IF NOT EXISTS jobs (
        id {pk},
        client_id INTEGER,
        property_id INTEGER,
        title TEXT DEFAULT '',
        job_type TEXT DEFAULT '',
        status TEXT DEFAULT 'New',
        billing_status TEXT DEFAULT 'Not Invoiced',
        invoice_number TEXT DEFAULT '',
        invoice_total TEXT DEFAULT '0',
        paid_status TEXT DEFAULT 'Unpaid',
        scheduled_date TEXT DEFAULT '',
        assigned_crew TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT ''
    )
    """)

    db_execute(f"""
    CREATE TABLE IF NOT EXISTS schedule (
        id {pk},
        job_id INTEGER,
        user_id INTEGER,
        scheduled_date TEXT DEFAULT '',
        scheduled_time TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT ''
    )
    """)

    db_execute(f"""
    CREATE TABLE IF NOT EXISTS time_clock (
        id {pk},
        user_id INTEGER,
        clock_in TEXT DEFAULT '',
        clock_out TEXT DEFAULT '',
        note TEXT DEFAULT '',
        created_at TEXT DEFAULT ''
    )
    """)

    db_execute(f"""
    CREATE TABLE IF NOT EXISTS weather_alerts (
        id {pk},
        alert_date TEXT DEFAULT '',
        location TEXT DEFAULT '',
        severity TEXT DEFAULT 'Watch',
        message TEXT DEFAULT '',
        source TEXT DEFAULT 'Open-Meteo',
        created_at TEXT DEFAULT ''
    )
    """)

    db_execute(f"""
    CREATE TABLE IF NOT EXISTS integration_settings (
        id {pk},
        service TEXT UNIQUE,
        access_token TEXT DEFAULT '',
        refresh_token TEXT DEFAULT '',
        realm_id TEXT DEFAULT '',
        expires_at TEXT DEFAULT '',
        updated_at TEXT DEFAULT ''
    )
    """)


def migrate_tables():
    user_cols = {
        "full_name": "TEXT DEFAULT ''",
        "username": "TEXT DEFAULT ''",
        "password": "TEXT DEFAULT ''",
        "role": "TEXT DEFAULT 'user'",
        "active": "TEXT DEFAULT 'yes'",
        "created_at": "TEXT DEFAULT ''",
    }
    client_cols = {
        "name": "TEXT DEFAULT ''",
        "phone": "TEXT DEFAULT ''",
        "email": "TEXT DEFAULT ''",
        "qb_customer_id": "TEXT DEFAULT ''",
        "portal_user_id": "INTEGER",
        "notes": "TEXT DEFAULT ''",
        "created_at": "TEXT DEFAULT ''",
    }
    property_cols = {
        "client_id": "INTEGER",
        "name": "TEXT DEFAULT ''",
        "address": "TEXT DEFAULT ''",
        "city": "TEXT DEFAULT ''",
        "state": "TEXT DEFAULT ''",
        "zip_code": "TEXT DEFAULT ''",
        "notes": "TEXT DEFAULT ''",
        "latitude": "TEXT DEFAULT ''",
        "longitude": "TEXT DEFAULT ''",
        "created_at": "TEXT DEFAULT ''",
    }
    job_cols = {
        "client_id": "INTEGER",
        "property_id": "INTEGER",
        "title": "TEXT DEFAULT ''",
        "job_type": "TEXT DEFAULT ''",
        "status": "TEXT DEFAULT 'New'",
        "billing_status": "TEXT DEFAULT 'Not Invoiced'",
        "invoice_number": "TEXT DEFAULT ''",
        "invoice_total": "TEXT DEFAULT '0'",
        "paid_status": "TEXT DEFAULT 'Unpaid'",
        "scheduled_date": "TEXT DEFAULT ''",
        "assigned_crew": "TEXT DEFAULT ''",
        "notes": "TEXT DEFAULT ''",
        "created_at": "TEXT DEFAULT ''",
    }
    schedule_cols = {
        "job_id": "INTEGER",
        "user_id": "INTEGER",
        "scheduled_date": "TEXT DEFAULT ''",
        "scheduled_time": "TEXT DEFAULT ''",
        "notes": "TEXT DEFAULT ''",
        "created_at": "TEXT DEFAULT ''",
    }
    clock_cols = {
        "user_id": "INTEGER",
        "clock_in": "TEXT DEFAULT ''",
        "clock_out": "TEXT DEFAULT ''",
        "note": "TEXT DEFAULT ''",
        "created_at": "TEXT DEFAULT ''",
    }
    weather_cols = {
        "alert_date": "TEXT DEFAULT ''",
        "location": "TEXT DEFAULT ''",
        "severity": "TEXT DEFAULT 'Watch'",
        "message": "TEXT DEFAULT ''",
        "source": "TEXT DEFAULT 'Open-Meteo'",
        "created_at": "TEXT DEFAULT ''",
    }
    settings_cols = {
        "service": "TEXT DEFAULT ''",
        "access_token": "TEXT DEFAULT ''",
        "refresh_token": "TEXT DEFAULT ''",
        "realm_id": "TEXT DEFAULT ''",
        "expires_at": "TEXT DEFAULT ''",
        "updated_at": "TEXT DEFAULT ''",
    }
    for table, cols in {
        "users": user_cols,
        "clients": client_cols,
        "properties": property_cols,
        "jobs": job_cols,
        "schedule": schedule_cols,
        "time_clock": clock_cols,
        "weather_alerts": weather_cols,
        "integration_settings": settings_cols,
    }.items():
        for column, definition in cols.items():
            ensure_column(table, column, definition)

    try:
        db_execute("UPDATE users SET full_name = username WHERE COALESCE(full_name, '') = ''")
    except Exception:
        pass


def seed_defaults():
    now = datetime.now().strftime("%Y-%m-%d")
    default_users = [
        ("Mike Heinlin", "admin", "admin", "admin"),
        ("Mike Heinlin", "mike", "1234", "admin"),
        ("Jake Crew", "jake", "1234", "crew"),
        ("Smith Client", "smith", "1234", "client"),
    ]
    for full_name, username, password, role in default_users:
        if not db_one("SELECT id FROM users WHERE username = :username", {"username": username}):
            db_execute(
                """
                INSERT INTO users (full_name, username, password, role, active, created_at)
                VALUES (:full_name, :username, :password, :role, 'yes', :created_at)
                """,
                {
                    "full_name": full_name,
                    "username": username,
                    "password": password,
                    "role": role,
                    "created_at": now,
                },
            )

    client = db_one("SELECT id FROM clients LIMIT 1")
    if not client:
        db_execute(
            """
            INSERT INTO clients (name, phone, email, notes, created_at)
            VALUES (:name, :phone, :email, :notes, :created_at)
            """,
            {
                "name": "Smith Family",
                "phone": "",
                "email": "smith@example.com",
                "notes": "Sample client. Replace with real QuickBooks import or manual entry.",
                "created_at": now,
            },
        )
        client = db_one("SELECT id FROM clients WHERE name = :name", {"name": "Smith Family"})

    prop = db_one("SELECT id FROM properties LIMIT 1")
    if not prop:
        db_execute(
            """
            INSERT INTO properties (client_id, name, address, city, state, zip_code, created_at)
            VALUES (:client_id, :name, :address, :city, :state, :zip_code, :created_at)
            """,
            {
                "client_id": client["id"] if client else None,
                "name": "Backyard Pool",
                "address": "123 Pool Drive",
                "city": "Evansville",
                "state": "IN",
                "zip_code": "47712",
                "created_at": now,
            },
        )
        prop = db_one("SELECT id FROM properties WHERE name = :name", {"name": "Backyard Pool"})

    if not db_one("SELECT id FROM jobs LIMIT 1"):
        db_execute(
            """
            INSERT INTO jobs
            (client_id, property_id, title, job_type, status, billing_status, invoice_total, paid_status, scheduled_date, assigned_crew, notes, created_at)
            VALUES
            (:client_id, :property_id, :title, :job_type, :status, :billing_status, :invoice_total, :paid_status, :scheduled_date, :assigned_crew, :notes, :created_at)
            """,
            {
                "client_id": client["id"] if client else None,
                "property_id": prop["id"] if prop else None,
                "title": "Spring Opening",
                "job_type": "Opening",
                "status": "Scheduled",
                "billing_status": "Not Invoiced",
                "invoice_total": "650",
                "paid_status": "Unpaid",
                "scheduled_date": now,
                "assigned_crew": "Jake Crew",
                "notes": "Sample job.",
                "created_at": now,
            },
        )


def init_db():
    create_tables()
    migrate_tables()
    seed_defaults()


init_db()


def qb_configured() -> bool:
    return bool(os.getenv("QUICKBOOKS_CLIENT_ID") and os.getenv("QUICKBOOKS_CLIENT_SECRET") and os.getenv("QUICKBOOKS_REDIRECT_URI"))


def qb_base_url() -> str:
    env = os.getenv("QUICKBOOKS_ENV", "sandbox").lower()
    if env == "production":
        return "https://quickbooks.api.intuit.com"
    return "https://sandbox-quickbooks.api.intuit.com"


def get_qb_settings() -> Optional[Dict[str, Any]]:
    return db_one("SELECT * FROM integration_settings WHERE service = 'quickbooks'")


def save_qb_settings(access_token: str = "", refresh_token: str = "", realm_id: str = "", expires_at: str = ""):
    existing = get_qb_settings()
    now = datetime.now().isoformat(timespec="seconds")
    if existing:
        db_execute(
            """
            UPDATE integration_settings
            SET access_token = :access_token, refresh_token = :refresh_token, realm_id = :realm_id, expires_at = :expires_at, updated_at = :updated_at
            WHERE service = 'quickbooks'
            """,
            {
                "access_token": access_token or existing.get("access_token", ""),
                "refresh_token": refresh_token or existing.get("refresh_token", ""),
                "realm_id": realm_id or existing.get("realm_id", ""),
                "expires_at": expires_at or existing.get("expires_at", ""),
                "updated_at": now,
            },
        )
    else:
        db_execute(
            """
            INSERT INTO integration_settings (service, access_token, refresh_token, realm_id, expires_at, updated_at)
            VALUES ('quickbooks', :access_token, :refresh_token, :realm_id, :expires_at, :updated_at)
            """,
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "realm_id": realm_id,
                "expires_at": expires_at,
                "updated_at": now,
            },
        )


@app.get("/health")
def health():
    return {"status": "ok", "app": APP_TITLE, "version": "final-working-build"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", {"error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = db_one(
        "SELECT id, full_name, username, role FROM users WHERE username = :username AND password = :password AND COALESCE(active, 'yes') = 'yes'",
        {"username": username, "password": password},
    )
    if not user:
        return render(request, "login.html", {"error": "Invalid username or password"})
    request.session["user"] = user
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = require_user(request)
    if not user:
        return redirect_login()
    stats = {
        "clients": db_one("SELECT COUNT(*) AS count FROM clients")["count"],
        "properties": db_one("SELECT COUNT(*) AS count FROM properties")["count"],
        "jobs": db_one("SELECT COUNT(*) AS count FROM jobs")["count"],
        "scheduled": db_one("SELECT COUNT(*) AS count FROM jobs WHERE status = 'Scheduled'")["count"],
        "ready_to_bill": db_one("SELECT COUNT(*) AS count FROM jobs WHERE billing_status = 'Ready To Bill'")["count"],
        "outstanding": db_one("SELECT COALESCE(SUM(CAST(NULLIF(invoice_total, '') AS NUMERIC)), 0) AS count FROM jobs WHERE paid_status != 'Paid'")["count"] if is_postgres() else db_one("SELECT COALESCE(SUM(CAST(NULLIF(invoice_total, '') AS REAL)), 0) AS count FROM jobs WHERE paid_status != 'Paid'")["count"],
    }
    recent_jobs = db_all(
        """
        SELECT jobs.*, clients.name AS client_name, properties.name AS property_name
        FROM jobs
        LEFT JOIN clients ON clients.id = jobs.client_id
        LEFT JOIN properties ON properties.id = jobs.property_id
        ORDER BY jobs.id DESC
        LIMIT 8
        """
    )
    upcoming = db_all(
        """
        SELECT schedule.*, jobs.title AS job_title, users.full_name AS crew_name
        FROM schedule
        LEFT JOIN jobs ON jobs.id = schedule.job_id
        LEFT JOIN users ON users.id = schedule.user_id
        WHERE schedule.scheduled_date >= :today
        ORDER BY schedule.scheduled_date ASC, schedule.scheduled_time ASC
        LIMIT 8
        """,
        {"today": date.today().isoformat()},
    )
    alerts = db_all("SELECT * FROM weather_alerts ORDER BY alert_date ASC, id DESC LIMIT 5")
    return render(
        request,
        "dashboard.html",
        {"stats": stats, "recent_jobs": recent_jobs, "upcoming": upcoming, "alerts": alerts, "money": money},
    )


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    user = require_user(request)
    if not user:
        return redirect_login()
    users = db_all("SELECT * FROM users ORDER BY id DESC")
    return render(request, "users.html", {"users": users})


@app.post("/users")
def add_user(request: Request, full_name: str = Form(...), username: str = Form(...), password: str = Form(...), role: str = Form("user")):
    if not require_user(request):
        return redirect_login()
    db_execute(
        """
        INSERT INTO users (full_name, username, password, role, active, created_at)
        VALUES (:full_name, :username, :password, :role, 'yes', :created_at)
        """,
        {"full_name": full_name, "username": username, "password": password, "role": role, "created_at": datetime.now().strftime("%Y-%m-%d")},
    )
    return RedirectResponse("/users", status_code=303)


@app.post("/users/delete")
def delete_user(request: Request, id: int = Form(...)):
    if not require_user(request):
        return redirect_login()
    db_execute("DELETE FROM users WHERE id = :id", {"id": id})
    return RedirectResponse("/users", status_code=303)


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    if not require_user(request):
        return redirect_login()
    clients = db_all("SELECT * FROM clients ORDER BY id DESC")
    users = db_all("SELECT id, full_name, username FROM users ORDER BY full_name")
    return render(request, "clients.html", {"clients": clients, "users": users})


@app.post("/clients")
def add_client(request: Request, name: str = Form(...), phone: str = Form(""), email: str = Form(""), qb_customer_id: str = Form(""), portal_user_id: str = Form(""), notes: str = Form("")):
    if not require_user(request):
        return redirect_login()
    db_execute(
        """
        INSERT INTO clients (name, phone, email, qb_customer_id, portal_user_id, notes, created_at)
        VALUES (:name, :phone, :email, :qb_customer_id, :portal_user_id, :notes, :created_at)
        """,
        {
            "name": name,
            "phone": phone,
            "email": email,
            "qb_customer_id": qb_customer_id,
            "portal_user_id": int(portal_user_id) if portal_user_id else None,
            "notes": notes,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
        },
    )
    return RedirectResponse("/clients", status_code=303)


@app.post("/clients/delete")
def delete_client(request: Request, id: int = Form(...)):
    if not require_user(request):
        return redirect_login()
    db_execute("DELETE FROM clients WHERE id = :id", {"id": id})
    return RedirectResponse("/clients", status_code=303)


@app.get("/properties", response_class=HTMLResponse)
def properties_page(request: Request):
    if not require_user(request):
        return redirect_login()
    properties = db_all(
        """
        SELECT properties.*, clients.name AS client_name
        FROM properties
        LEFT JOIN clients ON clients.id = properties.client_id
        ORDER BY properties.id DESC
        """
    )
    clients = db_all("SELECT * FROM clients ORDER BY name")
    return render(request, "properties.html", {"properties": properties, "clients": clients})


@app.post("/properties")
def add_property(request: Request, client_id: str = Form(""), name: str = Form(...), address: str = Form(""), city: str = Form(""), state: str = Form(""), zip_code: str = Form(""), latitude: str = Form(""), longitude: str = Form(""), notes: str = Form("")):
    if not require_user(request):
        return redirect_login()
    db_execute(
        """
        INSERT INTO properties (client_id, name, address, city, state, zip_code, latitude, longitude, notes, created_at)
        VALUES (:client_id, :name, :address, :city, :state, :zip_code, :latitude, :longitude, :notes, :created_at)
        """,
        {
            "client_id": int(client_id) if client_id else None,
            "name": name,
            "address": address,
            "city": city,
            "state": state,
            "zip_code": zip_code,
            "latitude": latitude,
            "longitude": longitude,
            "notes": notes,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
        },
    )
    return RedirectResponse("/properties", status_code=303)


@app.post("/properties/delete")
def delete_property(request: Request, id: int = Form(...)):
    if not require_user(request):
        return redirect_login()
    db_execute("DELETE FROM properties WHERE id = :id", {"id": id})
    return RedirectResponse("/properties", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    if not require_user(request):
        return redirect_login()
    jobs = db_all(
        """
        SELECT jobs.*, clients.name AS client_name, properties.name AS property_name, properties.address AS property_address
        FROM jobs
        LEFT JOIN clients ON clients.id = jobs.client_id
        LEFT JOIN properties ON properties.id = jobs.property_id
        ORDER BY jobs.id DESC
        """
    )
    clients = db_all("SELECT * FROM clients ORDER BY name")
    properties = db_all("SELECT * FROM properties ORDER BY name")
    users = db_all("SELECT * FROM users ORDER BY full_name")
    return render(request, "jobs.html", {"jobs": jobs, "clients": clients, "properties": properties, "users": users, "money": money})


@app.get("/jobs/new")
def jobs_new():
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs")
def add_job(request: Request, title: str = Form(...), client_id: str = Form(""), property_id: str = Form(""), job_type: str = Form(""), status: str = Form("New"), scheduled_date: str = Form(""), assigned_crew: str = Form(""), invoice_total: str = Form("0"), notes: str = Form("")):
    if not require_user(request):
        return redirect_login()
    db_execute(
        """
        INSERT INTO jobs (client_id, property_id, title, job_type, status, billing_status, invoice_total, paid_status, scheduled_date, assigned_crew, notes, created_at)
        VALUES (:client_id, :property_id, :title, :job_type, :status, 'Not Invoiced', :invoice_total, 'Unpaid', :scheduled_date, :assigned_crew, :notes, :created_at)
        """,
        {
            "client_id": int(client_id) if client_id else None,
            "property_id": int(property_id) if property_id else None,
            "title": title,
            "job_type": job_type,
            "status": status,
            "invoice_total": invoice_total,
            "scheduled_date": scheduled_date,
            "assigned_crew": assigned_crew,
            "notes": notes,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
        },
    )
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/delete")
def delete_job(request: Request, id: int = Form(...)):
    if not require_user(request):
        return redirect_login()
    db_execute("DELETE FROM jobs WHERE id = :id", {"id": id})
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/status")
def job_status(request: Request, id: int = Form(...), status: str = Form(...)):
    if not require_user(request):
        return redirect_login()
    db_execute("UPDATE jobs SET status = :status WHERE id = :id", {"id": id, "status": status})
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/start")
def job_start(request: Request, id: int = Form(...)):
    if not require_user(request):
        return redirect_login()
    db_execute("UPDATE jobs SET status = 'In Progress' WHERE id = :id", {"id": id})
    return RedirectResponse("/my-day", status_code=303)


@app.post("/jobs/complete")
def job_complete(request: Request, id: int = Form(...)):
    if not require_user(request):
        return redirect_login()
    db_execute("UPDATE jobs SET status = 'Complete', billing_status = 'Ready To Bill' WHERE id = :id", {"id": id})
    return RedirectResponse("/my-day", status_code=303)


@app.post("/jobs/ready-to-bill")
def job_ready_to_bill(request: Request, id: int = Form(...)):
    if not require_user(request):
        return redirect_login()
    db_execute("UPDATE jobs SET billing_status = 'Ready To Bill' WHERE id = :id", {"id": id})
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/billing")
def job_billing(request: Request, id: int = Form(...), invoice_number: str = Form(""), invoice_total: str = Form("0"), paid_status: str = Form("Unpaid")):
    if not require_user(request):
        return redirect_login()
    invoice_number = invoice_number or f"INV-{id:04d}"
    billing_status = "Paid" if paid_status == "Paid" else "Invoiced"
    db_execute(
        """
        UPDATE jobs
        SET invoice_number = :invoice_number,
            invoice_total = :invoice_total,
            paid_status = :paid_status,
            billing_status = :billing_status
        WHERE id = :id
        """,
        {"id": id, "invoice_number": invoice_number, "invoice_total": invoice_total, "paid_status": paid_status, "billing_status": billing_status},
    )
    return RedirectResponse("/jobs", status_code=303)


@app.get("/invoice/{job_id}", response_class=HTMLResponse)
def invoice_page(request: Request, job_id: int):
    if not require_user(request):
        return redirect_login()
    job = db_one(
        """
        SELECT jobs.*, clients.name AS client_name, clients.phone AS client_phone, clients.email AS client_email,
               properties.name AS property_name, properties.address AS property_address, properties.city AS property_city, properties.state AS property_state, properties.zip_code AS property_zip
        FROM jobs
        LEFT JOIN clients ON clients.id = jobs.client_id
        LEFT JOIN properties ON properties.id = jobs.property_id
        WHERE jobs.id = :id
        """,
        {"id": job_id},
    )
    if not job:
        return RedirectResponse("/jobs", status_code=303)
    if not job.get("invoice_number"):
        inv = f"INV-{job_id:04d}"
        db_execute("UPDATE jobs SET invoice_number = :invoice_number, billing_status = 'Invoiced' WHERE id = :id", {"invoice_number": inv, "id": job_id})
        job["invoice_number"] = inv
        job["billing_status"] = "Invoiced"
    return render(request, "invoice.html", {"job": job, "money": money})


@app.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    if not require_user(request):
        return redirect_login()
    today = date.today()
    year = year or today.year
    month = month or today.month
    if month < 1:
        month = 12
        year -= 1
    if month > 12:
        month = 1
        year += 1
    cal = Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(year, month)
    first = date(year, month, 1).isoformat()
    last = weeks[-1][-1].isoformat()
    jobs = db_all(
        """
        SELECT id, title, scheduled_date, status, assigned_crew
        FROM jobs
        WHERE scheduled_date >= :first AND scheduled_date <= :last AND COALESCE(scheduled_date, '') != ''
        ORDER BY scheduled_date, id
        """,
        {"first": first, "last": last},
    )
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for job in jobs:
        by_day.setdefault(job.get("scheduled_date") or "", []).append(job)
    clients = db_all("SELECT * FROM clients ORDER BY name")
    properties = db_all("SELECT * FROM properties ORDER BY name")
    users = db_all("SELECT * FROM users ORDER BY full_name")
    prev_month = month - 1
    prev_year = year
    next_month = month + 1
    next_year = year
    if prev_month == 0:
        prev_month = 12
        prev_year -= 1
    if next_month == 13:
        next_month = 1
        next_year += 1
    return render(
        request,
        "calendar.html",
        {
            "weeks": weeks,
            "month": month,
            "year": year,
            "month_name": month_name[month],
            "today": today,
            "by_day": by_day,
            "clients": clients,
            "properties": properties,
            "users": users,
            "prev_month": prev_month,
            "prev_year": prev_year,
            "next_month": next_month,
            "next_year": next_year,
        },
    )


@app.post("/calendar/schedule")
def calendar_schedule(request: Request, scheduled_date: str = Form(...), title: str = Form(...), client_id: str = Form(""), property_id: str = Form(""), assigned_crew: str = Form(""), job_type: str = Form("Service"), notes: str = Form("")):
    if not require_user(request):
        return redirect_login()
    db_execute(
        """
        INSERT INTO jobs (client_id, property_id, title, job_type, status, scheduled_date, assigned_crew, notes, created_at)
        VALUES (:client_id, :property_id, :title, :job_type, 'Scheduled', :scheduled_date, :assigned_crew, :notes, :created_at)
        """,
        {
            "client_id": int(client_id) if client_id else None,
            "property_id": int(property_id) if property_id else None,
            "title": title,
            "job_type": job_type,
            "scheduled_date": scheduled_date,
            "assigned_crew": assigned_crew,
            "notes": notes,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
        },
    )
    dt = date.fromisoformat(scheduled_date)
    return RedirectResponse(f"/calendar?year={dt.year}&month={dt.month}", status_code=303)


@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request):
    if not require_user(request):
        return redirect_login()
    scheduled_jobs = db_all(
        """
        SELECT jobs.*, clients.name AS client_name, properties.name AS property_name
        FROM jobs
        LEFT JOIN clients ON clients.id = jobs.client_id
        LEFT JOIN properties ON properties.id = jobs.property_id
        WHERE COALESCE(jobs.scheduled_date, '') != ''
        ORDER BY jobs.scheduled_date ASC, jobs.id DESC
        """
    )
    return render(request, "schedule.html", {"jobs": scheduled_jobs})


@app.get("/my-day", response_class=HTMLResponse)
def my_day(request: Request):
    user = require_user(request)
    if not user:
        return redirect_login()
    jobs = db_all(
        """
        SELECT jobs.*, clients.name AS client_name, properties.name AS property_name, properties.address AS property_address
        FROM jobs
        LEFT JOIN clients ON clients.id = jobs.client_id
        LEFT JOIN properties ON properties.id = jobs.property_id
        WHERE jobs.status != 'Complete'
        ORDER BY jobs.scheduled_date ASC, jobs.id DESC
        """
    )
    active_clock = db_one("SELECT * FROM time_clock WHERE user_id = :user_id AND clock_out = '' ORDER BY id DESC LIMIT 1", {"user_id": user["id"]})
    return render(request, "my_day.html", {"jobs": jobs, "active_clock": active_clock})


@app.post("/clock/in")
def clock_in(request: Request):
    user = require_user(request)
    if not user:
        return redirect_login()
    active = db_one("SELECT id FROM time_clock WHERE user_id = :user_id AND clock_out = '' LIMIT 1", {"user_id": user["id"]})
    if not active:
        db_execute(
            "INSERT INTO time_clock (user_id, clock_in, clock_out, note, created_at) VALUES (:user_id, :clock_in, '', '', :created_at)",
            {"user_id": user["id"], "clock_in": datetime.now().isoformat(timespec="seconds"), "created_at": datetime.now().strftime("%Y-%m-%d")},
        )
    return RedirectResponse("/my-day", status_code=303)


@app.post("/clock/out")
def clock_out(request: Request):
    user = require_user(request)
    if not user:
        return redirect_login()
    active = db_one("SELECT id FROM time_clock WHERE user_id = :user_id AND clock_out = '' ORDER BY id DESC LIMIT 1", {"user_id": user["id"]})
    if active:
        db_execute("UPDATE time_clock SET clock_out = :clock_out WHERE id = :id", {"clock_out": datetime.now().isoformat(timespec="seconds"), "id": active["id"]})
    return RedirectResponse("/my-day", status_code=303)


@app.get("/quickbooks", response_class=HTMLResponse)
def quickbooks_page(request: Request):
    if not require_user(request):
        return redirect_login()
    settings = get_qb_settings()
    clients = db_all("SELECT * FROM clients WHERE COALESCE(qb_customer_id, '') != '' ORDER BY name LIMIT 50")
    return render(
        request,
        "quickbooks.html",
        {
            "configured": qb_configured(),
            "connected": bool(settings and settings.get("access_token") and settings.get("realm_id")),
            "settings": settings,
            "clients": clients,
        },
    )


@app.get("/quickbooks/connect")
def quickbooks_connect(request: Request):
    if not require_user(request):
        return redirect_login()
    if not qb_configured():
        return RedirectResponse("/quickbooks", status_code=303)
    state = secrets.token_urlsafe(16)
    request.session["qb_state"] = state
    params = {
        "client_id": os.getenv("QUICKBOOKS_CLIENT_ID"),
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": os.getenv("QUICKBOOKS_REDIRECT_URI"),
        "state": state,
    }
    return RedirectResponse("https://appcenter.intuit.com/connect/oauth2?" + urlencode(params), status_code=303)


@app.get("/quickbooks/callback")
def quickbooks_callback(request: Request, code: str = "", realmId: str = "", state: str = ""):
    if state != request.session.get("qb_state"):
        return RedirectResponse("/quickbooks", status_code=303)
    token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    auth = (os.getenv("QUICKBOOKS_CLIENT_ID", ""), os.getenv("QUICKBOOKS_CLIENT_SECRET", ""))
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": os.getenv("QUICKBOOKS_REDIRECT_URI", "")}
    try:
        response = requests.post(token_url, data=data, auth=auth, headers={"Accept": "application/json"}, timeout=20)
        payload = response.json()
        if response.ok:
            save_qb_settings(payload.get("access_token", ""), payload.get("refresh_token", ""), realmId, str(payload.get("expires_in", "")))
    except Exception:
        pass
    return RedirectResponse("/quickbooks", status_code=303)


@app.post("/quickbooks/import-customers")
def quickbooks_import_customers(request: Request):
    if not require_user(request):
        return redirect_login()
    settings = get_qb_settings()
    if not settings or not settings.get("access_token") or not settings.get("realm_id"):
        return RedirectResponse("/quickbooks", status_code=303)
    query = "select * from Customer startposition 1 maxresults 100"
    url = f"{qb_base_url()}/v3/company/{settings['realm_id']}/query"
    headers = {"Authorization": f"Bearer {settings['access_token']}", "Accept": "application/json"}
    try:
        response = requests.get(url, params={"query": query, "minorversion": "75"}, headers=headers, timeout=30)
        data = response.json()
        customers = data.get("QueryResponse", {}).get("Customer", [])
        for c in customers:
            qb_id = str(c.get("Id", ""))
            name = c.get("DisplayName") or c.get("FullyQualifiedName") or "QuickBooks Customer"
            email = (c.get("PrimaryEmailAddr") or {}).get("Address", "")
            phone = (c.get("PrimaryPhone") or {}).get("FreeFormNumber", "")
            existing = db_one("SELECT id FROM clients WHERE qb_customer_id = :qb_customer_id", {"qb_customer_id": qb_id})
            if existing:
                db_execute("UPDATE clients SET name = :name, phone = :phone, email = :email WHERE id = :id", {"id": existing["id"], "name": name, "phone": phone, "email": email})
            else:
                db_execute(
                    "INSERT INTO clients (name, phone, email, qb_customer_id, created_at) VALUES (:name, :phone, :email, :qb_customer_id, :created_at)",
                    {"name": name, "phone": phone, "email": email, "qb_customer_id": qb_id, "created_at": datetime.now().strftime("%Y-%m-%d")},
                )
    except Exception:
        pass
    return RedirectResponse("/quickbooks", status_code=303)


@app.post("/quickbooks/import-csv")
async def quickbooks_import_csv(request: Request, file: UploadFile = File(...)):
    if not require_user(request):
        return redirect_login()
    content = await file.read()
    text_content = content.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text_content))
    for row in reader:
        name = row.get("Display Name") or row.get("Name") or row.get("Customer") or row.get("Company") or ""
        if not name:
            continue
        email = row.get("Email") or row.get("Email Address") or ""
        phone = row.get("Phone") or row.get("Phone Number") or ""
        qb_id = row.get("Id") or row.get("Customer ID") or ""
        existing = db_one("SELECT id FROM clients WHERE name = :name", {"name": name})
        if existing:
            db_execute("UPDATE clients SET phone = :phone, email = :email, qb_customer_id = :qb_customer_id WHERE id = :id", {"phone": phone, "email": email, "qb_customer_id": qb_id, "id": existing["id"]})
        else:
            db_execute(
                "INSERT INTO clients (name, phone, email, qb_customer_id, created_at) VALUES (:name, :phone, :email, :qb_customer_id, :created_at)",
                {"name": name, "phone": phone, "email": email, "qb_customer_id": qb_id, "created_at": datetime.now().strftime("%Y-%m-%d")},
            )
    return RedirectResponse("/quickbooks", status_code=303)


@app.get("/weather", response_class=HTMLResponse)
def weather_page(request: Request):
    if not require_user(request):
        return redirect_login()
    alerts = db_all("SELECT * FROM weather_alerts ORDER BY alert_date ASC, id DESC LIMIT 30")
    upcoming_jobs = db_all("SELECT * FROM jobs WHERE COALESCE(scheduled_date, '') != '' ORDER BY scheduled_date ASC LIMIT 30")
    return render(request, "weather.html", {"alerts": alerts, "upcoming_jobs": upcoming_jobs, "default_city": DEFAULT_CITY, "default_state": DEFAULT_STATE})


@app.post("/weather/refresh")
def weather_refresh(request: Request, location: str = Form(f"{DEFAULT_CITY}, {DEFAULT_STATE}"), latitude: str = Form(""), longitude: str = Form("")):
    if not require_user(request):
        return redirect_login()
    lat = safe_float(latitude, DEFAULT_LAT)
    lon = safe_float(longitude, DEFAULT_LON)
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "precipitation_probability_max,windspeed_10m_max,temperature_2m_min,temperature_2m_max",
            "forecast_days": 10,
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "timezone": "America/Chicago",
        }
        data = requests.get(url, params=params, timeout=20).json()
        daily = data.get("daily", {})
        days = daily.get("time", [])
        precip = daily.get("precipitation_probability_max", [])
        wind = daily.get("windspeed_10m_max", [])
        low = daily.get("temperature_2m_min", [])
        high = daily.get("temperature_2m_max", [])
        for i, day in enumerate(days):
            messages = []
            sev = "Watch"
            p = precip[i] if i < len(precip) and precip[i] is not None else 0
            w = wind[i] if i < len(wind) and wind[i] is not None else 0
            lo = low[i] if i < len(low) and low[i] is not None else 99
            hi = high[i] if i < len(high) and high[i] is not None else 0
            if p >= 60:
                messages.append(f"Rain risk {p}%")
                sev = "Warning"
            elif p >= 40:
                messages.append(f"Rain watch {p}%")
            if w >= 25:
                messages.append(f"High wind {w} mph")
                sev = "Warning"
            elif w >= 18:
                messages.append(f"Wind watch {w} mph")
            if lo <= 38:
                messages.append(f"Cold low {lo}°F")
                sev = "Warning"
            if hi >= 95:
                messages.append(f"Heat watch {hi}°F")
            if messages:
                existing = db_one("SELECT id FROM weather_alerts WHERE alert_date = :alert_date AND location = :location", {"alert_date": day, "location": location})
                msg = "; ".join(messages)
                if existing:
                    db_execute("UPDATE weather_alerts SET severity = :severity, message = :message, created_at = :created_at WHERE id = :id", {"id": existing["id"], "severity": sev, "message": msg, "created_at": datetime.now().isoformat(timespec="seconds")})
                else:
                    db_execute(
                        "INSERT INTO weather_alerts (alert_date, location, severity, message, source, created_at) VALUES (:alert_date, :location, :severity, :message, 'Open-Meteo', :created_at)",
                        {"alert_date": day, "location": location, "severity": sev, "message": msg, "created_at": datetime.now().isoformat(timespec="seconds")},
                    )
    except Exception:
        pass
    return RedirectResponse("/weather", status_code=303)


@app.post("/weather/delete")
def weather_delete(request: Request, id: int = Form(...)):
    if not require_user(request):
        return redirect_login()
    db_execute("DELETE FROM weather_alerts WHERE id = :id", {"id": id})
    return RedirectResponse("/weather", status_code=303)
