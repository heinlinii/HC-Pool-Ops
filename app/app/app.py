import os
from decimal import Decimal

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, text


app = FastAPI(title="HG Pool Ops")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "poolops-secret-key-change-later"),
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./poolops.db"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def run(sql, params=None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {})


def rows(sql, params=None):
    result = run(sql, params)
    return [dict(r._mapping) for r in result]


def one(sql, params=None):
    result = run(sql, params).fetchone()
    return dict(result._mapping) if result else None


def money(value):
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def current_user(request: Request):
    return request.session.get("user")


def require_login(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


@app.on_event("startup")
def startup():
    create_tables()
    migrate_tables()
    seed_defaults()


def create_tables():
    run("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'crew'
    )
    """)

    run("""
    CREATE TABLE IF NOT EXISTS clients (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT,
        email TEXT
    )
    """)

    run("""
    CREATE TABLE IF NOT EXISTS properties (
        id SERIAL PRIMARY KEY,
        client_id INTEGER,
        name TEXT,
        address TEXT,
        city TEXT,
        state TEXT,
        zip TEXT
    )
    """)

    run("""
    CREATE TABLE IF NOT EXISTS jobs (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        client_id INTEGER,
        property_id INTEGER,
        status TEXT DEFAULT 'Scheduled',
        scheduled_date DATE,
        crew TEXT,
        amount NUMERIC DEFAULT 0,
        paid_amount NUMERIC DEFAULT 0,
        billing_status TEXT DEFAULT 'Unbilled',
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    run("""
    CREATE TABLE IF NOT EXISTS invoices (
        id SERIAL PRIMARY KEY,
        job_id INTEGER NOT NULL,
        client_id INTEGER,
        total NUMERIC DEFAULT 0,
        paid_amount NUMERIC DEFAULT 0,
        status TEXT DEFAULT 'Unpaid',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        paid_at TIMESTAMP
    )
    """)

    run("""
    CREATE TABLE IF NOT EXISTS time_clock (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        username TEXT,
        clock_in TIMESTAMP,
        clock_out TIMESTAMP
    )
    """)


def migrate_tables():
    columns = [
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS amount NUMERIC DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS paid_amount NUMERIC DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS billing_status TEXT DEFAULT 'Unbilled'",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    ]

    for sql in columns:
        try:
            run(sql)
        except Exception:
            pass


def seed_defaults():
    if not one("SELECT id FROM users WHERE username = :username", {"username": "mike"}):
        run("""
        INSERT INTO users (username, password, name, role)
        VALUES
        ('mike', '1234', 'Mike Heinlin', 'admin'),
        ('jake', '1234', 'Jake Crew', 'crew'),
        ('smith', '1234', 'Smith Client', 'client')
        """)

    if not one("SELECT id FROM clients LIMIT 1"):
        run("""
        INSERT INTO clients (name, phone, email)
        VALUES ('Smith Family', '', 'smith@example.com')
        """)

    if not one("SELECT id FROM properties LIMIT 1"):
        client = one("SELECT id FROM clients LIMIT 1")
        run("""
        INSERT INTO properties (client_id, name, address, city, state, zip)
        VALUES (:client_id, 'Backyard Pool', '123 Pool Drive', 'Evansville', 'IN', '47712')
        """, {"client_id": client["id"]})

    if not one("SELECT id FROM jobs LIMIT 1"):
        client = one("SELECT id FROM clients LIMIT 1")
        prop = one("SELECT id FROM properties LIMIT 1")
        run("""
        INSERT INTO jobs
        (title, description, client_id, property_id, status, scheduled_date, crew, amount, paid_amount, billing_status)
        VALUES
        ('Yep', 'Pool job', :client_id, :property_id, 'Scheduled', '2026-04-28', 'Jake Crew', 2500, 0, 'Unbilled'),
        ('Spring Opening', 'Open pool for season', :client_id, :property_id, 'Complete', '2026-04-24', 'Jake Crew', 650, 650, 'Paid')
        """, {"client_id": client["id"], "property_id": prop["id"]})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = one("""
        SELECT id, username, name, role
        FROM users
        WHERE username = :username AND password = :password
    """, {"username": username, "password": password})

    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
        )

    request.session["user"] = user
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(require_login)):
    total_jobs = one("SELECT COUNT(*) AS count FROM jobs")["count"]
    open_jobs = one("SELECT COUNT(*) AS count FROM jobs WHERE status != 'Complete'")["count"]
    completed_jobs = one("SELECT COUNT(*) AS count FROM jobs WHERE status = 'Complete'")["count"]
    total_clients = one("SELECT COUNT(*) AS count FROM clients")["count"]
    total_properties = one("SELECT COUNT(*) AS count FROM properties")["count"]

    billing = one("""
        SELECT 
            COALESCE(SUM(amount), 0) AS billing_total,
            COALESCE(SUM(paid_amount), 0) AS paid_total
        FROM jobs
    """)

    billing_total = money(billing["billing_total"])
    paid_total = money(billing["paid_total"])
    outstanding_total = billing_total - paid_total

    recent_jobs = rows("""
        SELECT 
            jobs.*,
            clients.name AS client_name,
            properties.name AS property_name,
            properties.address AS address
        FROM jobs
        LEFT JOIN clients ON clients.id = jobs.client_id
        LEFT JOIN properties ON properties.id = jobs.property_id
        ORDER BY jobs.id DESC
        LIMIT 10
    """)

    invoices = rows("""
        SELECT 
            invoices.*,
            jobs.title AS job_title,
            clients.name AS client_name
        FROM invoices
        LEFT JOIN jobs ON jobs.id = invoices.job_id
        LEFT JOIN clients ON clients.id = invoices.client_id
        ORDER BY invoices.id DESC
        LIMIT 10
    """)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "total_jobs": total_jobs,
        "open_jobs": open_jobs,
        "completed_jobs": completed_jobs,
        "clients_count": total_clients,
        "properties_count": total_properties,
        "jobs_count": total_jobs,
        "open_slots": open_jobs,
        "billing_total": billing_total,
        "paid_total": paid_total,
        "outstanding_total": outstanding_total,
        "recent_jobs": recent_jobs,
        "invoices": invoices,
    })


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, user=Depends(require_login)):
    jobs = rows("""
        SELECT 
            jobs.*,
            clients.name AS client_name,
            properties.name AS property_name,
            properties.address AS address
        FROM jobs
        LEFT JOIN clients ON clients.id = jobs.client_id
        LEFT JOIN properties ON properties.id = jobs.property_id
        ORDER BY jobs.scheduled_date DESC NULLS LAST, jobs.id DESC
    """)

    rows_html = ""

    for job in jobs:
        amount = money(job.get("amount"))
        paid = money(job.get("paid_amount"))
        balance = amount - paid

        rows_html += f"""
        <tr>
            <td><strong>{job.get("title") or ""}</strong></td>
            <td>{job.get("client_name") or "-"}</td>
            <td>{job.get("address") or "-"}</td>
            <td>{job.get("status") or "-"}</td>
            <td>{job.get("billing_status") or "Unbilled"}</td>
            <td>${amount:,.2f}</td>
            <td>${paid:,.2f}</td>
            <td>${balance:,.2f}</td>
            <td>
                <form method="post" action="/jobs/{job.get("id")}/invoice" style="display:inline;">
                    <button type="submit">Invoice</button>
                </form>
                <form method="post" action="/jobs/{job.get("id")}/mark-paid" style="display:inline;">
                    <button type="submit">Paid</button>
                </form>
            </td>
        </tr>
        """

    if not rows_html:
        rows_html = """
        <tr>
            <td colspan="9">No jobs found.</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Jobs • HG Pool Ops</title>
        <link rel="stylesheet" href="/static/style.css">
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f5f7fb;
                margin: 0;
            }}
            .topbar {{
                background: #0b4aa2;
                color: white;
                padding: 14px 28px;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }}
            .topbar a {{
                color: white;
                text-decoration: none;
                margin-left: 16px;
                font-weight: bold;
            }}
            .container {{
                max-width: 1200px;
                margin: 30px auto;
                padding: 0 20px;
            }}
            .card {{
                background: white;
                border-radius: 12px;
                padding: 22px;
                box-shadow: 0 4px 16px rgba(0,0,0,.08);
            }}
            .page-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 22px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            th, td {{
                text-align: left;
                padding: 12px;
                border-bottom: 1px solid #e5e7eb;
            }}