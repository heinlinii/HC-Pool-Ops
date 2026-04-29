import os
from datetime import datetime, date
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="PoolOps Pro")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "poolops-change-this-secret"),
    same_site="lax",
    https_only=False,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


USERS = {
    "mike": {"password": "5500", "role": "admin", "name": "Mike"},
    "randy": {"password": "0318", "role": "crew", "name": "Randy"},
    "traylor": {"password": "8899", "role": "client", "name": "Traylor"},
}


JOBS = [
    {
        "id": 1,
        "client": "Smith",
        "property": "Smith Residence",
        "title": "Weekly Pool Service",
        "type": "Service",
        "status": "Scheduled",
        "crew": "Jake",
        "scheduled_date": date.today().isoformat(),
        "amount": 450.00,
        "billing_status": "Unbilled",
        "notes": "Check water, clean cover box, inspect equipment.",
    },
    {
        "id": 2,
        "client": "Johnson",
        "property": "Johnson Backyard Pool",
        "title": "Automatic Cover Repair",
        "type": "Repair",
        "status": "In Progress",
        "crew": "Jake",
        "scheduled_date": date.today().isoformat(),
        "amount": 1250.00,
        "billing_status": "Ready to Bill",
        "notes": "Inspect tracks, cover box, pulley, motor, and fabric alignment.",
    },
    {
        "id": 3,
        "client": "Miller",
        "property": "Miller New Build",
        "title": "Concrete Pool Layout",
        "type": "Construction",
        "status": "Scheduled",
        "crew": "Mike",
        "scheduled_date": date.today().isoformat(),
        "amount": 8500.00,
        "billing_status": "Deposit Needed",
        "notes": "Layout pool shell, elevations, cover box, plumbing routes.",
    },
]


TIME_CLOCK = {
    "jake": {"clocked_in": False, "last_action": None},
    "mike": {"clocked_in": False, "last_action": None},
}


def current_user(request: Request):
    user = request.session.get("user")
    if not user:
        return None
    return user


def require_user(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return user


def money(value):
    return f"${value:,.2f}"


def billing_summary():
    total = sum(job["amount"] for job in JOBS)
    ready = sum(job["amount"] for job in JOBS if job["billing_status"] == "Ready to Bill")
    unbilled = sum(job["amount"] for job in JOBS if job["billing_status"] == "Unbilled")
    deposits = sum(job["amount"] for job in JOBS if job["billing_status"] == "Deposit Needed")

    return {
        "total": money(total),
        "ready": money(ready),
        "unbilled": money(unbilled),
        "deposits": money(deposits),
        "job_count": len(JOBS),
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "PoolOps Pro",
        "time": datetime.now().isoformat(),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    username_clean = username.strip().lower()
    password_clean = password.strip()

    found = USERS.get(username_clean)

    if not found or found["password"] != password_clean:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid username or password.",
            },
            status_code=401,
        )

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
    if isinstance(user, RedirectResponse):
        return user

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "jobs": JOBS,
            "billing": billing_summary(),
            "time_clock": TIME_CLOCK.get(user["username"], {}),
        },
    )


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    return templates.TemplateResponse(
        "jobs.html",
        {
            "request": request,
            "user": user,
            "jobs": JOBS,
            "billing": billing_summary(),
        },
    )


@app.post("/jobs/{job_id}/start")
def start_job(request: Request, job_id: int):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    for job in JOBS:
        if job["id"] == job_id:
            job["status"] = "In Progress"
            job["crew"] = user["name"]
            break

    return RedirectResponse("/my-day", status_code=303)


@app.post("/jobs/{job_id}/complete")
def complete_job(request: Request, job_id: int):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    for job in JOBS:
        if job["id"] == job_id:
            job["status"] = "Completed"
            job["billing_status"] = "Ready to Bill"
            break

    return RedirectResponse("/my-day", status_code=303)


@app.get("/my-day", response_class=HTMLResponse)
def my_day(request: Request):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    username = user["username"]
    crew_jobs = [
        job for job in JOBS
        if job["crew"].lower() == user["name"].lower()
        or user["role"] == "admin"
    ]

    return templates.TemplateResponse(
        "my_day.html",
        {
            "request": request,
            "user": user,
            "jobs": crew_jobs,
            "clock": TIME_CLOCK.get(username, {"clocked_in": False, "last_action": None}),
        },
    )


@app.post("/clock-toggle")
def clock_toggle(request: Request):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    username = user["username"]
    if username not in TIME_CLOCK:
        TIME_CLOCK[username] = {"clocked_in": False, "last_action": None}

    TIME_CLOCK[username]["clocked_in"] = not TIME_CLOCK[username]["clocked_in"]
    TIME_CLOCK[username]["last_action"] = datetime.now().strftime("%m/%d/%Y %I:%M %p")

    return RedirectResponse("/my-day", status_code=303)


@app.get("/billing", response_class=HTMLResponse)
def billing_page(request: Request):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    return templates.TemplateResponse(
        "billing.html",
        {
            "request": request,
            "user": user,
            "jobs": JOBS,
            "billing": billing_summary(),
        },
    )