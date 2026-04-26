import os
from decimal import Decimal
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, text
app = FastAPI(title="HC Pool Ops")
@app.get("/health")
def health():
    return {"status": "ok"}
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
    migrations = [
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS amount NUMERIC DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS paid_amount NUMERIC DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS billing_status TEXT DEFAULT 'Unbilled'",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    ]

    for sql in migrations:
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
 return templates.TemplateResponse(
    request,
    "login.html",
    {
        "error": None
    }
)
@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = one("""
        SELECT id, username, name, role
        FROM users
        WHERE username = :username AND password = :password
    """, {
        "username": username,
        "password": password,
    })

    request.session["user"] = user


    if not user:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid username or password"
            }
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

    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "user": user,
        "jobs": jobs,
    })


@app.get("/jobs/new", response_class=HTMLResponse)
def new_job_page(request: Request, user=Depends(require_login)):
    clients = rows("SELECT * FROM clients ORDER BY name")
    properties = rows("SELECT * FROM properties ORDER BY name")

    return templates.TemplateResponse("job_form.html", {
        "request": request,
        "user": user,
        "clients": clients,
        "properties": properties,
    })


@app.post("/jobs/new")
def create_job(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    client_id: int = Form(None),
    property_id: int = Form(None),
    status: str = Form("Scheduled"),
    scheduled_date: str = Form(None),
    crew: str = Form(""),
    amount: float = Form(0),
    user=Depends(require_login),
):
    run("""
        INSERT INTO jobs
        (title, description, client_id, property_id, status, scheduled_date, crew, amount, paid_amount, billing_status)
        VALUES
        (:title, :description, :client_id, :property_id, :status, :scheduled_date, :crew, :amount, 0, 'Unbilled')
    """, {
        "title": title,
        "description": description,
        "client_id": client_id,
        "property_id": property_id,
        "status": status,
        "scheduled_date": scheduled_date or None,
        "crew": crew,
        "amount": amount,
    })

    return RedirectResponse("/jobs", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: int, request: Request, user=Depends(require_login)):
    job = one("""
        SELECT
            jobs.*,
            clients.name AS client_name,
            properties.name AS property_name,
            properties.address AS address
        FROM jobs
        LEFT JOIN clients ON clients.id = jobs.client_id
        LEFT JOIN properties ON properties.id = jobs.property_id
        WHERE jobs.id = :job_id
    """, {"job_id": job_id})

    if not job:
        return RedirectResponse("/jobs", status_code=303)

    invoice = one("""
        SELECT *
        FROM invoices
        WHERE job_id = :job_id
        ORDER BY id DESC
        LIMIT 1
    """, {"job_id": job_id})

    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "user": user,
        "job": job,
        "invoice": invoice,
    })


@app.post("/jobs/{job_id}/start")
def start_job(job_id: int, request: Request, user=Depends(require_login)):
    run("""
        UPDATE jobs
        SET status = 'In Progress',
            started_at = CURRENT_TIMESTAMP
        WHERE id = :job_id
    """, {"job_id": job_id})

    return RedirectResponse("/my-day", status_code=303)


@app.post("/jobs/{job_id}/complete")
def complete_job(job_id: int, request: Request, user=Depends(require_login)):
    run("""
        UPDATE jobs
        SET status = 'Complete',
            completed_at = CURRENT_TIMESTAMP
        WHERE id = :job_id
    """, {"job_id": job_id})

    return RedirectResponse("/my-day", status_code=303)


@app.post("/jobs/{job_id}/invoice")
def create_invoice(job_id: int, request: Request, user=Depends(require_login)):
    job = one("SELECT * FROM jobs WHERE id = :job_id", {"job_id": job_id})

    if not job:
        return RedirectResponse("/jobs", status_code=303)

    amount = money(job["amount"])
    paid = money(job["paid_amount"])
    invoice_status = "Paid" if amount > 0 and paid >= amount else "Unpaid"

    existing = one("""
        SELECT id
        FROM invoices
        WHERE job_id = :job_id
        ORDER BY id DESC
        LIMIT 1
    """, {"job_id": job_id})

    if existing:
        run("""
            UPDATE invoices
            SET total = :total,
                paid_amount = :paid_amount,
                status = :status
            WHERE id = :invoice_id
        """, {
            "invoice_id": existing["id"],
            "total": amount,
            "paid_amount": paid,
            "status": invoice_status,
        })
    else:
        run("""
            INSERT INTO invoices (job_id, client_id, total, paid_amount, status)
            VALUES (:job_id, :client_id, :total, :paid_amount, :status)
        """, {
            "job_id": job_id,
            "client_id": job["client_id"],
            "total": amount,
            "paid_amount": paid,
            "status": invoice_status,
        })

    run("""
        UPDATE jobs
        SET billing_status = :billing_status
        WHERE id = :job_id
    """, {
        "job_id": job_id,
        "billing_status": "Paid" if invoice_status == "Paid" else "Invoiced",
    })

    return RedirectResponse(f"/invoice/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/mark-paid")
def mark_job_paid(job_id: int, request: Request, user=Depends(require_login)):
    job = one("SELECT * FROM jobs WHERE id = :job_id", {"job_id": job_id})

    if not job:
        return RedirectResponse("/jobs", status_code=303)

    amount = money(job["amount"])

    run("""
        UPDATE jobs
        SET paid_amount = :amount,
            billing_status = 'Paid'
        WHERE id = :job_id
    """, {
        "amount": amount,
        "job_id": job_id,
    })

    invoice = one("""
        SELECT id
        FROM invoices
        WHERE job_id = :job_id
        ORDER BY id DESC
        LIMIT 1
    """, {"job_id": job_id})

    if invoice:
        run("""
            UPDATE invoices
            SET total = :amount,
                paid_amount = :amount,
                status = 'Paid',
                paid_at = CURRENT_TIMESTAMP
            WHERE id = :invoice_id
        """, {
            "amount": amount,
            "invoice_id": invoice["id"],
        })
    else:
        run("""
            INSERT INTO invoices (job_id, client_id, total, paid_amount, status, paid_at)
            VALUES (:job_id, :client_id, :total, :paid_amount, 'Paid', CURRENT_TIMESTAMP)
        """, {
            "job_id": job_id,
            "client_id": job["client_id"],
            "total": amount,
            "paid_amount": amount,
        })

    return RedirectResponse(f"/invoice/{job_id}", status_code=303)


@app.get("/invoice/{job_id}", response_class=HTMLResponse)
def view_invoice(job_id: int, request: Request, user=Depends(require_login)):
    job = one("""
        SELECT
            jobs.*,
            clients.name AS client_name,
            clients.phone AS client_phone,
            clients.email AS client_email,
            properties.name AS property_name,
            properties.address AS address,
            properties.city AS city,
            properties.state AS state,
            properties.zip AS zip
        FROM jobs
        LEFT JOIN clients ON clients.id = jobs.client_id
        LEFT JOIN properties ON properties.id = jobs.property_id
        WHERE jobs.id = :job_id
    """, {"job_id": job_id})

    if not job:
        return RedirectResponse("/jobs", status_code=303)

    invoice = one("""
        SELECT *
        FROM invoices
        WHERE job_id = :job_id
        ORDER BY id DESC
        LIMIT 1
    """, {"job_id": job_id})

    if not invoice:
        amount = money(job["amount"])
        paid = money(job["paid_amount"])
        status = "Paid" if amount > 0 and paid >= amount else "Unpaid"

        run("""
            INSERT INTO invoices (job_id, client_id, total, paid_amount, status)
            VALUES (:job_id, :client_id, :total, :paid_amount, :status)
        """, {
            "job_id": job_id,
            "client_id": job["client_id"],
            "total": amount,
            "paid_amount": paid,
            "status": status,
        })

        invoice = one("""
            SELECT *
            FROM invoices
            WHERE job_id = :job_id
            ORDER BY id DESC
            LIMIT 1
        """, {"job_id": job_id})

    amount = money(job["amount"])
    paid = money(job["paid_amount"])
    balance = amount - paid

    return templates.TemplateResponse("invoice.html", {
        "request": request,
        "user": user,
        "job": job,
        "invoice": invoice,
        "amount": amount,
        "paid": paid,
        "balance": balance,
    })


@app.get("/billing", response_class=HTMLResponse)
def billing_page(request: Request, user=Depends(require_login)):
    invoices = rows("""
        SELECT
            invoices.*,
            jobs.title AS job_title,
            jobs.amount AS job_amount,
            jobs.paid_amount AS job_paid_amount,
            jobs.billing_status AS billing_status,
            clients.name AS client_name
        FROM invoices
        LEFT JOIN jobs ON jobs.id = invoices.job_id
        LEFT JOIN clients ON clients.id = invoices.client_id
        ORDER BY invoices.id DESC
    """)

    return templates.TemplateResponse("billing.html", {
        "request": request,
        "user": user,
        "invoices": invoices,
    })


@app.get("/my-day", response_class=HTMLResponse)
def my_day(request: Request, user=Depends(require_login)):
    jobs = rows("""
        SELECT
            jobs.*,
            properties.name AS property_name,
            properties.address AS address,
            clients.name AS client_name
        FROM jobs
        LEFT JOIN properties ON properties.id = jobs.property_id
        LEFT JOIN clients ON clients.id = jobs.client_id
        WHERE jobs.status != 'Complete'
        ORDER BY jobs.scheduled_date ASC NULLS LAST, jobs.id ASC
    """)

    active_clock = one("""
        SELECT *
        FROM time_clock
        WHERE username = :username AND clock_out IS NULL
        ORDER BY id DESC
        LIMIT 1
    """, {"username": user["username"]})

    return templates.TemplateResponse("my_day.html", {
        "request": request,
        "user": user,
        "jobs": jobs,
        "active_clock": active_clock,
    })


@app.post("/clock-in")
def clock_in(request: Request, user=Depends(require_login)):
    active = one("""
        SELECT id
        FROM time_clock
        WHERE username = :username AND clock_out IS NULL
        LIMIT 1
    """, {"username": user["username"]})

    if not active:
        run("""
            INSERT INTO time_clock (user_id, username, clock_in)
            VALUES (:user_id, :username, CURRENT_TIMESTAMP)
        """, {
            "user_id": user["id"],
            "username": user["username"],
        })

    return RedirectResponse("/my-day", status_code=303)


@app.post("/clock-out")
def clock_out(request: Request, user=Depends(require_login)):
    active = one("""
        SELECT id
        FROM time_clock
        WHERE username = :username AND clock_out IS NULL
        ORDER BY id DESC
        LIMIT 1
    """, {"username": user["username"]})

    if active:
        run("""
            UPDATE time_clock
            SET clock_out = CURRENT_TIMESTAMP
            WHERE id = :id
        """, {"id": active["id"]})

    return RedirectResponse("/my-day", status_code=303)


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request, user=Depends(require_login)):
    clients = rows("SELECT * FROM clients ORDER BY name")

    return templates.TemplateResponse("clients.html", {
        "request": request,
        "user": user,
        "clients": clients,
    })


@app.get("/properties", response_class=HTMLResponse)
def properties_page(request: Request, user=Depends(require_login)):
    properties = rows("""
        SELECT
            properties.*,
            clients.name AS client_name
        FROM properties
        LEFT JOIN clients ON clients.id = properties.client_id
        ORDER BY properties.name
    """)

    return templates.TemplateResponse("properties.html", {
        "request": request,
        "user": user,
        "properties": properties,
    })


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, user=Depends(require_login)):
    users = rows("SELECT id, username, name, role FROM users ORDER BY id")

    return templates.TemplateResponse("users.html", {
        "request": request,
        "user": user,
        "users": users,
    })


@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request, user=Depends(require_login)):
    jobs = rows("""
        SELECT
            jobs.*,
            properties.name AS property_name,
            properties.address AS address,
            clients.name AS client_name
        FROM jobs
        LEFT JOIN properties ON properties.id = jobs.property_id
        LEFT JOIN clients ON clients.id = jobs.client_id
        ORDER BY jobs.scheduled_date ASC NULLS LAST, jobs.id ASC
    """)

    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "user": user,
        "jobs": jobs,
    })

@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "HG Pool Ops",
        "version": "full-app-replacement-invoice-1"
    }