import os
from datetime import date
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./poolops.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

app = FastAPI(title="HC Pool Ops", version="1.0.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def db_execute(sql: str, params: dict | None = None):
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})


def db_one(sql: str, params: dict | None = None):
    with engine.begin() as conn:
        row = conn.execute(text(sql), params or {}).mappings().first()
        return dict(row) if row else None


def db_all(sql: str, params: dict | None = None):
    with engine.begin() as conn:
        rows = conn.execute(text(sql), params or {}).mappings().all()
        return [dict(r) for r in rows]


def init_db():
    db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            full_name TEXT DEFAULT '',
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user'
        )
    """)

    db_execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            qb_customer_id TEXT DEFAULT '',
            portal_user_id INTEGER
        )
    """)

    db_execute("""
        CREATE TABLE IF NOT EXISTS properties (
            id SERIAL PRIMARY KEY,
            client_id INTEGER,
            name TEXT DEFAULT '',
            address TEXT DEFAULT '',
            city TEXT DEFAULT '',
            state TEXT DEFAULT '',
            zip_code TEXT DEFAULT ''
        )
    """)

    db_execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            role TEXT DEFAULT '',
            active TEXT DEFAULT 'Yes'
        )
    """)
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return HTMLResponse("""
    <html>
    <head><title>Login</title></head>
    <body style="font-family:Arial;max-width:400px;margin:80px auto;">
        <h1>HC Pool Ops Login</h1>
        <form method="post" action="/login">
            <label>Username</label><br>
            <input name="username" style="width:100%;padding:10px;"><br><br>
            <label>Password</label><br>
            <input name="password" type="password" style="width:100%;padding:10px;"><br><br>
            <button type="submit" style="width:100%;padding:12px;">Login</button>
        </form>
    </body>
    </html>
    """)

    existing = db_one("SELECT id FROM users WHERE username = :username", {"username": "admin"})
    if not existing:
        db_execute(
            """
            INSERT INTO users (full_name, username, password, role)
            VALUES (:full_name, :username, :password, :role)
            """,
            {
                "full_name": "Mike Heinlin",
                "username": "admin",
                "password": "admin",
                "role": "admin",
            },
        )


init_db()


def get_current_user(request: Request):
    user = request.session.get("user") if hasattr(request, "session") else None
    return user


def require_login(request: Request):
    user = get_current_user(request)
    if not user:
        return None
    return user


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    if not hasattr(request, "session"):
        request.scope["session"] = {}
    response = await call_next(request)
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/dashboard", status_code=303)

    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": None},
    )


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = db_one(
        """
        SELECT id, full_name, username, role
        FROM users
        WHERE username = :username AND password = :password
        """,
        {"username": username, "password": password},
    )

    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
        )

    request.session["user"] = user
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    clients_count = db_one("SELECT COUNT(*) AS count FROM clients")["count"]
    properties_count = db_one("SELECT COUNT(*) AS count FROM properties")["count"]
    jobs_count = db_one("SELECT COUNT(*) AS count FROM jobs")["count"]
    open_slots = db_one("SELECT COUNT(*) AS count FROM jobs WHERE status != 'Complete'")["count"]

    recent_jobs = db_all("""
        SELECT 
            jobs.id,
            jobs.title,
            jobs.status,
            jobs.scheduled_date,
            jobs.crew,
            COALESCE(properties.name, '') AS property_name
        FROM jobs
        LEFT JOIN properties ON jobs.property_id = properties.id
        ORDER BY jobs.id DESC
        LIMIT 10
    """)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "title": "Dashboard",
            "user": user,
            "clients_count": clients_count,
            "properties_count": properties_count,
            "jobs_count": jobs_count,
            "open_slots": open_slots,
            "recent_jobs": recent_jobs,
        },
    )


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    users = db_all("SELECT id, full_name, username, role FROM users ORDER BY id DESC")

    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "title": "Users",
            "user": user,
            "users": users,
            "error": None,
        },
    )


@app.post("/users")
def add_user(
    request: Request,
    full_name: str = Form(""),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db_execute(
        """
        INSERT INTO users (full_name, username, password, role)
        VALUES (:full_name, :username, :password, :role)
        """,
        {
            "full_name": full_name,
            "username": username,
            "password": password,
            "role": role,
        },
    )

    return RedirectResponse(url="/users", status_code=303)


@app.post("/users/delete")
def delete_user(request: Request, id: int = Form(...)):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db_execute("DELETE FROM users WHERE id = :id", {"id": id})
    return RedirectResponse(url="/users", status_code=303)


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    clients = db_all("""
        SELECT 
            clients.*,
            users.full_name AS portal_user_full_name,
            users.username AS portal_user_username
        FROM clients
        LEFT JOIN users ON clients.portal_user_id = users.id
        ORDER BY clients.id DESC
    """)

    users = db_all("SELECT id, full_name, username FROM users ORDER BY full_name")

    return templates.TemplateResponse(
        request,
        "clients.html",
        {
            "title": "Clients",
            "user": user,
            "clients": clients,
            "users": users,
            "error": None,
        },
    )


@app.post("/clients")
def add_client(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    qb_customer_id: str = Form(""),
    portal_user_id: Optional[int] = Form(None),
):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db_execute(
        """
        INSERT INTO clients (name, phone, email, qb_customer_id, portal_user_id)
        VALUES (:name, :phone, :email, :qb_customer_id, :portal_user_id)
        """,
        {
            "name": name,
            "phone": phone,
            "email": email,
            "qb_customer_id": qb_customer_id,
            "portal_user_id": portal_user_id,
        },
    )

    return RedirectResponse(url="/clients", status_code=303)


@app.post("/clients/delete")
def delete_client(request: Request, id: int = Form(...)):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db_execute("DELETE FROM clients WHERE id = :id", {"id": id})
    return RedirectResponse(url="/clients", status_code=303)


@app.get("/properties", response_class=HTMLResponse)
def properties_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    clients = db_all("SELECT id, name FROM clients ORDER BY name")

    properties = db_all("""
        SELECT 
            properties.*,
            clients.name AS client_name
        FROM properties
        LEFT JOIN clients ON properties.client_id = clients.id
        ORDER BY properties.id DESC
    """)

    return templates.TemplateResponse(
        request,
        "properties.html",
        {
            "title": "Properties",
            "user": user,
            "properties": properties,
            "clients": clients,
            "error": None,
        },
    )


@app.post("/properties")
def create_property(
    request: Request,
    client_id: int = Form(...),
    name: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db_execute(
        """
        INSERT INTO properties (client_id, name, address, city, state, zip_code)
        VALUES (:client_id, :name, :address, :city, :state, :zip_code)
        """,
        {
            "client_id": client_id,
            "name": name,
            "address": address,
            "city": city,
            "state": state,
            "zip_code": zip_code,
        },
    )

    return RedirectResponse(url="/properties", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    properties = db_all("SELECT id, name FROM properties ORDER BY name")

    jobs = db_all("""
        SELECT
            jobs.*,
            properties.name AS property_name
        FROM jobs
        LEFT JOIN properties ON jobs.property_id = properties.id
        ORDER BY jobs.id DESC
    """)

    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "title": "Jobs",
            "user": user,
            "jobs": jobs,
            "properties": properties,
            "error": None,
        },
    )


@app.get("/jobs/new", response_class=HTMLResponse)
def new_job_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    properties = db_all("SELECT id, name FROM properties ORDER BY name")

    return templates.TemplateResponse(
        request,
        "jobs_form.html",
        {
            "title": "New Job",
            "user": user,
            "properties": properties,
            "error": None,
        },
    )


@app.post("/jobs")
def create_job(
    request: Request,
    property_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    status: str = Form("Open"),
    scheduled_date: str = Form(""),
    crew: str = Form(""),
):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db_execute(
        """
        INSERT INTO jobs (property_id, title, description, status, scheduled_date, crew)
        VALUES (:property_id, :title, :description, :status, :scheduled_date, :crew)
        """,
        {
            "property_id": property_id,
            "title": title,
            "description": description,
            "status": status,
            "scheduled_date": scheduled_date,
            "crew": crew,
        },
    )

    return RedirectResponse(url="/jobs", status_code=303)


@app.post("/jobs/delete")
def delete_job(request: Request, id: int = Form(...)):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db_execute("DELETE FROM jobs WHERE id = :id", {"id": id})
    return RedirectResponse(url="/jobs", status_code=303)


@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    jobs = db_all("""
        SELECT 
            jobs.*,
            properties.name AS property_name
        FROM jobs
        LEFT JOIN properties ON jobs.property_id = properties.id
        WHERE jobs.scheduled_date != ''
        ORDER BY jobs.scheduled_date ASC
    """)

    properties = db_all("SELECT id, name FROM properties ORDER BY name")

    return templates.TemplateResponse(
        request,
        "schedule.html",
        {
            "title": "Schedule",
            "user": user,
            "jobs": jobs,
            "properties": properties,
            "today": str(date.today()),
            "error": None,
        },
    )


@app.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    jobs = db_all("""
        SELECT 
            jobs.*,
            properties.name AS property_name
        FROM jobs
        LEFT JOIN properties ON jobs.property_id = properties.id
        WHERE jobs.scheduled_date != ''
        ORDER BY jobs.scheduled_date ASC
    """)

    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            "title": "Calendar",
            "user": user,
            "jobs": jobs,
            "error": None,
        },
    )


@app.get("/quickbooks", response_class=HTMLResponse)
def quickbooks_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    clients = db_all("SELECT * FROM clients ORDER BY name")

    return templates.TemplateResponse(
        request,
        "quickbooks.html",
        {
            "title": "QuickBooks",
            "user": user,
            "clients": clients,
            "error": None,
        },
    )


@app.get("/weather", response_class=HTMLResponse)
def weather_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "weather.html",
        {
            "title": "Weather",
            "user": user,
            "alerts": [],
            "error": None,
        },
    )