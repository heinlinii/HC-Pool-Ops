from datetime import datetime, date

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


def nav():
    return """
    <p>
        <a href="/dashboard">Dashboard</a> |
        <a href="/jobs">Jobs</a> |
        <a href="/my-day">My Day</a> |
        <a href="/billing">Billing</a> |
        <a href="/logout">Logout</a>
    </p>
    <hr>
    """


def page(title, body):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title}</title>
        <style>
            body {{ font-family: Arial; padding: 30px; background: #0f172a; color: white; }}
            a {{ color: #38bdf8; }}
            table {{ border-collapse: collapse; width: 100%; background: #111827; }}
            th, td {{ border: 1px solid #334155; padding: 10px; text-align: left; }}
            button {{ padding: 10px 14px; margin: 4px; }}
            input {{ padding: 10px; margin: 8px 0; width: 260px; }}
            .card {{ background: #111827; padding: 20px; margin: 15px 0; border: 1px solid #334155; }}
        </style>
    </head>
    <body>
        {body}
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
def login_page():
    return page(
        "Login",
        """
        <h1>PoolOps Pro Login</h1>
        <form method="post" action="/login">
            <input name="username" placeholder="Username" required><br>
            <input name="password" type="password" placeholder="Password" required><br>
            <button type="submit">Login</button>
        </form>
        <p>mike / 5500</p>
        <p>randy / 0318</p>
        <p>traylor / 8899</p>
        """,
    )


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip().lower()
    password = password.strip()

    found = USERS.get(username)

    if not found or found["password"] != password:
        return HTMLResponse(
            page("Login Error", '<h1>Invalid login</h1><p><a href="/login">Try again</a></p>'),
            status_code=401,
        )

    request.session.clear()
    request.session["user"] = {
        "username": username,
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

    total = sum(j["amount"] for j in JOBS)
    ready = sum(j["amount"] for j in JOBS if j["billing_status"] == "Ready to Bill")

    body = f"""
    {nav()}
    <h1>Dashboard</h1>
    <div class="card">
        <h2>Welcome, {user["name"]}</h2>
        <p>Role: {user["role"]}</p>
    </div>
    <div class="card">
        <h3>Total Jobs: {len(JOBS)}</h3>
        <h3>Total Work: ${total:,.2f}</h3>
        <h3>Ready to Bill: ${ready:,.2f}</h3>
    </div>
    """
    return page("Dashboard", body)


@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    rows = ""
    for j in JOBS:
        rows += f"""
        <tr>
            <td>{j["id"]}</td>
            <td>{j["client"]}</td>
            <td>{j["property"]}</td>
            <td>{j["title"]}</td>
            <td>{j["status"]}</td>
            <td>{j["crew"]}</td>
            <td>{j["billing_status"]}</td>
            <td>${j["amount"]:,.2f}</td>
        </tr>
        """

    body = f"""
    {nav()}
    <h1>Jobs</h1>
    <table>
        <tr>
            <th>ID</th><th>Client</th><th>Property</th><th>Job</th>
            <th>Status</th><th>Crew</th><th>Billing</th><th>Amount</th>
        </tr>
        {rows}
    </table>
    """
    return page("Jobs", body)


@app.get("/my-day", response_class=HTMLResponse)
def my_day(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    username = user["username"]
    clocked = TIME_CLOCK.get(username, False)

    job_cards = ""
    for j in JOBS:
        if user["role"] == "admin" or j["crew"].lower() == user["name"].lower():
            job_cards += f"""
            <div class="card">
                <h3>{j["title"]}</h3>
                <p><b>Client:</b> {j["client"]}</p>
                <p><b>Status:</b> {j["status"]}</p>
                <p>{j["notes"]}</p>
                <form method="post" action="/jobs/{j["id"]}/start">
                    <button>Start Job</button>
                </form>
                <form method="post" action="/jobs/{j["id"]}/complete">
                    <button>Complete Job</button>
                </form>
            </div>
            """

    body = f"""
    {nav()}
    <h1>My Day</h1>
    <div class="card">
        <h3>Clock Status: {"Clocked In" if clocked else "Clocked Out"}</h3>
        <form method="post" action="/clock-toggle">
            <button>{"Clock Out" if clocked else "Clock In"}</button>
        </form>
    </div>
    {job_cards}
    """
    return page("My Day", body)


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

    for j in JOBS:
        if j["id"] == job_id:
            j["status"] = "In Progress"
            j["crew"] = user["name"]

    return RedirectResponse("/my-day", status_code=303)


@app.post("/jobs/{job_id}/complete")
def complete_job(request: Request, job_id: int):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    for j in JOBS:
        if j["id"] == job_id:
            j["status"] = "Completed"
            j["billing_status"] = "Ready to Bill"

    return RedirectResponse("/my-day", status_code=303)


@app.get("/billing", response_class=HTMLResponse)
def billing(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    total = sum(j["amount"] for j in JOBS)
    ready = sum(j["amount"] for j in JOBS if j["billing_status"] == "Ready to Bill")
    unbilled = sum(j["amount"] for j in JOBS if j["billing_status"] == "Unbilled")

    body = f"""
    {nav()}
    <h1>Billing</h1>
    <div class="card">
        <h3>Total: ${total:,.2f}</h3>
        <h3>Ready to Bill: ${ready:,.2f}</h3>
        <h3>Unbilled: ${unbilled:,.2f}</h3>
    </div>
    """
    return page("Billing", body)