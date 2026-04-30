from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="PoolOps Pro")

app.add_middleware(SessionMiddleware, secret_key="poolops-secret-key")

# ================= USERS =================
USERS = {
    "mike": {"password": "5500", "role": "admin", "name": "Mike"},
    "randy": {"password": "0318", "role": "crew", "name": "Randy"},
    "traylor": {"password": "8899", "role": "client", "name": "Traylor"},
}

# ================= JOB STORAGE =================
JOBS = []
JOB_ID = 1

TIME_CLOCK = {}

# ================= HELPERS =================
def get_user(request: Request):
    return request.session.get("user")

def money(v):
    return f"${float(v):,.2f}"

# ================= UI =================
def css():
    return """
    <style>
    body { background:#07111f; color:#fff; font-family:Arial; margin:0; }
    .wrap { max-width:1100px; margin:auto; padding:20px; }

    .topbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }
    .logo { height:60px; }

    .nav a {
        margin-left:10px;
        padding:8px 12px;
        background:#132238;
        border-radius:10px;
        text-decoration:none;
        color:white;
        font-weight:bold;
    }

    .card {
        background:#0f172a;
        padding:20px;
        border-radius:15px;
        margin-bottom:15px;
        border:1px solid #243449;
    }

    input, select, textarea {
        width:100%;
        padding:10px;
        margin-bottom:10px;
        background:#020617;
        color:white;
        border:1px solid #333;
        border-radius:8px;
    }

    button {
        padding:10px 15px;
        border:none;
        border-radius:10px;
        background:#1e3a5f;
        color:white;
        font-weight:bold;
        cursor:pointer;
    }

    table {
        width:100%;
        border-collapse:collapse;
    }

    th, td {
        padding:10px;
        border-bottom:1px solid #243449;
    }

    h1 { margin:0 0 10px; }
    </style>
    """

def nav(user):
    return f"""
    <div class="topbar">
        <img src="/static/logo.png" class="logo">
        <div class="nav">
            <a href="/dashboard">Dashboard</a>
            <a href="/jobs">Jobs</a>
            <a href="/add-job">Add Job</a>
            <a href="/billing">Billing</a>
            <a href="/logout">Logout</a>
        </div>
    </div>
    """

def page(title, body, user):
    return f"""
    <html>
    <head>
        <title>{title}</title>
        {css()}
    </head>
    <body>
        <div class="wrap">
            {nav(user)}
            {body}
        </div>
    </body>
    </html>
    """

# ================= AUTH =================
@app.get("/")
def home():
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return f"""
    <html><head>{css()}</head><body>
    <div class="wrap">
        <div class="card">
            <h1>Login</h1>
            <form method="post" action="/login">
                <input name="username" placeholder="Username">
                <input name="password" type="password" placeholder="Password">
                <button>Login</button>
            </form>
        </div>
    </div>
    </body></html>
    """

@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = USERS.get(username.lower())

    if not user or user["password"] != password:
        return RedirectResponse("/login", status_code=303)

    request.session["user"] = {
        "username": username,
        "name": user["name"],
        "role": user["role"]
    }

    return RedirectResponse("/dashboard", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")

# ================= DASHBOARD =================
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login")

    total = sum(j["amount"] for j in JOBS)

    body = f"""
    <div class="card">
        <h1>Welcome {user["name"]}</h1>
        <p>Total Jobs: {len(JOBS)}</p>
        <p>Total Work: {money(total)}</p>
    </div>
    """

    return page("Dashboard", body, user)

# ================= ADD JOB =================
@app.get("/add-job", response_class=HTMLResponse)
def add_job_page(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login")

    body = """
    <div class="card">
        <h1>Add Job</h1>
        <form method="post" action="/add-job">
            <input name="client" placeholder="Client">
            <input name="property" placeholder="Property">
            <input name="title" placeholder="Job Title">

            <select name="job_type">
                <option>Service</option>
                <option>Install</option>
                <option>Repair</option>
            </select>

            <input name="date" type="date">

            <select name="status">
                <option>Scheduled</option>
                <option>In Progress</option>
                <option>Completed</option>
            </select>

            <select name="billing_status">
                <option>Unbilled</option>
                <option>Ready to Bill</option>
                <option>Paid</option>
            </select>

            <input name="crew" placeholder="Crew">
            <input name="amount" placeholder="Amount">
            <textarea name="notes" placeholder="Notes"></textarea>

            <button>Add Job</button>
        </form>
    </div>
    """

    return page("Add Job", body, user)

@app.post("/add-job")
def add_job(
    request: Request,
    client: str = Form(...),
    property: str = Form(...),
    title: str = Form(...),
    job_type: str = Form(...),
    date: str = Form(...),
    status: str = Form(...),
    billing_status: str = Form(...),
    crew: str = Form(...),
    amount: float = Form(...),
    notes: str = Form(...)
):
    global JOB_ID

    JOBS.append({
        "id": JOB_ID,
        "client": client,
        "property": property,
        "title": title,
        "job_type": job_type,
        "date": date,
        "status": status,
        "billing_status": billing_status,
        "crew": crew,
        "amount": amount,
        "notes": notes
    })

    JOB_ID += 1

    return RedirectResponse("/jobs", status_code=303)

# ================= JOB LIST =================
@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login")

    rows = ""

    for j in JOBS:
        rows += f"""
        <tr>
            <td>{j["client"]}</td>
            <td>{j["title"]}</td>
            <td>{j["status"]}</td>
            <td>{j["billing_status"]}</td>
            <td>{money(j["amount"])}</td>
            <td>
                <a href="/delete-job/{j["id"]}">Delete</a>
            </td>
        </tr>
        """

    body = f"""
    <div class="card">
        <h1>Jobs</h1>
        <table>
            <tr>
                <th>Client</th>
                <th>Job</th>
                <th>Status</th>
                <th>Billing</th>
                <th>Amount</th>
                <th></th>
            </tr>
            {rows}
        </table>
    </div>
    """

    return page("Jobs", body, user)

@app.get("/delete-job/{job_id}")
def delete_job(job_id: int):
    global JOBS
    JOBS = [j for j in JOBS if j["id"] != job_id]
    return RedirectResponse("/jobs")

# ================= BILLING =================
@app.get("/billing", response_class=HTMLResponse)
def billing(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login")

    total = sum(j["amount"] for j in JOBS)
    ready = sum(j["amount"] for j in JOBS if j["billing_status"] == "Ready to Bill")

    body = f"""
    <div class="card">
        <h1>Billing</h1>
        <p>Total: {money(total)}</p>
        <p>Ready to Bill: {money(ready)}</p>
    </div>
    """

    return page("Billing", body, user)