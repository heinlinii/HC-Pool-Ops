from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="PoolOps2")

app.add_middleware(
    SessionMiddleware,
    secret_key="poolops2-phase1-secret",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


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
    user = get_current_user(request)

    if not user:
        return None

    return user


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
        "phase": "1",
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
        "completed": len([job for job in JOBS if job["status"] == "Completed"]),
    }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "jobs": JOBS,
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
    notes: str = Form(""),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    if user["role"] != "admin":
        return RedirectResponse(url="/crew", status_code=303)

    next_id = max([job["id"] for job in JOBS], default=0) + 1

    JOBS.append(
        {
            "id": next_id,
            "client": client.strip(),
            "address": address.strip(),
            "job_type": job_type.strip(),
            "status": "Scheduled",
            "crew": crew.strip() or "Unassigned",
            "date": date.strip(),
            "notes": notes.strip(),
        }
    )

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

    for job in JOBS:
        if job["id"] == job_id:
            job["status"] = "In Progress"

            TIME_CLOCK[user["username"]] = {
                "clocked_in": True,
                "current_job": job_id,
            }

            break

    return RedirectResponse(url="/crew", status_code=303)


@app.post("/crew/complete-job/{job_id}")
async def complete_job(
    request: Request,
    job_id: int,
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    for job in JOBS:
        if job["id"] == job_id:
            job["status"] = "Completed"

            if TIME_CLOCK.get(user["username"], {}).get("current_job") == job_id:
                TIME_CLOCK[user["username"]]["current_job"] = None

            break

    return RedirectResponse(url="/crew", status_code=303)