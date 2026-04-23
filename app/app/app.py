import os
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # .../app/app
PROJECT_ROOT = os.path.dirname(BASE_DIR)                # .../app

app = FastAPI(title="HC Pool Ops")

app.add_middleware(
    SessionMiddleware,
    secret_key="super-secret-key-change-me",
)

app.mount("/static", StaticFiles(directory=os.path.join(PROJECT_ROOT, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(PROJECT_ROOT, "templates"))

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


def property_name(property_id: int) -> str:
    for prop in DATA["properties"]:
        if prop["id"] == property_id:
            return prop["name"]
    return f"Property #{property_id}"


def client_name(client_id: int) -> str:
    for client in DATA["clients"]:
        if client["id"] == client_id:
            return client["name"]
    return f"Client #{client_id}"


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if get_user(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
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
        "login.html",
        {
            "request": request,
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

    recent_jobs = []
    for job in DATA["jobs"]:
        recent_jobs.append(
            {
                **job,
                "property_name": property_name(job["property_id"]),
            }
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Dashboard",
            "user": get_user(request),
            "client_count": len(DATA["clients"]),
            "property_count": len(DATA["properties"]),
            "job_count": len(DATA["jobs"]),
            "recent_jobs": recent_jobs,
        },
    )


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    auth = require_login(request)
    if auth:
        return auth

    return templates.TemplateResponse(
        "clients.html",
        {
            "request": request,
            "title": "Clients",
            "user": get_user(request),
            "clients": DATA["clients"],
            "error": None,
        },
    )


@app.post("/clients", response_class=HTMLResponse)
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

    enriched_properties = []
    for prop in DATA["properties"]:
        enriched_properties.append(
            {
                **prop,
                "client_name": client_name(prop["client_id"]),
            }
        )

    return templates.TemplateResponse(
        "properties.html",
        {
            "request": request,
            "title": "Properties",
            "user": get_user(request),
            "properties": enriched_properties,
            "clients": DATA["clients"],
            "error": None,
        },
    )


@app.post("/properties", response_class=HTMLResponse)
def add_property(
    request: Request,
    client_id: int = Form(...),
    name: str = Form(...),
    address: str = Form(""),
    city: str = Form(""),
):
    auth = require_login(request)
    if auth:
        return auth

    DATA["properties"].append(
        {
            "id": COUNTERS["properties"],
            "client_id": client_id,
            "name": name.strip(),
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

    enriched_jobs = []
    for job in DATA["jobs"]:
        enriched_jobs.append(
            {
                **job,
                "property_name": property_name(job["property_id"]),
            }
        )

    return templates.TemplateResponse(
        "jobs.html",
        {
            "request": request,
            "title": "Jobs",
            "user": get_user(request),
            "jobs": enriched_jobs,
            "properties": DATA["properties"],
            "error": None,
        },
    )


@app.post("/jobs", response_class=HTMLResponse)
def add_job(
    request: Request,
    property_id: int = Form(...),
    title: str = Form(...),
    status: str = Form("Scheduled"),
    scheduled_for: str = Form(""),
):
    auth = require_login(request)
    if auth:
        return auth

    DATA["jobs"].append(
        {
            "id": COUNTERS["jobs"],
            "property_id": property_id,
            "title": title.strip(),
            "status": status.strip() or "Scheduled",
            "scheduled_for": scheduled_for.strip(),
        }
    )
    COUNTERS["jobs"] += 1

    return RedirectResponse(url="/jobs", status_code=303)