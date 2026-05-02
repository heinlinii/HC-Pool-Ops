from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="PoolOps2")

app.add_middleware(
    SessionMiddleware,
    secret_key="poolops2-phase-15-secret",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


USERS = {
    "mike": {"password": "5500", "role": "admin", "name": "Mike"},
    "randy": {"password": "0318", "role": "crew", "name": "Randy"},
}


EMPLOYEES = [
    {
        "id": 1,
        "name": "Mike",
        "role": "Admin",
        "phone": "",
        "email": "",
        "active": True,
    },
    {
        "id": 2,
        "name": "Randy",
        "role": "Crew",
        "phone": "",
        "email": "",
        "active": True,
    },
]


CLIENTS = [
    {
        "id": 1,
        "name": "Smith Residence",
        "phone": "",
        "email": "",
        "notes": "Sample client.",
    },
    {
        "id": 2,
        "name": "Johnson Backyard",
        "phone": "",
        "email": "",
        "notes": "Sample remodel client.",
    },
]


PROPERTIES = [
    {
        "id": 1,
        "client_id": 1,
        "client": "Smith Residence",
        "address": "Evansville, IN",
        "pool_type": "Concrete Pool",
        "notes": "20x40 rectangle pool.",
    },
    {
        "id": 2,
        "client_id": 2,
        "client": "Johnson Backyard",
        "address": "Newburgh, IN",
        "pool_type": "Pool Remodel",
        "notes": "Tile and coping replacement.",
    },
]


JOBS = [
    {
        "id": 1,
        "client": "Smith Residence",
        "property": "Evansville, IN",
        "address": "Evansville, IN",
        "job_type": "Concrete Pool",
        "status": "Scheduled",
        "crew": "Randy",
        "date": "Today",
        "priority": "Normal",
        "notes": "20x40 rectangle pool.",
    },
    {
        "id": 2,
        "client": "Johnson Backyard",
        "property": "Newburgh, IN",
        "address": "Newburgh, IN",
        "job_type": "Pool Remodel",
        "status": "Pending",
        "crew": "Unassigned",
        "date": "Tomorrow",
        "priority": "High",
        "notes": "Tile and coping replacement.",
    },
]


TIME_CLOCK = {
    "randy": {"clocked_in": False, "current_job": None}
}


def get_current_user(request: Request):
    username = request.session.get("username")

    if not username:
        return None

    user = USERS.get(username)

    if not user:
        return None

    return {
        "username": username,
        "name": user["name"],
        "role": user["role"],
    }


def require_login(request: Request):
    return get_current_user(request)


def require_admin(request: Request):
    user = get_current_user(request)

    if not user:
        return None

    if user["role"] != "admin":
        return None

    return user


def next_id(items):
    return max([item["id"] for item in items], default=0) + 1


def find_by_id(items, item_id: int):
    for item in items:
        if item["id"] == item_id:
            return item
    return None


@app.get("/")
async def login_page(request: Request):
    user = get_current_user(request)

    if user:
        if user["role"] == "crew":
            return RedirectResponse(url="/crew", status_code=303)

        return RedirectResponse(url="/dashboard", status_code=303)

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
        },
    )


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    username = username.lower().strip()
    password = password.strip()

    user = USERS.get(username)

    if not user or user["password"] != password:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Invalid username or password.",
            },
            status_code=401,
        )

    request.session["username"] = username

    if user["role"] == "crew":
        return RedirectResponse(url="/crew", status_code=303)

    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "PoolOps2",
        "phase": "1.5",
    }


@app.get("/dashboard")
async def dashboard(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    if user["role"] != "admin":
        return RedirectResponse(url="/crew", status_code=303)

    stats = {
        "total_jobs": len(JOBS),
        "scheduled": len([job for job in JOBS if job["status"] == "Scheduled"]),
        "pending": len([job for job in JOBS if job["status"] == "Pending"]),
        "in_progress": len([job for job in JOBS if job["status"] == "In Progress"]),
        "completed": len([job for job in JOBS if job["status"] == "Completed"]),
        "clients": len(CLIENTS),
        "properties": len(PROPERTIES),
        "employees": len(EMPLOYEES),
    }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "jobs": JOBS,
            "clients": CLIENTS,
            "properties": PROPERTIES,
            "employees": EMPLOYEES,
            "stats": stats,
        },
    )


@app.get("/jobs")
async def jobs_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "user": user,
            "jobs": JOBS,
            "clients": CLIENTS,
            "properties": PROPERTIES,
            "employees": EMPLOYEES,
        },
    )


@app.post("/jobs/add")
async def add_job(
    request: Request,
    client: str = Form(...),
    address: str = Form(...),
    job_type: str = Form(...),
    date: str = Form(...),
    crew: str = Form("Unassigned"),
    status: str = Form("Scheduled"),
    priority: str = Form("Normal"),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    clean_address = address.strip()

    JOBS.append(
        {
            "id": next_id(JOBS),
            "client": client.strip(),
            "property": clean_address,
            "address": clean_address,
            "job_type": job_type.strip(),
            "status": status.strip(),
            "crew": crew.strip() or "Unassigned",
            "date": date.strip(),
            "priority": priority.strip(),
            "notes": notes.strip(),
        }
    )

    return RedirectResponse(url="/jobs", status_code=303)


@app.post("/jobs/update/{job_id}")
async def update_job(
    request: Request,
    job_id: int,
    client: str = Form(...),
    address: str = Form(...),
    job_type: str = Form(...),
    date: str = Form(...),
    crew: str = Form(...),
    status: str = Form(...),
    priority: str = Form(...),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    job = find_by_id(JOBS, job_id)

    if job:
        job["client"] = client.strip()
        job["property"] = address.strip()
        job["address"] = address.strip()
        job["job_type"] = job_type.strip()
        job["date"] = date.strip()
        job["crew"] = crew.strip()
        job["status"] = status.strip()
        job["priority"] = priority.strip()
        job["notes"] = notes.strip()

    return RedirectResponse(url="/jobs", status_code=303)


@app.post("/jobs/delete/{job_id}")
async def delete_job(request: Request, job_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    global JOBS
    JOBS = [job for job in JOBS if job["id"] != job_id]

    return RedirectResponse(url="/jobs", status_code=303)


@app.get("/schedule")
async def schedule_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "schedule.html",
        {
            "user": user,
            "jobs": JOBS,
        },
    )


@app.post("/schedule/status/{job_id}")
async def update_schedule_status(
    request: Request,
    job_id: int,
    status: str = Form(...),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    job = find_by_id(JOBS, job_id)

    if job:
        job["status"] = status.strip()

    return RedirectResponse(url="/schedule", status_code=303)


@app.get("/crew")
async def crew_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    crew_jobs = [
        job
        for job in JOBS
        if job["crew"].lower() in [user["name"].lower(), user["username"].lower()]
        or job["crew"].lower() == "unassigned"
        or user["role"] == "admin"
    ]

    clock = TIME_CLOCK.get(
        user["username"],
        {
            "clocked_in": False,
            "current_job": None,
        },
    )

    return templates.TemplateResponse(
        request,
        "crew.html",
        {
            "user": user,
            "jobs": crew_jobs,
            "clock": clock,
        },
    )


@app.post("/crew/clock-in")
async def clock_in(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    old_clock = TIME_CLOCK.get(
        user["username"],
        {
            "clocked_in": False,
            "current_job": None,
        },
    )

    TIME_CLOCK[user["username"]] = {
        "clocked_in": True,
        "current_job": old_clock.get("current_job"),
    }

    return RedirectResponse(url="/crew", status_code=303)


@app.post("/crew/clock-out")
async def clock_out(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    TIME_CLOCK[user["username"]] = {
        "clocked_in": False,
        "current_job": None,
    }

    return RedirectResponse(url="/crew", status_code=303)


@app.post("/crew/start-job/{job_id}")
async def start_job(
    request: Request,
    job_id: int,
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    job = find_by_id(JOBS, job_id)

    if job:
        job["status"] = "In Progress"

        TIME_CLOCK[user["username"]] = {
            "clocked_in": True,
            "current_job": job_id,
        }

    return RedirectResponse(url="/crew", status_code=303)


@app.post("/crew/complete-job/{job_id}")
async def complete_job(
    request: Request,
    job_id: int,
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    job = find_by_id(JOBS, job_id)

    if job:
        job["status"] = "Completed"

        if TIME_CLOCK.get(user["username"], {}).get("current_job") == job_id:
            TIME_CLOCK[user["username"]]["current_job"] = None

    return RedirectResponse(url="/crew", status_code=303)


@app.get("/clients")
async def clients_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "clients.html",
        {
            "user": user,
            "clients": CLIENTS,
        },
    )


@app.post("/clients/add")
async def add_client(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    CLIENTS.append(
        {
            "id": next_id(CLIENTS),
            "name": name.strip(),
            "phone": phone.strip(),
            "email": email.strip(),
            "notes": notes.strip(),
        }
    )

    return RedirectResponse(url="/clients", status_code=303)


@app.post("/clients/update/{client_id}")
async def update_client(
    request: Request,
    client_id: int,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    client = find_by_id(CLIENTS, client_id)

    if client:
        old_name = client["name"]
        client["name"] = name.strip()
        client["phone"] = phone.strip()
        client["email"] = email.strip()
        client["notes"] = notes.strip()

        for prop in PROPERTIES:
            if prop["client"] == old_name:
                prop["client"] = client["name"]

        for job in JOBS:
            if job["client"] == old_name:
                job["client"] = client["name"]

    return RedirectResponse(url="/clients", status_code=303)


@app.post("/clients/delete/{client_id}")
async def delete_client(request: Request, client_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    global CLIENTS
    CLIENTS = [client for client in CLIENTS if client["id"] != client_id]

    return RedirectResponse(url="/clients", status_code=303)


@app.get("/properties")
async def properties_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "properties.html",
        {
            "user": user,
            "clients": CLIENTS,
            "properties": PROPERTIES,
        },
    )


@app.post("/properties/add")
async def add_property(
    request: Request,
    client: str = Form(...),
    address: str = Form(...),
    pool_type: str = Form(""),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    selected_client = None

    for c in CLIENTS:
        if c["name"] == client:
            selected_client = c
            break

    PROPERTIES.append(
        {
            "id": next_id(PROPERTIES),
            "client_id": selected_client["id"] if selected_client else None,
            "client": client.strip(),
            "address": address.strip(),
            "pool_type": pool_type.strip(),
            "notes": notes.strip(),
        }
    )

    return RedirectResponse(url="/properties", status_code=303)


@app.post("/properties/update/{property_id}")
async def update_property(
    request: Request,
    property_id: int,
    client: str = Form(...),
    address: str = Form(...),
    pool_type: str = Form(""),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    prop = find_by_id(PROPERTIES, property_id)

    if prop:
        old_address = prop["address"]

        selected_client = None
        for c in CLIENTS:
            if c["name"] == client:
                selected_client = c
                break

        prop["client_id"] = selected_client["id"] if selected_client else None
        prop["client"] = client.strip()
        prop["address"] = address.strip()
        prop["pool_type"] = pool_type.strip()
        prop["notes"] = notes.strip()

        for job in JOBS:
            if job["address"] == old_address:
                job["property"] = prop["address"]
                job["address"] = prop["address"]
                job["client"] = prop["client"]

    return RedirectResponse(url="/properties", status_code=303)


@app.post("/properties/delete/{property_id}")
async def delete_property(request: Request, property_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    global PROPERTIES
    PROPERTIES = [prop for prop in PROPERTIES if prop["id"] != property_id]

    return RedirectResponse(url="/properties", status_code=303)


@app.get("/employees")
async def employees_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "employees.html",
        {
            "user": user,
            "employees": EMPLOYEES,
        },
    )


@app.post("/employees/add")
async def add_employee(
    request: Request,
    name: str = Form(...),
    role: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    active: str = Form("true"),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    EMPLOYEES.append(
        {
            "id": next_id(EMPLOYEES),
            "name": name.strip(),
            "role": role.strip(),
            "phone": phone.strip(),
            "email": email.strip(),
            "active": active == "true",
        }
    )

    return RedirectResponse(url="/employees", status_code=303)


@app.post("/employees/update/{employee_id}")
async def update_employee(
    request: Request,
    employee_id: int,
    name: str = Form(...),
    role: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    active: str = Form("true"),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    employee = find_by_id(EMPLOYEES, employee_id)

    if employee:
        old_name = employee["name"]

        employee["name"] = name.strip()
        employee["role"] = role.strip()
        employee["phone"] = phone.strip()
        employee["email"] = email.strip()
        employee["active"] = active == "true"

        for job in JOBS:
            if job["crew"] == old_name:
                job["crew"] = employee["name"]

    return RedirectResponse(url="/employees", status_code=303)


@app.post("/employees/delete/{employee_id}")
async def delete_employee(request: Request, employee_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    global EMPLOYEES
    EMPLOYEES = [employee for employee in EMPLOYEES if employee["id"] != employee_id]

    return RedirectResponse(url="/employees", status_code=303)