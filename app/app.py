from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="PoolOps2")

app.add_middleware(SessionMiddleware, secret_key="poolops2-phase1-secret")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


USERS = {
    "mike": {"password": "5500", "role": "admin", "name": "Mike"},
    "randy": {"password": "0318", "role": "crew", "name": "Randy"},
}


JOBS = [
    {
        "id": 1,
        "client": "Sample Client",
        "address": "123 Poolside Drive",
        "job_type": "Pool Remodel",
        "status": "Scheduled",
        "crew": "Randy",
        "date": "Today",
        "notes": "Phase 1 demo job.",
    },
    {
        "id": 2,
        "client": "Heinlin Test Pool",
        "address": "456 Concrete Lane",
        "job_type": "Service / Layout",
        "status": "Pending",
        "crew": "Unassigned",
        "date": "Tomorrow",
        "notes": "Use this to test schedule and dashboard pages.",
    },
]


TIME_CLOCK = {
    "randy": {"clocked_in": False, "current_job": None}
}


def current_user(request: Request):
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
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)
    return user


@app.get("/")
def login_page(request: Request):
    user = current_user(request)
    if user:
        if user["role"] == "crew":
            return RedirectResponse("/crew", status_code=303)
        return RedirectResponse("/dashboard", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    username = username.strip().lower()
    user = USERS.get(username)

    if not user or user["password"] != password.strip():
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password."},
            status_code=401,
        )

    request.session["username"] = username

    if user["role"] == "crew":
        return RedirectResponse("/crew", status_code=303)

    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "PoolOps2",
        "phase": "1",
    }


@app.get("/dashboard")
def dashboard(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    if user["role"] != "admin":
        return RedirectResponse("/crew", status_code=303)

    stats = {
        "total_jobs": len(JOBS),
        "scheduled": len([j for j in JOBS if j["status"] == "Scheduled"]),
        "pending": len([j for j in JOBS if j["status"] == "Pending"]),
        "completed": len([j for j in JOBS if j["status"] == "Completed"]),
    }

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "jobs": JOBS,
            "stats": stats,
        },
    )


@app.get("/jobs")
def jobs_page(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    return templates.TemplateResponse(
        "jobs.html",
        {
            "request": request,
            "user": user,
            "jobs": JOBS,
        },
    )


@app.post("/jobs/add")
def add_job(
    request: Request,
    client: str = Form(...),
    address: str = Form(...),
    job_type: str = Form(...),
    date: str = Form(...),
    crew: str = Form("Unassigned"),
    notes: str = Form(""),
):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    if user["role"] != "admin":
        return RedirectResponse("/crew", status_code=303)

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

    return RedirectResponse("/jobs", status_code=303)


@app.get("/schedule")
def schedule_page(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "user": user,
            "jobs": JOBS,
        },
    )


@app.get("/crew")
def crew_page(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    crew_jobs = [
        job for job in JOBS
        if job["crew"].lower() in [user["name"].lower(), user["username"].lower()]
        or job["crew"].lower() == "unassigned"
    ]

    clock_state = TIME_CLOCK.get(
        user["username"],
        {"clocked_in": False, "current_job": None},
    )

    return templates.TemplateResponse(
        "crew.html",
        {
            "request": request,
            "user": user,
            "jobs": crew_jobs,
            "clock": clock_state,
        },
    )


@app.post("/crew/clock-in")
def clock_in(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    TIME_CLOCK[user["username"]] = {
        "clocked_in": True,
        "current_job": TIME_CLOCK.get(user["username"], {}).get("current_job"),
    }

    return RedirectResponse("/crew", status_code=303)


@app.post("/crew/clock-out")
def clock_out(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    TIME_CLOCK[user["username"]] = {
        "clocked_in": False,
        "current_job": None,
    }

    return RedirectResponse("/crew", status_code=303)


@app.post("/crew/start-job/{job_id}")
def start_job(request: Request, job_id: int):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

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
def complete_job(request: Request, job_id: int):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    for job in JOBS:
        if job["id"] == job_id:
            job["status"] = "Completed"
            if TIME_CLOCK.get(user["username"], {}).get("current_job") == job_id:
                TIME_CLOCK[user["username"]]["current_job"] = None
            break

    return RedirectResponse("/crew", status_code=303)