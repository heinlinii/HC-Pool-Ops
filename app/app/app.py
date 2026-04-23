import os
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(BASE_DIR)

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
    rows = []
    for prop in DATA["properties"]:
        rows.append(
            {
                "id": prop["id"],
                "name": prop["name"],
                "client_id": prop["client_id"],
                "client_name": get_client_name(prop["client_id"]),
                "address": prop.get("address", ""),
                "city": prop.get("city", ""),
            }
        )
    return rows


def build_jobs_with_property_names():
    rows = []
    for job in DATA["jobs"]:
        rows.append(
            {
                "id": job["id"],
                "title": job["title"],
                "property_id": job["property_id"],
                "property_name": get_property_name(job["property_id"]),
                "status": job.get("status", ""),
                "scheduled_for": job.get("scheduled_for", ""),
            }
        )
    return rows


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

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "title": "Dashboard",
            "user": get_user(request),
            "client_count": len(DATA["clients"]),
            "property_count": len(DATA["properties"]),
            "job_count": len(DATA["jobs"]),
            "recent_jobs": build_jobs_with_property_names(),
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
            "phone": phone.strip(),
            "email": email.strip(),
        }
    )
    COUNTERS["clients"] += 1

    return RedirectResponse(url="/clients", status_code=303)


@app.post("/clients/delete")
def delete_client(
    request: Request,
    id: int = Form(...),
):
    auth = require_login(request)
    if auth:
        return auth

    property_ids_to_delete = [p["id"] for p in DATA["properties"] if p["client_id"] == id]
    DATA["jobs"] = [j for j in DATA["jobs"] if j["property_id"] not in property_ids_to_delete]
    DATA["properties"] = [p for p in DATA["properties"] if p["client_id"] != id]
    DATA["clients"] = [c for c in DATA["clients"] if c["id"] != id]

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
            "address": address.strip(),
            "city": city.strip(),
        }
    )
    COUNTERS["properties"] += 1

    return RedirectResponse(url="/properties", status_code=303)


@app.post("/properties/delete")
def delete_property(
    request: Request,
    id: int = Form(...),
):
    auth = require_login(request)
    if auth:
        return auth

    DATA["jobs"] = [j for j in DATA["jobs"] if j["property_id"] != id]
    DATA["properties"] = [p for p in DATA["properties"] if p["id"] != id]

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
            "scheduled_for": scheduled_for.strip(),
        }
    )
    COUNTERS["jobs"] += 1

    return RedirectResponse(url="/jobs", status_code=303)


@app.post("/jobs/delete")
def delete_job(
    request: Request,
    id: int = Form(...),
):
    auth = require_login(request)
    if auth:
        return auth

    DATA["jobs"] = [j for j in DATA["jobs"] if j["id"] != id]
    return RedirectResponse(url="/jobs", status_code=303)


@app.post("/jobs/status")
def update_job_status(
    request: Request,
    id: int = Form(...),
    status: str = Form(...),
):
    auth = require_login(request)
    if auth:
        return auth

    valid_statuses = ["Scheduled", "In Progress", "Complete"]
    if status in valid_statuses:
        for job in DATA["jobs"]:
            if job["id"] == id:
                job["status"] = status
                break

    return RedirectResponse(url="/jobs", status_code=303)