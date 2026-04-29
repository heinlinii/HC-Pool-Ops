from pathlib import Path
from datetime import datetime, date
import os

from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware


# ---------- PATH SETUP ----------
BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


# ---------- APP INIT ----------
app = FastAPI(title="PoolOps Pro")

app.add_middleware(
    SessionMiddleware,
    secret_key="poolops-secret-key-change-later",
    same_site="lax",
)

# Static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------- USERS (TEMP LOGIN SYSTEM) ----------
USERS = {
    "mike": {"password": "1234", "role": "admin", "name": "Mike"},
    "jake": {"password": "1234", "role": "crew", "name": "Jake"},
    "smith": {"password": "1234", "role": "client", "name": "Smith"},
}


# ---------- AUTH HELPERS ----------
def get_user(request: Request):
    username = request.session.get("username")
    if not username:
        return None
    user = USERS.get(username)
    if not user:
        request.session.clear()
        return None
    return {"username": username, **user}


def require_login(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return user


def render(request: Request, template: str, data=None):
    context = data or {}
    context["request"] = request
    context["user"] = get_user(request)
    return templates.TemplateResponse(template, context)


# ---------- SAMPLE JOB DATA ----------
JOBS = [
    {
        "id": 1,
        "customer": "Smith",
        "job_name": "Weekly Service",
        "status": "Scheduled",
        "amount": 450,
        "billing": "Unbilled",
        "date": date.today().isoformat(),
    },
    {
        "id": 2,
        "customer": "Johnson",
        "job_name": "Cover Repair",
        "status": "Completed",
        "amount": 1200,
        "billing": "Ready",
        "date": date.today().isoformat(),
    },
]


def billing_summary(jobs):
    total = sum(j["amount"] for j in jobs)
    ready = sum(j["amount"] for j in jobs if j["billing"] == "Ready")
    unbilled = sum(j["amount"] for j in jobs if j["billing"] == "Unbilled")

    return {
        "total": total,
        "ready": ready,
        "unbilled": unbilled,
        "count": len(jobs),
    }


# ---------- ROUTES ----------
@app.get("/")
def home(request: Request):
    if get_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login")
def login_page(request: Request):
    return render(request, "login.html", {"error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.lower().strip()
    user = USERS.get(username)

    if not user or user["password"] != password:
        return render(request, "login.html", {"error": "Invalid login"})

    request.session["username"] = username
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

    summary = billing_summary(JOBS)

    return render(
        request,
        "dashboard.html",
        {
            "jobs": JOBS,
            "billing": summary,
        },
    )


@app.get("/jobs")
def jobs(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    return render(
        request,
        "jobs.html",
        {
            "jobs": JOBS,
            "billing": billing_summary(JOBS),
        },
    )


@app.get("/my-day")
def my_day(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    return render(
        request,
        "jobs.html",
        {
            "jobs": JOBS,
            "billing": billing_summary(JOBS),
        },
    )


@app.get("/health")
def health():
    return {"status": "ok", "app": "PoolOps Pro"}