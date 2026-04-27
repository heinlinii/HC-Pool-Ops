import os
from decimal import Decimal

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, text

app = FastAPI(title="HC Pool Ops")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "poolops-secret-key-change-later"),
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def get_db_url():
    url = os.getenv("DATABASE_URL", "sqlite:///./poolops.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


engine = create_engine(get_db_url(), pool_pre_ping=True)


def db_execute(sql, params=None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {})


def db_all(sql, params=None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {}).mappings().all()


def db_one(sql, params=None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {}).mappings().first()


def current_user(request: Request):
    return request.session.get("user")


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def init_db():
    db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'admin'
        )
    """)

    db_execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        )
    """)

    db_execute("""
        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY,
            client_id INTEGER,
            name TEXT NOT NULL,
            address TEXT DEFAULT '',
            city TEXT DEFAULT '',
            state TEXT DEFAULT '',
            zip_code TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        )
    """)

    db_execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            role TEXT DEFAULT '',
            active TEXT DEFAULT 'yes'
        )
    """)

    db_execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY,
            property_id INTEGER,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'Scheduled',
            scheduled_date TEXT DEFAULT '',
            assigned_crew TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            billing_status TEXT DEFAULT 'Not Invoiced',
            invoice_number TEXT DEFAULT '',
            invoice_total TEXT DEFAULT '0',
            paid_status TEXT DEFAULT 'Unpaid'
        )
    """)

    existing = db_one("SELECT id FROM users WHERE username = :username", {"username": "admin"})
    if not existing:
        db_execute(
    "INSERT INTO users (username, password, role) VALUES (:username, :password, :role)",
    {
        "username": "admin",
        "password": "admin",
        "role": "admin",
    },
)

    prop = db_one("SELECT id FROM properties LIMIT 1")
    if not prop:
        db_execute(
            "INSERT INTO properties (name, address, city, state, zip_code) VALUES (:name, :address, :city, :state, :zip)",
            {
                "name": "Backyard Pool",
                "address": "",
                "city": "Evansville",
                "state": "IN",
                "zip": "",
            },
        )


init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


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
        {"error": None},
    )


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = db_one(
        "SELECT * FROM users WHERE username = :username AND password = :password",
        {"username": username, "password": password},
    )

    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
        )

    request.session["user"] = {
        "id": user["id"],
        "name": user["name"],
        "username": user["username"],
        "role": user["role"],
    }
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(require_user)):
    stats = {
        "clients": db_one("SELECT COUNT(*) AS count FROM clients")["count"],
        "properties": db_one("SELECT COUNT(*) AS count FROM properties")["count"],
        "jobs": db_one("SELECT COUNT(*) AS count FROM jobs")["count"],
        "employees": db_one("SELECT COUNT(*) AS count FROM employees")["count"],
    }

    jobs = db_all("""
        SELECT jobs.*, properties.name AS property_name
        FROM jobs
        LEFT JOIN properties ON properties.id = jobs.property_id
        ORDER BY jobs.id DESC
        LIMIT 10
    """)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "stats": stats,
            "jobs": jobs,
        },
    )


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, user=Depends(require_user)):
    users = db_all("SELECT * FROM users ORDER BY id DESC")
    return templates.TemplateResponse(
        request,
        "users.html",
        {"user": user, "users": users},
    )


@app.post("/users")
def add_user(
    request: Request,
    name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
    user=Depends(require_user),
):
    db_execute(
    "INSERT INTO users (username, password, role) VALUES (:username, :password, :role)",
    {
        "username": username,
        "password": password,
        "role": role,
    },
)
   
@app.post("/users/delete")
def delete_user(id: int = Form(...), user=Depends(require_user)):
    db_execute("DELETE FROM users WHERE id = :id", {"id": id})
    return RedirectResponse("/users", status_code=303)


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request, user=Depends(require_user)):
    clients = db_all("SELECT * FROM clients ORDER BY id DESC")
    return templates.TemplateResponse(
        request,
        "clients.html",
        {"user": user, "clients": clients},
    )


@app.post("/clients")
def add_client(
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    notes: str = Form(""),
    user=Depends(require_user),
):
    db_execute(
        "INSERT INTO clients (name, phone, email, notes) VALUES (:name, :phone, :email, :notes)",
        {"name": name, "phone": phone, "email": email, "notes": notes},
    )
    return RedirectResponse("/clients", status_code=303)


@app.post("/clients/delete")
def delete_client(id: int = Form(...), user=Depends(require_user)):
    db_execute("DELETE FROM clients WHERE id = :id", {"id": id})
    return RedirectResponse("/clients", status_code=303)


@app.get("/properties", response_class=HTMLResponse)
def properties_page(request: Request, user=Depends(require_user)):
    properties = db_all("""
        SELECT properties.*, clients.name AS client_name
        FROM properties
        LEFT JOIN clients ON clients.id = properties.client_id
        ORDER BY properties.id DESC
    """)
    clients = db_all("SELECT * FROM clients ORDER BY name")
    return templates.TemplateResponse(
        request,
        "properties.html",
        {"user": user, "properties": properties, "clients": clients},
    )


@app.post("/properties")
def add_property(
    client_id: int = Form(None),
    name: str = Form(...),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    notes: str = Form(""),
    user=Depends(require_user),
):
    db_execute(
        """
        INSERT INTO properties (client_id, name, address, city, state, zip_code, notes)
        VALUES (:client_id, :name, :address, :city, :state, :zip_code, :notes)
        """,
        {
            "client_id": client_id,
            "name": name,
            "address": address,
            "city": city,
            "state": state,
            "zip_code": zip_code,
            "notes": notes,
        },
    )
    return RedirectResponse("/properties", status_code=303)


@app.post("/properties/delete")
def delete_property(id: int = Form(...), user=Depends(require_user)):
    db_execute("DELETE FROM properties WHERE id = :id", {"id": id})
    return RedirectResponse("/properties", status_code=303)


@app.get("/employees", response_class=HTMLResponse)
def employees_page(request: Request, user=Depends(require_user)):
    employees = db_all("SELECT * FROM employees ORDER BY id DESC")
    return templates.TemplateResponse(
        request,
        "employees.html",
        {"user": user, "employees": employees},
    )


@app.post("/employees")
def add_employee(
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    role: str = Form(""),
    active: str = Form("yes"),
    user=Depends(require_user),
):
    db_execute(
        "INSERT INTO employees (name, phone, email, role, active) VALUES (:name, :phone, :email, :role, :active)",
        {"name": name, "phone": phone, "email": email, "role": role, "active": active},
    )
    return RedirectResponse("/employees", status_code=303)


@app.post("/employees/delete")
def delete_employee(id: int = Form(...), user=Depends(require_user)):
    db_execute("DELETE FROM employees WHERE id = :id", {"id": id})
    return RedirectResponse("/employees", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, user=Depends(require_user)):
    jobs = db_all("""
        SELECT jobs.*, properties.name AS property_name
        FROM jobs
        LEFT JOIN properties ON properties.id = jobs.property_id
        ORDER BY jobs.id DESC
    """)
    properties = db_all("SELECT * FROM properties ORDER BY name")
    employees = db_all("SELECT * FROM employees WHERE active = 'yes' ORDER BY name")

    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "user": user,
            "jobs": jobs,
            "properties": properties,
            "employees": employees,
        },
    )


@app.get("/jobs/new")
def jobs_new():
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs")
def add_job(
    property_id: int = Form(...),
    title: str = Form(...),
    status: str = Form("Scheduled"),
    scheduled_date: str = Form(""),
    assigned_crew: str = Form(""),
    notes: str = Form(""),
    user=Depends(require_user),
):
    db_execute(
        """
        INSERT INTO jobs (property_id, title, status, scheduled_date, assigned_crew, notes)
        VALUES (:property_id, :title, :status, :scheduled_date, :assigned_crew, :notes)
        """,
        {
            "property_id": property_id,
            "title": title,
            "status": status,
            "scheduled_date": scheduled_date,
            "assigned_crew": assigned_crew,
            "notes": notes,
        },
    )
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/delete")
def delete_job(id: int = Form(...), user=Depends(require_user)):
    db_execute("DELETE FROM jobs WHERE id = :id", {"id": id})
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/status")
def update_job_status(
    id: int = Form(...),
    status: str = Form(...),
    user=Depends(require_user),
):
    db_execute("UPDATE jobs SET status = :status WHERE id = :id", {"id": id, "status": status})
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/billing")
def update_job_billing(
    id: int = Form(...),
    billing_status: str = Form("Not Invoiced"),
    invoice_total: str = Form("0"),
    paid_status: str = Form("Unpaid"),
    user=Depends(require_user),
):
    job = db_one("SELECT * FROM jobs WHERE id = :id", {"id": id})
    if not job:
        return RedirectResponse("/jobs", status_code=303)

    invoice_number = job["invoice_number"] or f"INV-{id:04d}"

    db_execute(
        """
        UPDATE jobs
        SET billing_status = :billing_status,
            invoice_total = :invoice_total,
            paid_status = :paid_status,
            invoice_number = :invoice_number
        WHERE id = :id
        """,
        {
            "id": id,
            "billing_status": billing_status,
            "invoice_total": invoice_total,
            "paid_status": paid_status,
            "invoice_number": invoice_number,
        },
    )
    return RedirectResponse("/jobs", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: int, request: Request, user=Depends(require_user)):
    job = db_one("""
        SELECT jobs.*, properties.name AS property_name
        FROM jobs
        LEFT JOIN properties ON properties.id = jobs.property_id
        WHERE jobs.id = :id
    """, {"id": job_id})

    if not job:
        return RedirectResponse("/jobs", status_code=303)

    return templates.TemplateResponse(
        request,
        "service_stop_detail.html",
        {"user": user, "job": job},
    )


@app.get("/jobs/{job_id}/invoice", response_class=HTMLResponse)
def job_invoice(job_id: int, request: Request, user=Depends(require_user)):
    job = db_one("""
        SELECT jobs.*, properties.name AS property_name, properties.address AS property_address
        FROM jobs
        LEFT JOIN properties ON properties.id = jobs.property_id
        WHERE jobs.id = :id
    """, {"id": job_id})

    if not job:
        return RedirectResponse("/jobs", status_code=303)

    if not job["invoice_number"]:
        invoice_number = f"INV-{job_id:04d}"
        db_execute(
            "UPDATE jobs SET invoice_number = :invoice_number, billing_status = :billing_status WHERE id = :id",
            {"invoice_number": invoice_number, "billing_status": "Invoiced", "id": job_id},
        )
        job = dict(job)
        job["invoice_number"] = invoice_number
        job["billing_status"] = "Invoiced"

    return templates.TemplateResponse(
        request,
        "invoice.html",
        {"user": user, "job": job},
    )


@app.get("/invoice/{invoice_number}", response_class=HTMLResponse)
def invoice_by_number(invoice_number: str, request: Request, user=Depends(require_user)):
    job = db_one("""
        SELECT jobs.*, properties.name AS property_name, properties.address AS property_address
        FROM jobs
        LEFT JOIN properties ON properties.id = jobs.property_id
        WHERE jobs.invoice_number = :invoice_number
    """, {"invoice_number": invoice_number})

    if not job:
        return {"detail": "Not Found"}

    return templates.TemplateResponse(
        request,
        "invoice.html",
        {"user": user, "job": job},
    )


@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request, user=Depends(require_user)):
    jobs = db_all("""
        SELECT jobs.*, properties.name AS property_name
        FROM jobs
        LEFT JOIN properties ON properties.id = jobs.property_id
        WHERE jobs.status != 'Completed'
        ORDER BY jobs.scheduled_date ASC, jobs.id DESC
    """)
    properties = db_all("SELECT * FROM properties ORDER BY name")
    employees = db_all("SELECT * FROM employees WHERE active = 'yes' ORDER BY name")

    return templates.TemplateResponse(
        request,
        "schedule.html",
        {
            "user": user,
            "jobs": jobs,
            "properties": properties,
            "employees": employees,
        },
    )


@app.post("/schedule")
def schedule_job(
    property_id: int = Form(...),
    title: str = Form(...),
    scheduled_date: str = Form(""),
    assigned_crew: str = Form(""),
    notes: str = Form(""),
    user=Depends(require_user),
):
    db_execute(
        """
        INSERT INTO jobs (property_id, title, status, scheduled_date, assigned_crew, notes)
        VALUES (:property_id, :title, 'Scheduled', :scheduled_date, :assigned_crew, :notes)
        """,
        {
            "property_id": property_id,
            "title": title,
            "scheduled_date": scheduled_date,
            "assigned_crew": assigned_crew,
            "notes": notes,
        },
    )
    return RedirectResponse("/schedule", status_code=303)


@app.post("/schedule/delete")
def schedule_delete(id: int = Form(...), user=Depends(require_user)):
    db_execute("DELETE FROM jobs WHERE id = :id", {"id": id})
    return RedirectResponse("/schedule", status_code=303)


@app.post("/schedule/book")
def schedule_book(
    job_id: int = Form(...),
    scheduled_date: str = Form(""),
    assigned_crew: str = Form(""),
    user=Depends(require_user),
):
    db_execute(
        """
        UPDATE jobs
        SET scheduled_date = :scheduled_date,
            assigned_crew = :assigned_crew,
            status = 'Scheduled'
        WHERE id = :job_id
        """,
        {
            "job_id": job_id,
            "scheduled_date": scheduled_date,
            "assigned_crew": assigned_crew,
        },
    )
    return RedirectResponse("/schedule", status_code=303)


@app.get("/my-day", response_class=HTMLResponse)
def my_day(request: Request, user=Depends(require_user)):
    jobs = db_all("""
        SELECT jobs.*, properties.name AS property_name
        FROM jobs
        LEFT JOIN properties ON properties.id = jobs.property_id
        WHERE jobs.status != 'Completed'
        ORDER BY jobs.scheduled_date ASC, jobs.id DESC
    """)

    return templates.TemplateResponse(
        request,
        "my_day.html",
        {"user": user, "jobs": jobs},
    )


@app.post("/clock/in")
def clock_in(user=Depends(require_user)):
    return RedirectResponse("/my-day", status_code=303)


@app.post("/clock/out")
def clock_out(user=Depends(require_user)):
    return RedirectResponse("/my-day", status_code=303)


@app.get("/client-portal", response_class=HTMLResponse)
def client_portal(request: Request):
    jobs = db_all("""
        SELECT jobs.*, properties.name AS property_name
        FROM jobs
        LEFT JOIN properties ON properties.id = jobs.property_id
        ORDER BY jobs.id DESC
        LIMIT 20
    """)

    return templates.TemplateResponse(
        request,
        "client_portal.html",
        {"jobs": jobs},
    )


@app.get("/redo")
def redo():
    return RedirectResponse("/dashboard", status_code=303)