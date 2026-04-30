from datetime import datetime

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="PoolOps Pro")

app.add_middleware(SessionMiddleware, secret_key="poolops-secret-key")


USERS = {
    "mike": {"password": "5500", "role": "admin", "name": "Mike"},
    "randy": {"password": "0318", "role": "crew", "name": "Randy"},
    "traylor": {"password": "8899", "role": "client", "name": "Traylor"},
}


JOBS = [
    {
        "id": 1,
        "client": "Traylor",
        "property": "Traylor Residence",
        "title": "Pool Service",
        "status": "Scheduled",
        "crew": "Randy",
        "amount": 450.00,
        "billing_status": "Unbilled",
        "notes": "Clean pool, check equipment, inspect cover.",
    },
    {
        "id": 2,
        "client": "Sample Client",
        "property": "Sample Property",
        "title": "Automatic Cover Repair",
        "status": "Scheduled",
        "crew": "Randy",
        "amount": 1250.00,
        "billing_status": "Ready to Bill",
        "notes": "Inspect tracks, pulleys, motor, and cover box.",
    },
]


TIME_CLOCK = {
    "mike": False,
    "randy": False,
    "traylor": False,
}


def get_user(request: Request):
    user = request.session.get("user")
    if isinstance(user, dict):
        return user

    request.session.clear()
    return None


def money(value):
    return f"${value:,.2f}"


def css():
    return """
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            font-family: Arial, Helvetica, sans-serif;
            background: #07111f;
            color: #f8fafc;
        }

        a {
            color: inherit;
            text-decoration: none;
        }

        .shell {
            max-width: 1200px;
            margin: 0 auto;
            padding: 28px;
        }

        .topbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 18px;
            margin-bottom: 26px;
        }

        .brand {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .brand h1 {
            margin: 0;
            font-size: 28px;
            letter-spacing: -0.04em;
        }

        .brand span {
            color: #94a3b8;
            font-size: 14px;
        }

        .nav {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .nav a,
        .btn {
            display: inline-block;
            padding: 10px 14px;
            border-radius: 12px;
            background: #132238;
            color: #e2e8f0;
            border: 1px solid #243449;
            font-weight: 700;
            cursor: pointer;
        }

        .nav a:hover,
        .btn:hover {
            background: #1e3a5f;
        }

        .hero {
            background: linear-gradient(135deg, #0f2742, #111827);
            border: 1px solid #243449;
            border-radius: 22px;
            padding: 28px;
            margin-bottom: 22px;
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
            gap: 18px;
        }

        .card {
            background: #0f172a;
            border: 1px solid #243449;
            border-radius: 20px;
            padding: 22px;
            box-shadow: 0 12px 40px rgba(0,0,0,0.22);
        }

        .card h3 {
            margin: 0 0 10px;
            color: #f8fafc;
        }

        .metric {
            font-size: 32px;
            font-weight: 900;
            color: #38bdf8;
            margin-top: 8px;
        }

        .muted {
            color: #94a3b8;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            overflow: hidden;
            border-radius: 16px;
            background: #0f172a;
            border: 1px solid #243449;
        }

        th,
        td {
            padding: 13px 14px;
            border-bottom: 1px solid #243449;
            text-align: left;
        }

        th {
            background: #132238;
            color: #cbd5e1;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: .04em;
        }

        tr:last-child td {
            border-bottom: none;
        }

        .status {
            display: inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 800;
            background: #1e293b;
            color: #e2e8f0;
        }

        .ready {
            background: #064e3b;
            color: #a7f3d0;
        }

        .unbilled {
            background: #78350f;
            color: #fde68a;
        }

        form {
            margin: 0;
        }

        input {
            width: 100%;
            padding: 13px 14px;
            border-radius: 12px;
            border: 1px solid #334155;
            background: #020617;
            color: #f8fafc;
            margin-bottom: 12px;
            font-size: 16px;
        }

        button {
            border: none;
        }

        .login-wrap {
            min-height: 100vh;
            display: grid;
            place-items: center;
            padding: 24px;
        }

        .login-card {
            width: 100%;
            max-width: 430px;
            background: #0f172a;
            border: 1px solid #243449;
            border-radius: 24px;
            padding: 30px;
            box-shadow: 0 22px 80px rgba(0,0,0,0.45);
        }

        .login-card h1 {
            margin: 0 0 8px;
            font-size: 32px;
        }

        .error {
            background: #7f1d1d;
            color: #fee2e2;
            padding: 12px;
            border-radius: 12px;
            margin-bottom: 14px;
        }

        .actions {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 12px;
        }

        @media (max-width: 800px) {
            .topbar {
                align-items: flex-start;
                flex-direction: column;
            }

            .grid {
                grid-template-columns: 1fr;
            }

            .shell {
                padding: 18px;
            }

            table {
                font-size: 13px;
            }
        }
    </style>
    """


def nav(user=None):
    name = user["name"] if user else "Guest"
    role = user["role"] if user else ""
    return f"""
    <div class="topbar">
        <div class="brand">
            <h1>PoolOps Pro</h1>
            <span>Heinlin Concrete • Logged in as {name} {f"({role})" if role else ""}</span>
        </div>
        <div class="nav">
            <a href="/dashboard">Dashboard</a>
            <a href="/jobs">Jobs</a>
            <a href="/my-day">My Day</a>
            <a href="/billing">Billing</a>
            <a href="/logout">Logout</a>
        </div>
    </div>
    """


def page(title, body, user=None):
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
            {nav(user) if user else ""}
            {body}
        </div>
    </body>
    </html>
    """


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "PoolOps Pro",
        "time": datetime.now().isoformat(),
    }


@app.get("/")
def home():
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    body = f"""
    <div class="login-wrap">
        <div class="login-card">
            <h1>PoolOps Pro</h1>
            <p class="muted">Sign in to manage jobs, crews, billing, and schedules.</p>

            <form method="post" action="/login">
                <input name="username" placeholder="Username" required>
                <input name="password" type="password" placeholder="Password" required>
                <button class="btn" type="submit">Login</button>
            </form>

            <div class="card" style="margin-top:18px;">
                <h3>Test Logins</h3>
                <p class="muted">mike / 5500 = admin</p>
                <p class="muted">randy / 0318 = crew</p>
                <p class="muted">traylor / 8899 = client</p>
            </div>
        </div>
    </div>
    """
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login • PoolOps Pro</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {css()}
    </head>
    <body>
        {body}
    </body>
    </html>
    """


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    username_clean = username.strip().lower()
    password_clean = password.strip()

    found = USERS.get(username_clean)

    if not found or found["password"] != password_clean:
        body = f"""
        <div class="login-wrap">
            <div class="login-card">
                <h1>PoolOps Pro</h1>
                <div class="error">Invalid username or password.</div>
                <form method="post" action="/login">
                    <input name="username" placeholder="Username" required>
                    <input name="password" type="password" placeholder="Password" required>
                    <button class="btn" type="submit">Try Again</button>
                </form>
            </div>
        </div>
        """
        return HTMLResponse(
            f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Login Error • PoolOps Pro</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                {css()}
            </head>
            <body>{body}</body>
            </html>
            """,
            status_code=401,
        )

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
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    total = sum(job["amount"] for job in JOBS)
    ready = sum(job["amount"] for job in JOBS if job["billing_status"] == "Ready to Bill")
    unbilled = sum(job["amount"] for job in JOBS if job["billing_status"] == "Unbilled")

    body = f"""
    <div class="hero">
        <h2>Dashboard</h2>
        <p>Welcome back, {user["name"]}. This is your live PoolOps command center.</p>
    </div>

    <div class="grid">
        <div class="card">
            <h3>Total Jobs</h3>
            <div class="metric">{len(JOBS)}</div>
            <p class="muted">Active sample jobs currently loaded.</p>
        </div>

        <div class="card">
            <h3>Total Work</h3>
            <div class="metric">{money(total)}</div>
            <p class="muted">Current open work value.</p>
        </div>

        <div class="card">
            <h3>Ready to Bill</h3>
            <div class="metric">{money(ready)}</div>
            <p class="muted">Unbilled: {money(unbilled)}</p>
        </div>
    </div>
    """

    return page("Dashboard", body, user)


@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    rows = ""
    for job in JOBS:
        billing_class = "ready" if job["billing_status"] == "Ready to Bill" else "unbilled"
        rows += f"""
        <tr>
            <td>{job["id"]}</td>
            <td>{job["client"]}</td>
            <td>{job["property"]}</td>
            <td>{job["title"]}</td>
            <td><span class="status">{job["status"]}</span></td>
            <td>{job["crew"]}</td>
            <td><span class="status {billing_class}">{job["billing_status"]}</span></td>
            <td>{money(job["amount"])}</td>
        </tr>
        """

    body = f"""
    <div class="hero">
        <h2>Jobs</h2>
        <p>View current jobs, crew assignments, status, and billing readiness.</p>
    </div>

    <table>
        <tr>
            <th>ID</th>
            <th>Client</th>
            <th>Property</th>
            <th>Job</th>
            <th>Status</th>
            <th>Crew</th>
            <th>Billing</th>
            <th>Amount</th>
        </tr>
        {rows}
    </table>
    """

    return page("Jobs", body, user)


@app.get("/my-day", response_class=HTMLResponse)
def my_day(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    username = user["username"]
    clocked_in = TIME_CLOCK.get(username, False)

    cards = ""

    for job in JOBS:
        if user["role"] == "admin" or job["crew"].lower() == user["name"].lower():
            cards += f"""
            <div class="card">
                <h3>{job["title"]}</h3>
                <p><b>Client:</b> {job["client"]}</p>
                <p><b>Property:</b> {job["property"]}</p>
                <p><b>Status:</b> <span class="status">{job["status"]}</span></p>
                <p class="muted">{job["notes"]}</p>

                <div class="actions">
                    <form method="post" action="/jobs/{job["id"]}/start">
                        <button class="btn" type="submit">Start Job</button>
                    </form>
                    <form method="post" action="/jobs/{job["id"]}/complete">
                        <button class="btn" type="submit">Complete Job</button>
                    </form>
                </div>
            </div>
            """

    body = f"""
    <div class="hero">
        <h2>My Day</h2>
        <p>Field workflow for clocking in, starting jobs, and completing work.</p>
    </div>

    <div class="card">
        <h3>Clock Status</h3>
        <div class="metric">{"Clocked In" if clocked_in else "Clocked Out"}</div>
        <form method="post" action="/clock-toggle" style="margin-top:12px;">
            <button class="btn" type="submit">{"Clock Out" if clocked_in else "Clock In"}</button>
        </form>
    </div>

    {cards}
    """

    return page("My Day", body, user)


@app.post("/clock-toggle")
def clock_toggle(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    username = user["username"]
    TIME_CLOCK[username] = not TIME_CLOCK.get(username, False)

    return RedirectResponse("/my-day", status_code=303)


@app.post("/jobs/{job_id}/start")
def start_job(request: Request, job_id: int):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    for job in JOBS:
        if job["id"] == job_id:
            job["status"] = "In Progress"
            job["crew"] = user["name"]

    return RedirectResponse("/my-day", status_code=303)


@app.post("/jobs/{job_id}/complete")
def complete_job(request: Request, job_id: int):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    for job in JOBS:
        if job["id"] == job_id:
            job["status"] = "Completed"
            job["billing_status"] = "Ready to Bill"

    return RedirectResponse("/my-day", status_code=303)


@app.get("/billing", response_class=HTMLResponse)
def billing(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    total = sum(job["amount"] for job in JOBS)
    ready = sum(job["amount"] for job in JOBS if job["billing_status"] == "Ready to Bill")
    unbilled = sum(job["amount"] for job in JOBS if job["billing_status"] == "Unbilled")

    rows = ""
    for job in JOBS:
        rows += f"""
        <tr>
            <td>{job["client"]}</td>
            <td>{job["title"]}</td>
            <td>{job["billing_status"]}</td>
            <td>{money(job["amount"])}</td>
        </tr>
        """

    body = f"""
    <div class="hero">
        <h2>Billing</h2>
        <p>Track work value and what is ready to invoice.</p>
    </div>

    <div class="grid">
        <div class="card">
            <h3>Total</h3>
            <div class="metric">{money(total)}</div>
        </div>
        <div class="card">
            <h3>Ready to Bill</h3>
            <div class="metric">{money(ready)}</div>
        </div>
        <div class="card">
            <h3>Unbilled</h3>
            <div class="metric">{money(unbilled)}</div>
        </div>
    </div>

    <div style="height:18px;"></div>

    <table>
        <tr>
            <th>Client</th>
            <th>Job</th>
            <th>Billing Status</th>
            <th>Amount</th>
        </tr>
        {rows}
    </table>
    """

    return page("Billing", body, user)