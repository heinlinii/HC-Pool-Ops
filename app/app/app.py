import os

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware


app = FastAPI(title="PoolOps Pro")


# REQUIRED FOR request.session
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "poolops-dev-secret-key"),
    same_site="lax",
    https_only=False,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "templates"))
STATIC_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "static"))

templates = Jinja2Templates(directory=TEMPLATES_DIR)

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


USERS = {
    "mike": {"password": "1234", "role": "admin", "name": "Mike"},
    "jake": {"password": "1234", "role": "crew", "name": "Jake"},
    "smith": {"password": "1234", "role": "client", "name": "Smith"},
}


def get_current_user(request: Request):
    username = request.session.get("username")
    if not username:
        return None

    user = USERS.get(username)
    if not user:
        request.session.clear()
        return None

    return {
        "username": username,
        "name": user["name"],
        "role": user["role"],
    }


def require_login(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)
    return user


@app.get("/health")
def health():
    return {"status": "ok", "app": "PoolOps Pro"}


@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/dashboard", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
        },
    )


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return login_page(request)


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    username_clean = username.strip().lower()
    password_clean = password.strip()

    user = USERS.get(username_clean)

    if not user or user["password"] != password_clean:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid username or password.",
            },
            status_code=401,
        )

    request.session.clear()
    request.session["username"] = username_clean
    request.session["role"] = user["role"]

    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "role": user["role"],
        },
    )


@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    jobs_data = [
        {
            "id": 1,
            "customer": "Smith",
            "job_name": "Pool Service",
            "status": "Scheduled",
            "billing_status": "Unbilled",
            "amount": 450,
        },
        {
            "id": 2,
            "customer": "Johnson",
            "job_name": "Cover Repair",
            "status": "Completed",
            "billing_status": "Ready to Bill",
            "amount": 1200,
        },
    ]

    return templates.TemplateResponse(
        "jobs.html",
        {
            "request": request,
            "user": user,
            "role": user["role"],
            "jobs": jobs_data,
        },
    )


@app.get("/my-day", response_class=HTMLResponse)
def my_day(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user

    return templates.TemplateResponse(
        "jobs.html",
        {
            "request": request,
            "user": user,
            "role": user["role"],
            "jobs": [],
        },
    )