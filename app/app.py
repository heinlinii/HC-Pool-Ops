from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="PoolOps2")

app.add_middleware(SessionMiddleware, secret_key="poolops2-phase1-secret")


USERS = {
    "mike": {"password": "5500", "role": "admin", "name": "Mike"},
    "randy": {"password": "0318", "role": "crew", "name": "Randy"},
}

JOBS = [
    {
        "id": 1,
        "client": "Smith Residence",
        "address": "Evansville, IN",
        "job_type": "Concrete Pool",
        "status": "Scheduled",
        "crew": "Randy",
        "date": "Today",
        "notes": "20x40 rectangle pool",
    },
    {
        "id": 2,
        "client": "Johnson Backyard",
        "address": "Newburgh, IN",
        "job_type": "Pool Remodel",
        "status": "Pending",
        "crew": "Unassigned",
        "date": "Tomorrow",
        "notes": "Tile and coping replacement",
    },
]

TIME_CLOCK = {
    "randy": {"clocked_in": False, "current_job": None}
}


def page(title, body):
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            margin: 0;
            font-family: Arial, sans-serif;
            background: #111827;
            color: white;
        }}
        .wrap {{
            max-width: 1100px;
            margin: auto;
            padding: 24px;
        }}
        .card {{
            background: #1f2937;
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 20px;
        }}
        input, select, textarea {{
            width: 100%;
            padding: 12px;
            margin: 8px 0 16px;
            border-radius: 10px;
            border: 0;
            background: #374151;
            color: white;
        }}
        button, a.btn {{
            display: inline-block;
            background: #2563eb;
            color: white;
            padding: 12px 16px;
            border-radius: 10px;
            border: 0;
            text-decoration: none;
            font-weight: bold;
            margin: 4px;
            cursor: pointer;
        }}
        .danger {{ background: #dc2626; }}
        .success {{ background: #16a34a; }}
        .nav a {{
            color: white;
            margin-right: 12px;
            text-decoration: none;
            font-weight: bold;
        }}
        .job {{
            border: 1px solid #374151;
            border-radius: 14px;
            padding: 16px;
            margin: 12px 0;
            background: #111827;
        }}
        .pill {{
            background: #2563eb;
            border-radius: 999px;
            padding: 6px 10px;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="wrap">
        {body}
    </div>
</body>
</html>
""")


def get_user(request: Request):
    username = request.session.get("username")
    if not username:
        return None
    record = USERS.get(username)
    if not record:
        return None
    return {
        "username": username,
        "name": record["name"],
        "role": record["role"],
    }


def nav(user):
    return f"""
    <div class="card nav">
        <h1>PoolOps2</h1>
        <p>Logged in as {user["name"]} / {user["role"]}</p>
        <a href="/dashboard">Dashboard</a>
        <a href="/jobs">Jobs</a>
        <a href="/schedule">Schedule</a>
        <a href="/crew">Crew</a>
        <a href="/health">Health</a>
        <a href="/logout">Logout</a>
    </div>
    """


@app.get("/")
async def login_page(request: Request):
    user = get_user(request)
    if user:
        if user["role"] == "crew":
            return RedirectResponse("/crew", status_code=303)
        return RedirectResponse("/dashboard", status_code=303)

    return page("Login", """
    <div class="card">
        <h1>PoolOps2</h1>
        <p>Heinlin Concrete LLC</p>
        <form method="post" action="/login">
            <label>Username</label>
            <input name="username" required>
            <label>Password</label>
            <input name="password" type="password" required>
            <button type="submit">Login</button>
        </form>
        <p>Admin: mike / 5500</p>
        <p>Crew: randy / 0318</p>
    </div>
    """)


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip().lower()
    password = password.strip()

    record = USERS.get(username)

    if not record or record["password"] != password:
        return page("Login Error", """
        <div class="card">
            <h1>Login Failed</h1>
            <p>Invalid username or password.</p>
            <a class="btn" href="/">Try Again</a>
        </div>
        """)

    request.session["username"] = username

    if record["role"] == "crew":
        return RedirectResponse("/crew", status_code=303)

    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "PoolOps2",
        "phase": "1",
    }


@app.get("/dashboard")
async def dashboard(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    total = len(JOBS)
    scheduled = len([j for j in JOBS if j["status"] == "Scheduled"])
    pending = len([j for j in JOBS if j["status"] == "Pending"])
    completed = len([j for j in JOBS if j["status"] == "Completed"])

    job_rows = "".join(
        f"""
        <div class="job">
            <h3>{job["client"]}</h3>
            <p>{job["address"]}</p>
            <p><span class="pill">{job["status"]}</span></p>
            <p>Type: {job["job_type"]}</p>
            <p>Crew: {job["crew"]}</p>
            <p>Date: {job["date"]}</p>
        </div>
        """
        for job in JOBS
    )

    return page("Dashboard", nav(user) + f"""
    <div class="card">
        <h2>Dashboard</h2>
        <p>Total Jobs: {total}</p>
        <p>Scheduled: {scheduled}</p>
        <p>Pending: {pending}</p>
        <p>Completed: {completed}</p>
    </div>
    <div class="card">
        <h2>Current Jobs</h2>
        {job_rows}
    </div>
    """)


@app.get("/jobs")
async def jobs_page(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    add_form = ""
    if user["role"] == "admin":
        add_form = """
        <div class="card">
            <h2>Add Job</h2>
            <form method="post" action="/jobs/add">
                <label>Client</label>
                <input name="client" required>

                <label>Address</label>
                <input name="address" required>

                <label>Job Type</label>
                <select name="job_type" required>
                    <option>Concrete Pool</option>
                    <option>Pool Remodel</option>
                    <option>Auto Cover</option>
                    <option>Tile / Coping</option>
                    <option>EcoFinish</option>
                    <option>Service</option>
                </select>

                <label>Date</label>
                <input name="date" placeholder="Today / Tomorrow / Monday" required>

                <label>Crew</label>
                <select name="crew">
                    <option>Randy</option>
                    <option>Unassigned</option>
                </select>

                <label>Notes</label>
                <textarea name="notes"></textarea>

                <button type="submit">Create Job</button>
            </form>
        </div>
        """

    job_cards = "".join(
        f"""
        <div class="job">
            <h3>{job["client"]}</h3>
            <p>{job["address"]}</p>
            <p><span class="pill">{job["status"]}</span></p>
            <p>Type: {job["job_type"]}</p>
            <p>Crew: {job["crew"]}</p>
            <p>Date: {job["date"]}</p>
            <p>{job["notes"]}</p>
        </div>
        """
        for job in JOBS
    )

    return page("Jobs", nav(user) + add_form + f"""
    <div class="card">
        <h2>Jobs</h2>
        {job_cards}
    </div>
    """)


@app.post("/jobs/add")
async def add_job(
    request: Request,
    client: str = Form(...),
    address: str = Form(...),
    job_type: str = Form(...),
    date: str = Form(...),
    crew: str = Form("Unassigned"),
    notes: str = Form(""),
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    if user["role"] != "admin":
        return RedirectResponse("/crew", status_code=303)

    next_id = max([job["id"] for job in JOBS], default=0) + 1

    JOBS.append({
        "id": next_id,
        "client": client.strip(),
        "address": address.strip(),
        "job_type": job_type.strip(),
        "status": "Scheduled",
        "crew": crew.strip(),
        "date": date.strip(),
        "notes": notes.strip(),
    })

    return RedirectResponse("/jobs", status_code=303)


@app.get("/schedule")
async def schedule(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    job_cards = "".join(
        f"""
        <div class="job">
            <h3>{job["date"]}: {job["client"]}</h3>
            <p>{job["address"]}</p>
            <p>{job["job_type"]} / {job["crew"]}</p>
            <p><span class="pill">{job["status"]}</span></p>
        </div>
        """
        for job in JOBS
    )

    return page("Schedule", nav(user) + f"""
    <div class="card">
        <h2>Schedule</h2>
        {job_cards}
    </div>
    """)


@app.get("/crew")
async def crew(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    clock = TIME_CLOCK.get(user["username"], {"clocked_in": False, "current_job": None})

    clock_text = "CLOCKED IN" if clock["clocked_in"] else "CLOCKED OUT"
    clock_button = """
        <form method="post" action="/crew/clock-out">
            <button class="danger">Clock Out</button>
        </form>
    """ if clock["clocked_in"] else """
        <form method="post" action="/crew/clock-in">
            <button>Clock In</button>
        </form>
    """

    crew_jobs = [
        job for job in JOBS
        if job["crew"].lower() in [user["name"].lower(), user["username"].lower()]
        or job["crew"].lower() == "unassigned"
    ]

    job_cards = "".join(
        f"""
        <div class="job">
            <h3>{job["client"]}</h3>
            <p>{job["address"]}</p>
            <p>{job["job_type"]} / {job["date"]}</p>
            <p><span class="pill">{job["status"]}</span></p>

            <form method="post" action="/crew/start-job/{job["id"]}">
                <button>Start Job</button>
            </form>

            <form method="post" action="/crew/complete-job/{job["id"]}">
                <button class="success">Complete Job</button>
            </form>
        </div>
        """
        for job in crew_jobs
    )

    return page("Crew", nav(user) + f"""
    <div class="card">
        <h2>My Day</h2>
        <h3>{clock_text}</h3>
        <p>Active Job: {clock["current_job"]}</p>
        {clock_button}
    </div>

    <div class="card">
        <h2>Crew Jobs</h2>
        {job_cards}
    </div>
    """)


@app.post("/crew/clock-in")
async def clock_in(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    TIME_CLOCK[user["username"]] = {"clocked_in": True, "current_job": None}

    return RedirectResponse("/crew", status_code=303)


@app.post("/crew/clock-out")
async def clock_out(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    TIME_CLOCK[user["username"]] = {"clocked_in": False, "current_job": None}

    return RedirectResponse("/crew", status_code=303)


@app.post("/crew/start-job/{job_id}")
async def start_job(request: Request, job_id: int):
    user = get_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    for job in JOBS:
        if job["id"] == job_id:
            job["status"] = "In Progress"
            TIME_CLOCK[user["username"]] = {
                "clocked_in": True,
                "current_job": job_id,
            }
            break

    return RedirectResponse("/crew", status_code=303)


@app.post("/crew/complete-job/{job_id}")
async def complete_job(request: Request, job_id: int):
    user = get_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    for job in JOBS:
        if job["id"] == job_id:
            job["status"] = "Completed"
            if TIME_CLOCK.get(user["username"], {}).get("current_job") == job_id:
                TIME_CLOCK[user["username"]]["current_job"] = None
            break

    return RedirectResponse("/crew", status_code=303)