import os
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="HC Pool Ops", version="1.0.0")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "change-this-secret"),
)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

APP_USERS = {
    "mike": "1234",
    "jake": "1234",
}

DATA = {
    "clients": [
        {"id": 1, "name": "Smith Family", "phone": "812-555-0101", "email": "smith@example.com"},
        {"id": 2, "name": "Johnson Residence", "phone": "812-555-0102", "email": "johnson@example.com"},
    ],
    "properties": [
        {"id": 1, "client_id": 1, "name": "Backyard Pool", "address": "123 Main St", "city": "Evansville"},
        {"id": 2, "client_id": 2, "name": "Lake House Pool", "address": "456 Oak Ave", "city": "Newburgh"},
    ],
    "jobs": [
        {"id": 1, "property_id": 1, "title": "Spring Opening", "status": "Scheduled", "scheduled_for": "2026-04-25"},
        {"id": 2, "property_id": 2, "title": "Tile Repair", "status": "In Progress", "scheduled_for": "2026-04-27"},
    ],
}

COUNTERS = {
    "clients": 3,
    "properties": 3,
    "jobs": 3,
}


def get_current_user(request: Request) -> Optional[str]:
    return request.session.get("user")


def require_login(request: Request):
    if not get_current_user(request):
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


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return HTMLResponse("""
    <html>
    <head><title>Login</title></head>
    <body style="font-family:Arial;max-width:400px;margin:80px auto;">
        <h1>HC Pool Ops Login</h1>
        <form method="post" action="/login">
            <label>Username</label><br>
            <input name="username" style="width:100%;padding:10px;"><br><br>
            <label>Password</label><br>
            <input name="password" type="password" style="width:100%;padding:10px;"><br><br>
            <button type="submit" style="width:100%;padding:12px;">Login</button>
        </form>
    </body>
    </html>
    """)


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username in APP_USERS and APP_USERS[username] == password:
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
                "property_name": get_property_name(job["property_id"]),
            }
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Dashboard",
            "user": get_current_user(request),
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
            "user": get_current_user(request),
            "clients": DATA["clients"],
            "error": None,
        },
    )


@app.post("/clients", response_class=HTMLResponse)
def create_client(
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
            "clients.html",
            {
                "request": request,
                "title": "Clients",
                "user": get_current_user(request),
                "clients": DATA["clients"],
                "error": "Client name is required.",
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

    enriched_properties = []
    for prop in DATA["properties"]:
        enriched_properties.append(
            {
                **prop,
                "client_name": get_client_name(prop["client_id"]),
            }
        )

    return templates.TemplateResponse(
        "properties.html",
        {
            "request": request,
            "title": "Properties",
            "user": get_current_user(request),
            "properties": enriched_properties,
            "clients": DATA["clients"],
            "error": None,
        },
    )


@app.post("/properties", response_class=HTMLResponse)
def create_property(
    request: Request,
    client_id: int = Form(...),
    name: str = Form(...),
    address: str = Form(""),
    city: str = Form(""),
):
    auth = require_login(request)
    if auth:
        return auth

    clean_name = name.strip()
    clean_address = address.strip()
    clean_city = city.strip()

    valid_client_ids = [client["id"] for client in DATA["clients"]]
    if client_id not in valid_client_ids:
        enriched_properties = []
        for prop in DATA["properties"]:
            enriched_properties.append(
                {
                    **prop,
                    "client_name": get_client_name(prop["client_id"]),
                }
            )
        return templates.TemplateResponse(
            "properties.html",
            {
                "request": request,
                "title": "Properties",
                "user": get_current_user(request),
                "properties": enriched_properties,
                "clients": DATA["clients"],
                "error": "Please choose a valid client.",
            },
            status_code=400,
        )

    if not clean_name:
        enriched_properties = []
        for prop in DATA["properties"]:
            enriched_properties.append(
                {
                    **prop,
                    "client_name": get_client_name(prop["client_id"]),
                }
            )
        return templates.TemplateResponse(
            "properties.html",
            {
                "request": request,
                "title": "Properties",
                "user": get_current_user(request),
                "properties": enriched_properties,
                "clients": DATA["clients"],
                "error": "Property name is required.",
            },
            status_code=400,
        )

    DATA["properties"].append(
        {
            "id": COUNTERS["properties"],
            "client_id": client_id,
            "name": clean_name,
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

    enriched_jobs = []
    for job in DATA["jobs"]:
        enriched_jobs.append(
            {
                **job,
                "property_name": get_property_name(job["property_id"]),
            }
        )

    return templates.TemplateResponse(
        "jobs.html",
        {
            "request": request,
            "title": "Jobs",
            "user": get_current_user(request),
            "jobs": enriched_jobs,
            "properties": DATA["properties"],
            "error": None,
        },
    )


@app.post("/jobs", response_class=HTMLResponse)
def create_job(
    request: Request,
    property_id: int = Form(...),
    title: str = Form(...),
    status: str = Form(...),
    scheduled_for: str = Form(""),
):
    auth = require_login(request)
    if auth:
        return auth

    clean_title = title.strip()
    clean_status = status.strip()
    clean_date = scheduled_for.strip()

    valid_property_ids = [prop["id"] for prop in DATA["properties"]]
    valid_statuses = ["Scheduled", "In Progress", "Complete"]

    if property_id not in valid_property_ids:
        enriched_jobs = []
        for job in DATA["jobs"]:
            enriched_jobs.append(
                {
                    **job,
                    "property_name": get_property_name(job["property_id"]),
                }
            )
        return templates.TemplateResponse(
            "jobs.html",
            {
                "request": request,
                "title": "Jobs",
                "user": get_current_user(request),
                "jobs": enriched_jobs,
                "properties": DATA["properties"],
                "error": "Please choose a valid property.",
            },
            status_code=400,
        )

    if not clean_title:
        enriched_jobs = []
        for job in DATA["jobs"]:
            enriched_jobs.append(
                {
                    **job,
                    "property_name": get_property_name(job["property_id"]),
                }
            )
        return templates.TemplateResponse(
            "jobs.html",
            {
                "request": request,
                "title": "Jobs",
                "user": get_current_user(request),
                "jobs": enriched_jobs,
                "properties": DATA["properties"],
                "error": "Job title is required.",
            },
            status_code=400,
        )

    if clean_status not in valid_statuses:
        enriched_jobs = []
        for job in DATA["jobs"]:
            enriched_jobs.append(
                {
                    **job,
                    "property_name": get_property_name(job["property_id"]),
                }
            )
        return templates.TemplateResponse(
            "jobs.html",
            {
                "request": request,
                "title": "Jobs",
                "user": get_current_user(request),
                "jobs": enriched_jobs,
                "properties": DATA["properties"],
                "error": "Please choose a valid job status.",
            },
            status_code=400,
        )

    DATA["jobs"].append(
        {
            "id": COUNTERS["jobs"],
            "property_id": property_id,
            "title": clean_title,
            "status": clean_status,
            "scheduled_for": clean_date,
        }
    )
    COUNTERS["jobs"] += 1

    return RedirectResponse(url="/jobs", status_code=303)
