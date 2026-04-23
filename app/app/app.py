import os
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))      # .../app/app
APP_ROOT = os.path.dirname(BASE_DIR)                       # .../app

app = FastAPI(title="HC Pool Ops")

app.add_middleware(
    SessionMiddleware,
    secret_key="super-secret-key-change-me",
)

app.mount("/static", StaticFiles(directory=os.path.join(APP_ROOT, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))

USERS = {
    "mike": "1234",
    "jake": "1234",
}

DATA = {
    "clients": [],
    "properties": [],
    "jobs": [],
}

COUNTERS = {
    "clients": 1,
    "properties": 1,
    "jobs": 1,
}


def get_user(request: Request):
    return request.session.get("user")


def require_login(request: Request):
    if not get_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return None


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "title": "Login",
            "user": None,
            "error": None,
        },
    )


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username in USERS and USERS[username] == password:
        request.session["user"] = username
        return RedirectResponse(url="/dashboard", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "title": "Login",
            "user": None,
            "error": "Invalid username or password.",
        },
        status_code=400,
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    auth = require_login(request)
    if auth:
        return auth

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "title": "Dashboard",
            "user": get_user(request),
            "client_count": len(DATA["clients"]),
            "property_count": len(DATA["properties"]),
            "job_count": len(DATA["jobs"]),
            "recent_jobs": DATA["jobs"],
        },
    )


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    auth = require_login(request)
    if auth:
        return auth

    return templates.TemplateResponse(
        request=request,
        name="clients.html",
        context={
            "title": "Clients",
            "user": get_user(request),
            "error": None,
            "clients": DATA["clients"],
        },
    )


@app.post("/clients")
def add_client(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
):
    auth = require_login(request)
    if auth:
        return auth

    DATA["clients"].append(
        {
            "id": COUNTERS["clients"],
            "name": name.strip(),
            "phone": phone.strip(),
            "email": email.strip(),
        }
    )
    COUNTERS["clients"] += 1

    return RedirectResponse(url="/clients", status_code=303)


@app.get("/properties", response_class=HTMLResponse)
def properties_page(request: Request):
    auth = require_login(request)
    if auth:
        return auth

    return templates.TemplateResponse(
        request=request,
        name="properties.html",
        context={
            "title": "Properties",
            "user": get_user(request),
            "error": None,
            "clients": DATA["clients"],
            "properties": DATA["properties"],
        },
    )


@app.post("/properties")
def add_property(
    request: Request,
    name: str = Form(...),
    client_id: int = Form(...),
    address: str = Form(""),
    city: str = Form(""),
):
    auth = require_login(request)
    if auth:
        return auth

    DATA["properties"].append(
        {
            "id": COUNTERS["properties"],
            "name": name.strip(),
            "client_id": client_id,
            "address": address.strip(),
            "city": city.strip(),
        }
    )
    COUNTERS["properties"] += 1

    return RedirectResponse(url="/properties", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    auth = require_login(request)
    if auth:
        return auth

    return templates.TemplateResponse(
        request=request,
        name="jobs.html",
        context={
            "title": "Jobs",
            "user": get_user(request),
            "error": None,
            "properties": DATA["properties"],
            "jobs": DATA["jobs"],
        },
    )


@app.post("/jobs")
def add_job(
    request: Request,
    title: str = Form(...),
    property_id: int = Form(...),
):
    auth = require_login(request)
    if auth:
        return auth

    DATA["jobs"].append(
        {
            "id": COUNTERS["jobs"],
            "title": title.strip(),
            "property_id": property_id,
        }
    )
    COUNTERS["jobs"] += 1

    return RedirectResponse(url="/jobs", status_code=303)