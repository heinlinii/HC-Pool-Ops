from datetime import datetime, date
import csv
import io

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware


app = FastAPI(title="PoolOps Pro")
app.add_middleware(SessionMiddleware, secret_key="poolops-secret-key")

# Logo lives here:
# app/static/logo.png
app.mount("/static", StaticFiles(directory="app/static"), name="static")


USERS = {
    "mike": {"password": "5500", "role": "admin", "name": "Mike"},
    "randy": {"password": "0318", "role": "crew", "name": "Randy"},
    "traylor": {"password": "8899", "role": "client", "name": "Traylor"},
}


CLIENTS = [
    {"id": 1, "name": "Traylor", "phone": "812-449-6198", "email": "", "notes": "Client portal test account"},
]

PROPERTIES = [
    {"id": 1, "client": "Traylor", "name": "Traylor Residence", "address": "Evansville, IN", "notes": "Main pool property"},
]

EMPLOYEES = [
    {"id": 1, "name": "Mike", "role": "Admin", "phone": ""},
    {"id": 2, "name": "Randy", "role": "Crew", "phone": ""},
]

JOBS = [
    {
        "id": 1,
        "client": "Traylor",
        "property": "Traylor Residence",
        "title": "Pool Service",
        "job_type": "Service",
        "date": date.today().isoformat(),
        "status": "Scheduled",
        "billing_status": "Unbilled",
        "crew": "Randy",
        "amount": 450.00,
        "notes": "Clean pool, check equipment, inspect cover.",
    },
    {
        "id": 2,
        "client": "Sample Client",
        "property": "Sample Property",
        "title": "Automatic Cover Repair",
        "job_type": "Repair",
        "date": date.today().isoformat(),
        "status": "Scheduled",
        "billing_status": "Ready to Bill",
        "crew": "Randy",
        "amount": 1250.00,
        "notes": "Inspect tracks, pulleys, motor, and cover box.",
    },
]

TIME_CLOCK = {
    "mike": {"clocked_in": False, "last_action": ""},
    "randy": {"clocked_in": False, "last_action": ""},
    "traylor": {"clocked_in": False, "last_action": ""},
}


def next_id(items):
    if not items:
        return 1
    return max(item["id"] for item in items) + 1


def get_user(request: Request):
    user = request.session.get("user")
    if isinstance(user, dict):
        return user
    request.session.clear()
    return None


def require_user(request: Request):
    return get_user(request)


def money(value):
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "$0.00"


def css():
    return """
    <style>
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: Arial, Helvetica, sans-serif;
            background: #07111f;
            color: #f8fafc;
        }
        a { color: inherit; text-decoration: none; }
        .shell {
            max-width: 1250px;
            margin: 0 auto;
            padding: 24px;
        }
        .topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 18px;
            margin-bottom: 22px;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 14px;
        }
        .logo {
            width: 86px;
            height: 86px;
            object-fit: contain;
            background: white;
            border-radius: 16px;
            padding: 6px;
        }
        .brand-text h1 {
            margin: 0;
            font-size: 30px;
            letter-spacing: -0.04em;
        }
        .brand-text p {
            margin: 4px 0 0;
            color: #94a3b8;
            font-size: 14px;
        }
        .nav {
            display: flex;
            flex-wrap: wrap;
            justify-content: flex-end;
            gap: 8px;
        }
        .nav a, .btn {
            display: inline-block;
            padding: 10px 13px;
            border-radius: 12px;
            background: #132238;
            color: #e2e8f0;
            border: 1px solid #243449;
            font-weight: 800;
            cursor: pointer;
            font-size: 14px;
        }
        .nav a:hover, .btn:hover { background: #1e3a5f; }
        .hero {
            background: linear-gradient(135deg, #0f2742, #111827);
            border: 1px solid #243449;
            border-radius: 22px;
            padding: 26px;
            margin-bottom: 20px;
            box-shadow: 0 18px 60px rgba(0,0,0,0.35);
        }
        .hero h2 {
            margin: 0 0 8px;
            font-size: 34px;
        }
        .hero p {
            margin: 0;
            color: #cbd5e1;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 16px;
        }
        .grid-2 {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
        }
        .card {
            background: #0f172a;
            border: 1px solid #243449;
            border-radius: 20px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 12px 40px rgba(0,0,0,0.22);
        }
        .card h3 { margin: 0 0 10px; }
        .metric {
            font-size: 30px;
            font-weight: 900;
            color: #38bdf8;
            margin-top: 8px;
        }
        .muted { color: #94a3b8; }
        table {
            width: 100%;
            border-collapse: collapse;
            background: #0f172a;
            border: 1px solid #243449;
            border-radius: 16px;
            overflow: hidden;
        }
        th, td {
            padding: 12px 13px;
            border-bottom: 1px solid #243449;
            text-align: left;
            vertical-align: top;
        }
        th {
            background: #132238;
            color: #cbd5e1;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: .04em;
        }
        tr:last-child td { border-bottom: none; }
        input, select, textarea {
            width: 100%;
            padding: 12px 13px;
            border-radius: 12px;
            border: 1px solid #334155;
            background: #020617;
            color: #f8fafc;
            margin-bottom: 10px;
            font-size: 15px;
        }
        textarea { min-height: 100px; }
        button { border: none; }
        .form-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
        }
        .status {
            display: inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 900;
            background: #1e293b;
            color: #e2e8f0;
        }
        .ready { background: #064e3b; color: #a7f3d0; }
        .unbilled { background: #78350f; color: #fde68a; }
        .paid { background: #1e3a8a; color: #bfdbfe; }
        .danger { background: #7f1d1d; }
        .actions {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
        }
        .login-wrap {
            min-height: 100vh;
            display: grid;
            place-items: center;
            padding: 24px;
        }
        .login-card {
            width: 100%;
            max-width: 440px;
            background: #0f172a;
            border: 1px solid #243449;
            border-radius: 24px;
            padding: 30px;
            box-shadow: 0 22px 80px rgba(0,0,0,0.45);
        }
        .login-logo {
            width: 180px;
            max-width: 100%;
            display: block;
            margin: 0 auto 18px;
            background: white;
            border-radius: 18px;
            padding: 8px;
        }
        .error {
            background: #7f1d1d;
            color: #fee2e2;
            padding: 12px;
            border-radius: 12px;
            margin-bottom: 14px;
        }
        @media (max-width: 850px) {
            .topbar { flex-direction: column; align-items: flex-start; }
            .grid, .grid-2, .form-grid { grid-template-columns: 1fr; }
            .nav { justify-content: flex-start; }
            .shell { padding: 16px; }
            table { font-size: 13px; }
        }
    </style>
    """


def nav(user):
    return f"""
    <div class="topbar">
        <div class="brand">
            <img src="/static/logo.png" class="logo" onerror="this.style.display='none'">
            <div class="brand-text">
                <h1>PoolOps Pro</h1>
                <p>Heinlin Concrete • Logged in as {user["name"]} ({user["role"]})</p>
            </div>
        </div>
        <div class="nav">
            <a href="/dashboard">Dashboard</a>
            <a href="/jobs">Jobs</a>
            <a href="/add-job">Add Job</a>
            <a href="/clients">Clients</a>
            <a href="/properties">Properties</a>
            <a href="/employees">Employees</a>
            <a href="/schedule">Schedule</a>
            <a href="/my-day">My Day</a>
            <a href="/billing">Billing</a>
            <a href="/quickbooks-export">QB CSV</a>
            <a href="/logout">Logout</a>
        </div>
    </div>
    """


def page(title, body, user):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title} • PoolOps Pro</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {css()}
    </head>
    <body>
        <div class="shell">
            {nav(user)}
            {body}
        </div>
    </body>
    </html>
    """


def login_page_html(error=""):
    error_html = f'<div class="error">{error}</div>' if error else ""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login • PoolOps Pro</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {css()}
    </head>
    <body>
        <div class="login-wrap">
            <div class="login-card">
                <img src="/static/logo.png" class="login-logo" onerror="this.style.display='none'">
                <h1>PoolOps Pro</h1>
                <p class="muted">Heinlin Concrete command center.</p>
                {error_html}
                <form method="post" action="/login">
                    <input name="username" placeholder="Username" required>
                    <input name="password" type="password" placeholder="Password" required>
                    <button class="btn" type="submit">Login</button>
                </form>
                <div class="card" style="margin-top:18px;">
                    <h3>Logins</h3>
                    <p class="muted">mike / 5500 = admin</p>
                    <p class="muted">randy / 0318 = crew</p>
                    <p class="muted">traylor / 8899 = client</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/health")
def health():
    return {"status": "ok", "app": "PoolOps Pro", "time": datetime.now().isoformat()}


@app.get("/")
def home():
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_get():
    return login_page_html()


@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    username_clean = username.strip().lower()
    password_clean = password.strip()
    found = USERS.get(username_clean)

    if not found or found["password"] != password_clean:
        return HTMLResponse(login_page_html("Invalid username or password."), status_code=401)

    request.session.clear()
    request.session["user"] = {
        "username": username_clean,
        "name": found["name"],
        "role": found["role"],
    }
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    total = sum(j["amount"] for j in JOBS)
    ready = sum(j["amount"] for j in JOBS if j["billing_status"] == "Ready to Bill")
    unbilled = sum(j["amount"] for j in JOBS if j["billing_status"] == "Unbilled")
    completed = len([j for j in JOBS if j["status"] == "Completed"])

    body = f"""
    <div class="hero">
        <h2>Dashboard</h2>
        <p>Live overview for jobs, crew, billing, schedule, and clients.</p>
    </div>
    <div class="grid">
        <div class="card"><h3>Total Jobs</h3><div class="metric">{len(JOBS)}</div><p class="muted">Jobs in the system.</p></div>
        <div class="card"><h3>Total Work</h3><div class="metric">{money(total)}</div><p class="muted">Current work value.</p></div>
        <div class="card"><h3>Ready to Bill</h3><div class="metric">{money(ready)}</div><p class="muted">Unbilled: {money(unbilled)}</p></div>
        <div class="card"><h3>Clients</h3><div class="metric">{len(CLIENTS)}</div></div>
        <div class="card"><h3>Properties</h3><div class="metric">{len(PROPERTIES)}</div></div>
        <div class="card"><h3>Completed Jobs</h3><div class="metric">{completed}</div></div>
    </div>
    """
    return page("Dashboard", body, user)


@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    rows = ""
    for j in JOBS:
        billing_class = "ready" if j["billing_status"] == "Ready to Bill" else "paid" if j["billing_status"] == "Paid" else "unbilled"
        rows += f"""
        <tr>
            <td>{j["date"]}</td>
            <td>{j["client"]}</td>
            <td>{j["property"]}</td>
            <td>{j["title"]}<br><span class="muted">{j["job_type"]}</span></td>
            <td><span class="status">{j["status"]}</span></td>
            <td>{j["crew"]}</td>
            <td><span class="status {billing_class}">{j["billing_status"]}</span></td>
            <td>{money(j["amount"])}</td>
            <td>
                <a class="btn" href="/edit-job/{j["id"]}">Edit</a>
                <a class="btn danger" href="/delete-job/{j["id"]}">Delete</a>
            </td>
        </tr>
        """

    body = f"""
    <div class="hero">
        <h2>Jobs</h2>
        <p>Manage job status, billing, crew assignment, and notes.</p>
    </div>
    <div class="actions"><a class="btn" href="/add-job">Add New Job</a></div><br>
    <table>
        <tr>
            <th>Date</th><th>Client</th><th>Property</th><th>Job</th><th>Status</th>
            <th>Crew</th><th>Billing</th><th>Amount</th><th>Actions</th>
        </tr>
        {rows}
    </table>
    """
    return page("Jobs", body, user)


def job_form(action, button_text, j=None):
    j = j or {
        "client": "",
        "property": "",
        "title": "",
        "job_type": "Service",
        "date": date.today().isoformat(),
        "status": "Scheduled",
        "billing_status": "Unbilled",
        "crew": "Randy",
        "amount": 0,
        "notes": "",
    }

    def selected(current, value):
        return "selected" if current == value else ""

    return f"""
    <div class="card">
        <form method="post" action="{action}">
            <div class="form-grid">
                <input name="client" placeholder="Client" value="{j["client"]}" required>
                <input name="property" placeholder="Property" value="{j["property"]}" required>
                <input name="title" placeholder="Job Title" value="{j["title"]}" required>
                <select name="job_type">
                    <option {selected(j["job_type"], "Service")}>Service</option>
                    <option {selected(j["job_type"], "Install")}>Install</option>
                    <option {selected(j["job_type"], "Repair")}>Repair</option>
                    <option {selected(j["job_type"], "Remodel")}>Remodel</option>
                    <option {selected(j["job_type"], "Auto Cover")}>Auto Cover</option>
                    <option {selected(j["job_type"], "EcoFinish")}>EcoFinish</option>
                </select>
                <input name="job_date" type="date" value="{j["date"]}">
                <select name="status">
                    <option {selected(j["status"], "Scheduled")}>Scheduled</option>
                    <option {selected(j["status"], "In Progress")}>In Progress</option>
                    <option {selected(j["status"], "Completed")}>Completed</option>
                    <option {selected(j["status"], "On Hold")}>On Hold</option>
                </select>
                <select name="billing_status">
                    <option {selected(j["billing_status"], "Unbilled")}>Unbilled</option>
                    <option {selected(j["billing_status"], "Ready to Bill")}>Ready to Bill</option>
                    <option {selected(j["billing_status"], "Paid")}>Paid</option>
                </select>
                <input name="crew" placeholder="Crew" value="{j["crew"]}">
                <input name="amount" type="number" step="0.01" placeholder="Amount" value="{j["amount"]}">
            </div>
            <textarea name="notes" placeholder="Notes">{j["notes"]}</textarea>
            <button class="btn" type="submit">{button_text}</button>
        </form>
    </div>
    """


@app.get("/add-job", response_class=HTMLResponse)
def add_job_get(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    body = f"""
    <div class="hero"><h2>Add Job</h2><p>Create a new contractor job.</p></div>
    {job_form("/add-job", "Add Job")}
    """
    return page("Add Job", body, user)


@app.post("/add-job")
def add_job_post(
    request: Request,
    client: str = Form(...),
    property: str = Form(...),
    title: str = Form(...),
    job_type: str = Form(...),
    job_date: str = Form(...),
    status: str = Form(...),
    billing_status: str = Form(...),
    crew: str = Form(...),
    amount: float = Form(...),
    notes: str = Form(""),
):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    JOBS.append({
        "id": next_id(JOBS),
        "client": client,
        "property": property,
        "title": title,
        "job_type": job_type,
        "date": job_date,
        "status": status,
        "billing_status": billing_status,
        "crew": crew,
        "amount": amount,
        "notes": notes,
    })
    return RedirectResponse("/jobs", status_code=303)


@app.get("/edit-job/{job_id}", response_class=HTMLResponse)
def edit_job_get(request: Request, job_id: int):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    job = next((j for j in JOBS if j["id"] == job_id), None)
    if not job:
        return RedirectResponse("/jobs", status_code=303)

    body = f"""
    <div class="hero"><h2>Edit Job</h2><p>Update job details.</p></div>
    {job_form(f"/edit-job/{job_id}", "Save Changes", job)}
    """
    return page("Edit Job", body, user)


@app.post("/edit-job/{job_id}")
def edit_job_post(
    request: Request,
    job_id: int,
    client: str = Form(...),
    property: str = Form(...),
    title: str = Form(...),
    job_type: str = Form(...),
    job_date: str = Form(...),
    status: str = Form(...),
    billing_status: str = Form(...),
    crew: str = Form(...),
    amount: float = Form(...),
    notes: str = Form(""),
):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    for j in JOBS:
        if j["id"] == job_id:
            j.update({
                "client": client,
                "property": property,
                "title": title,
                "job_type": job_type,
                "date": job_date,
                "status": status,
                "billing_status": billing_status,
                "crew": crew,
                "amount": amount,
                "notes": notes,
            })
            break

    return RedirectResponse("/jobs", status_code=303)


@app.get("/delete-job/{job_id}")
def delete_job(request: Request, job_id: int):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    global JOBS
    JOBS = [j for j in JOBS if j["id"] != job_id]
    return RedirectResponse("/jobs", status_code=303)


@app.get("/clients", response_class=HTMLResponse)
def clients(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    rows = "".join(f"<tr><td>{c['name']}</td><td>{c['phone']}</td><td>{c['email']}</td><td>{c['notes']}</td></tr>" for c in CLIENTS)
    body = f"""
    <div class="hero"><h2>Clients</h2><p>Add and track customers.</p></div>
    <div class="card">
        <form method="post" action="/clients">
            <div class="form-grid">
                <input name="name" placeholder="Client Name" required>
                <input name="phone" placeholder="Phone">
                <input name="email" placeholder="Email">
                <input name="notes" placeholder="Notes">
            </div>
            <button class="btn">Add Client</button>
        </form>
    </div>
    <table><tr><th>Name</th><th>Phone</th><th>Email</th><th>Notes</th></tr>{rows}</table>
    """
    return page("Clients", body, user)


@app.post("/clients")
def add_client(request: Request, name: str = Form(...), phone: str = Form(""), email: str = Form(""), notes: str = Form("")):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    CLIENTS.append({"id": next_id(CLIENTS), "name": name, "phone": phone, "email": email, "notes": notes})
    return RedirectResponse("/clients", status_code=303)


@app.get("/properties", response_class=HTMLResponse)
def properties(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    rows = "".join(f"<tr><td>{p['client']}</td><td>{p['name']}</td><td>{p['address']}</td><td>{p['notes']}</td></tr>" for p in PROPERTIES)
    body = f"""
    <div class="hero"><h2>Properties</h2><p>Track client pool properties and addresses.</p></div>
    <div class="card">
        <form method="post" action="/properties">
            <div class="form-grid">
                <input name="client" placeholder="Client" required>
                <input name="name" placeholder="Property Name" required>
                <input name="address" placeholder="Address">
                <input name="notes" placeholder="Notes">
            </div>
            <button class="btn">Add Property</button>
        </form>
    </div>
    <table><tr><th>Client</th><th>Property</th><th>Address</th><th>Notes</th></tr>{rows}</table>
    """
    return page("Properties", body, user)


@app.post("/properties")
def add_property(request: Request, client: str = Form(...), name: str = Form(...), address: str = Form(""), notes: str = Form("")):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    PROPERTIES.append({"id": next_id(PROPERTIES), "client": client, "name": name, "address": address, "notes": notes})
    return RedirectResponse("/properties", status_code=303)


@app.get("/employees", response_class=HTMLResponse)
def employees(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    rows = "".join(f"<tr><td>{e['name']}</td><td>{e['role']}</td><td>{e['phone']}</td></tr>" for e in EMPLOYEES)
    body = f"""
    <div class="hero"><h2>Employees</h2><p>Track crew members and roles.</p></div>
    <div class="card">
        <form method="post" action="/employees">
            <div class="form-grid">
                <input name="name" placeholder="Employee Name" required>
                <input name="role" placeholder="Role">
                <input name="phone" placeholder="Phone">
            </div>
            <button class="btn">Add Employee</button>
        </form>
    </div>
    <table><tr><th>Name</th><th>Role</th><th>Phone</th></tr>{rows}</table>
    """
    return page("Employees", body, user)


@app.post("/employees")
def add_employee(request: Request, name: str = Form(...), role: str = Form("Crew"), phone: str = Form("")):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    EMPLOYEES.append({"id": next_id(EMPLOYEES), "name": name, "role": role, "phone": phone})
    return RedirectResponse("/employees", status_code=303)


@app.get("/schedule", response_class=HTMLResponse)
def schedule(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    sorted_jobs = sorted(JOBS, key=lambda j: j["date"])
    rows = "".join(
        f"<tr><td>{j['date']}</td><td>{j['client']}</td><td>{j['title']}</td><td>{j['crew']}</td><td>{j['status']}</td></tr>"
        for j in sorted_jobs
    )
    body = f"""
    <div class="hero"><h2>Schedule</h2><p>Simple schedule view from job dates.</p></div>
    <table><tr><th>Date</th><th>Client</th><th>Job</th><th>Crew</th><th>Status</th></tr>{rows}</table>
    """
    return page("Schedule", body, user)


@app.get("/my-day", response_class=HTMLResponse)
def my_day(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    username = user["username"]
    if username not in TIME_CLOCK:
        TIME_CLOCK[username] = {"clocked_in": False, "last_action": ""}

    clock = TIME_CLOCK[username]
    visible_jobs = [j for j in JOBS if user["role"] == "admin" or j["crew"].lower() == user["name"].lower()]

    cards = ""
    for j in visible_jobs:
        cards += f"""
        <div class="card">
            <h3>{j["title"]}</h3>
            <p><b>Client:</b> {j["client"]}</p>
            <p><b>Property:</b> {j["property"]}</p>
            <p><b>Status:</b> {j["status"]}</p>
            <p class="muted">{j["notes"]}</p>
            <div class="actions">
                <form method="post" action="/jobs/{j["id"]}/start"><button class="btn">Start Job</button></form>
                <form method="post" action="/jobs/{j["id"]}/complete"><button class="btn">Complete Job</button></form>
            </div>
        </div>
        """

    body = f"""
    <div class="hero"><h2>My Day</h2><p>Crew workflow for clock-in, start job, and complete job.</p></div>
    <div class="card">
        <h3>Clock Status</h3>
        <div class="metric">{"Clocked In" if clock["clocked_in"] else "Clocked Out"}</div>
        <p class="muted">Last action: {clock["last_action"] or "None"}</p>
        <form method="post" action="/clock-toggle">
            <button class="btn">{"Clock Out" if clock["clocked_in"] else "Clock In"}</button>
        </form>
    </div>
    {cards}
    """
    return page("My Day", body, user)


@app.post("/clock-toggle")
def clock_toggle(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    username = user["username"]
    if username not in TIME_CLOCK:
        TIME_CLOCK[username] = {"clocked_in": False, "last_action": ""}

    TIME_CLOCK[username]["clocked_in"] = not TIME_CLOCK[username]["clocked_in"]
    TIME_CLOCK[username]["last_action"] = datetime.now().strftime("%m/%d/%Y %I:%M %p")
    return RedirectResponse("/my-day", status_code=303)


@app.post("/jobs/{job_id}/start")
def start_job(request: Request, job_id: int):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    for j in JOBS:
        if j["id"] == job_id:
            j["status"] = "In Progress"
            j["crew"] = user["name"]
    return RedirectResponse("/my-day", status_code=303)


@app.post("/jobs/{job_id}/complete")
def complete_job(request: Request, job_id: int):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    for j in JOBS:
        if j["id"] == job_id:
            j["status"] = "Completed"
            j["billing_status"] = "Ready to Bill"
    return RedirectResponse("/my-day", status_code=303)


@app.get("/billing", response_class=HTMLResponse)
def billing(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    total = sum(j["amount"] for j in JOBS)
    ready = sum(j["amount"] for j in JOBS if j["billing_status"] == "Ready to Bill")
    paid = sum(j["amount"] for j in JOBS if j["billing_status"] == "Paid")
    unbilled = sum(j["amount"] for j in JOBS if j["billing_status"] == "Unbilled")

    rows = "".join(f"<tr><td>{j['client']}</td><td>{j['title']}</td><td>{j['billing_status']}</td><td>{money(j['amount'])}</td></tr>" for j in JOBS)

    body = f"""
    <div class="hero"><h2>Billing</h2><p>Track work value, ready-to-bill work, and paid jobs.</p></div>
    <div class="grid">
        <div class="card"><h3>Total</h3><div class="metric">{money(total)}</div></div>
        <div class="card"><h3>Ready to Bill</h3><div class="metric">{money(ready)}</div></div>
        <div class="card"><h3>Paid</h3><div class="metric">{money(paid)}</div></div>
        <div class="card"><h3>Unbilled</h3><div class="metric">{money(unbilled)}</div></div>
    </div>
    <table><tr><th>Client</th><th>Job</th><th>Billing</th><th>Amount</th></tr>{rows}</table>
    """
    return page("Billing", body, user)


@app.get("/quickbooks-export")
def quickbooks_export(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Customer", "Product/Service", "Description", "Qty", "Rate", "Amount", "Service Date", "Memo"])

    for j in JOBS:
        if j["billing_status"] in ["Ready to Bill", "Unbilled", "Paid"]:
            writer.writerow([
                j["client"],
                j["job_type"],
                j["title"],
                1,
                f"{j['amount']:.2f}",
                f"{j['amount']:.2f}",
                j["date"],
                j["notes"],
            ])

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=poolops_quickbooks_export.csv"},
    )