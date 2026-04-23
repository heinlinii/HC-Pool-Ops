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


def get_client_name(client_id: int) -> str:
    for client in DATA["clients"]:
        if client["id"] == client_id:
            return client["name"]
    return "Unknown Client"


def get_property_name(property_id: int) -> str:
    for prop in DATA["properties"]:
        if prop["id"] == property_id:
            return prop["name"]
    return "Unknown Property"


def build_properties_with_client_names():
    items = []
    for prop in DATA["properties"]:
        items.append(
            {
                **prop,
                "client_name": get_client_name(prop["client_id"]),
            }
        )
    return items


def build_jobs_with_property_names():
    items = []
    for job in DATA["jobs"]:
        items.append(
            {
                **job,
                "property_name": get_property_name(job["property_id"]),
            }
        )
    return items


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_user(request):
        return RedirectResponse(url="/dashboard", status_code=303)

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

    recent_jobs = build_jobs_with_property_names()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
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

    clean_name = name.strip()
    clean_phone = phone.strip()
    clean_email = email.strip()

    if not clean_name:
        return templates.TemplateResponse(
            request=request,
            name="clients.html",
            context={
                "title": "Clients",
                "user": get_user(request),
                "error": "Client name is required.",
                "clients": DATA["clients"],
            },
            status_code=400,
        )

    DATA["clients"].append(
        {
            "id": COUNTERS["clients"],
            "name": clean_name,
            "phone": clean_phone,
            "email": clean_email,
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
            "properties": build_properties_with_client_names(),
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

    if len(DATA["clients"]) == 0:
        return templates.TemplateResponse(
            request=request,
            name="properties.html",
            context={
                "title": "Properties",
                "user": get_user(request),
                "error": "Add a client before adding a property.",
                "clients": DATA["clients"],
                "properties": build_properties_with_client_names(),
            },
            status_code=400,
        )

    valid_client_ids = [client["id"] for client in DATA["clients"]]
    if client_id not in valid_client_ids:
        return templates.TemplateResponse(
            request=request,
            name="properties.html",
            context={
                "title": "Properties",
                "user": get_user(request),
                "error": "Please choose a valid client.",
                "clients": DATA["clients"],
                "properties": build_properties_with_client_names(),
            },
            status_code=400,
        )

    clean_name = name.strip()
    clean_address = address.strip()
    clean_city = city.strip()

    if not clean_name:
        return templates.TemplateResponse(
            request=request,
            name="properties.html",
            context={
                "title": "Properties",
                "user": get_user(request),
                "error": "Property name is required.",
                "clients": DATA["clients"],
                "properties": build_properties_with_client_names(),
            },
            status_code=400,
        )

    DATA["properties"].append(
        {
            "id": COUNTERS["properties"],
            "name": clean_name,
            "client_id": client_id,
            "address": clean_address,
            "city": clean_city,
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
            "jobs": build_jobs_with_property_names(),
        },
    )


@app.post("/jobs")
def add_job(
    request: Request,
    title: str = Form(...),
    property_id: int = Form(...),
    status: str = Form(...),
    scheduled_for: str = Form(""),
):
    auth = require_login(request)
    if auth:
        return auth

    if len(DATA["properties"]) == 0:
        return templates.TemplateResponse(
            request=request,
            name="jobs.html",
            context={
                "title": "Jobs",
                "user": get_user(request),
                "error": "Add a property before adding a job.",
                "properties": DATA["properties"],
                "jobs": build_jobs_with_property_names(),
            },
            status_code=400,
        )

    valid_property_ids = [prop["id"] for prop in DATA["properties"]]
    valid_statuses = ["Scheduled", "In Progress", "Complete"]

    if property_id not in valid_property_ids:
        return templates.TemplateResponse(
            request=request,
            name="jobs.html",
            context={
                "title": "Jobs",
                "user": get_user(request),
                "error": "Please choose a valid property.",
                "properties": DATA["properties"],
                "jobs": build_jobs_with_property_names(),
            },
            status_code=400,
        )

    clean_title = title.strip()
    clean_status = status.strip()
    clean_scheduled_for = scheduled_for.strip()

    if not clean_title:
        return templates.TemplateResponse(
            request=request,
            name="jobs.html",
            context={
                "title": "Jobs",
                "user": get_user(request),
                "error": "Job title is required.",
                "properties": DATA["properties"],
                "jobs": build_jobs_with_property_names(),
            },
            status_code=400,
        )

    if clean_status not in valid_statuses:
        return templates.TemplateResponse(
            request=request,
            name="jobs.html",
            context={
                "title": "Jobs",
                "user": get_user(request),
                "error": "Please choose a valid job status.",
                "properties": DATA["properties"],
                "jobs": build_jobs_with_property_names(),
            },
            status_code=400,
        )

    DATA["jobs"].append(
        {
            "id": COUNTERS["jobs"],
            "title": clean_title,
            "property_id": property_id,
            "status": clean_status,
            "scheduled_for": clean_scheduled_for,
        }
    )
    COUNTERS["jobs"] += 1

    return RedirectResponse(url="/jobs", status_code=303)