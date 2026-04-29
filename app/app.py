from pathlib import Path
from datetime import datetime, date
import os

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="PoolOps Pro")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "change-this-poolops-secret"),
    same_site="lax",
    https_only=False,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


USERS = {
    "mike": {"password": "1234", "role": "admin", "name": "Mike"},
    "jake": {"password": "1234", "role": "crew", "name": "Jake"},
    "smith": {"password": "1234", "role": "client", "name": "Smith"},
}


def current_user(request: Request):
    username = request.session.get("username")
    if not username:
        return None
    user = USERS.get(username)
    if not user:
        request.session.clear()
        return None
    return {"username": username, **user}


def require_login(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return user


def render(request: Request, template_name: str, context: dict | None = None):
    ctx = context or {}
    ctx["request"] = request
    ctx["user"] = current_user(request)
    return templates.TemplateResponse(template_name, ctx)


SAMPLE_JOBS = [
    {
        "id": 1,
        "customer": "Smith",
        "property": "Main Pool",
        "job_name": "Pool Service",
        "status": "Scheduled",
        "amount": 450.00,
        "billing_status": "Unbilled",
        "date": date.today().isoformat(),
    },
    {
        "id": 2,
        "customer": "Johnson",
        "property": "Backyard Pool",
        "job_name": "Cover Repair",
        "status": "Completed",
        "amount": 1250.00,
        "billing_status": "Ready to Bill",
        "date": date.today().isoformat(),
    },
]


def billing_summary(jobs):
    total = sum(float(j.get("amount") or 0) for j in jobs)
    ready = sum(float(j.get("amount") or 0) for j in jobs if j.get("billing_status") == "Ready to Bill")
    unbilled = sum(float(j.get("amount") or 0) for j in jobs if j.get("billing_status") == "Unbilled")
    return {
        "total_jobs": len(jobs),
        "total_amount": total,
        "ready_to_bill": ready,
        "unbilled": unbilled,
        "generated_at": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
    }


@app.get("/")
def home(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login")
def login_page(request: Request):
    return render(request, "login.html", {"error": None})


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    username_clean = username.strip().lower()
    user = USERS.get(username_clean)

    if not user or user["password"] != password.strip():
        return render(
            request,
            "login.html",
            {"error": "Invalid username or password."},
        )

    request.session.clear()
    request.session["username"] = username_clean
    request.session["role"] = user["role"]

    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/dashboard")
def dashboard(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    jobs = SAMPLE_JOBS
    summary = billing_summary(jobs)

    return render(
        request,
        "dashboard.html",
        {
            "title": "Dashboard",
            "jobs": jobs,
            "billing": summary,
            "stats": summary,
            "role": user["role"],
        },
    )


@app.get("/jobs")
def jobs_page(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    jobs = SAMPLE_JOBS
    summary = billing_summary(jobs)

    return render(
        request,
        "jobs.html",
        {
            "title": "Jobs",
            "jobs": jobs,
            "billing": summary,
            "stats": summary,
            "role": user["role"],
        },
    )


@app.post("/jobs/{job_id}/mark-ready")
def mark_job_ready(request: Request, job_id: int):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/{job_id}/complete")
def complete_job(request: Request, job_id: int):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    return RedirectResponse("/jobs", status_code=303)


@app.get("/my-day")
def my_day(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    return render(
        request,
        "jobs.html",
        {
            "title": "My Day",
            "jobs": SAMPLE_JOBS,
            "billing": billing_summary(SAMPLE_JOBS),
            "stats": billing_summary(SAMPLE_JOBS),
            "role": user["role"],
        },
    )


@app.get("/health")
def health():
    return {"status": "ok", "app": "PoolOps Pro"}