from functools import wraps
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

app = FastAPI()

app.add_middleware(SessionMiddleware, secret_key="hc-pool-ops-secret-key")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

CLIENTS = [
    {
        "id": 1,
        "name": "John Smith",
        "phone": "(812) 555-0101",
        "email": "john@example.com",
        "address": "123 Main St, Evansville, IN",
        "notes": "Needs spring opening and weekly service.",
    },
    {
        "id": 2,
        "name": "Sarah Johnson",
        "phone": "(812) 555-0102",
        "email": "sarah@example.com",
        "address": "456 Oak Ave, Newburgh, IN",
        "notes": "Automatic cover issue last season.",
    },
]

PROPERTIES = [
    {
        "id": 1,
        "client_id": 1,
        "name": "Smith Residence",
        "address": "123 Main St, Evansville, IN",
        "pool_type": "Concrete",
        "status": "Active",
        "notes": "Auto cover installed. Weekly route.",
    },
    {
        "id": 2,
        "client_id": 2,
        "name": "Johnson Residence",
        "address": "456 Oak Ave, Newburgh, IN",
        "pool_type": "Fiberglass",
        "status": "Service Only",
        "notes": "Cover motor issue from last season.",
    },
]

SERVICE_STOPS = [
    {
        "id": 1,
        "property_id": 1,
        "title": "Weekly Service",
        "scheduled_for": "2026-04-22",
        "status": "Scheduled",
        "technician": "Mike Heinlin",
        "notes": "Vacuum, chemistry check, basket cleanout.",
    },
    {
        "id": 2,
        "property_id": 2,
        "title": "Cover Inspection",
        "scheduled_for": "2026-04-23",
        "status": "Open",
        "technician": "Jake Turner",
        "notes": "Check cover track and motor alignment.",
    },
]

EMPLOYEES = [
    {
        "id": 1,
        "name": "Mike Heinlin",
        "role": "Admin",
        "phone": "(812) 449-6198",
        "email": "mike@heinlin.com",
        "status": "Active",
    },
    {
        "id": 2,
        "name": "Jake Turner",
        "role": "Field",
        "phone": "(812) 555-0125",
        "email": "jake@heinlin.com",
        "status": "Active",
    },
]

USERS = [
    {
        "id": 1,
        "username": "mike",
        "password": "1234",
        "role": "admin",
        "employee_name": "Mike Heinlin",
    },
    {
        "id": 2,
        "username": "jake",
        "password": "1234",
        "role": "field",
        "employee_name": "Jake Turner",
    },
]


def get_client(client_id: int) -> Optional[dict]:
    return next((c for c in CLIENTS if c["id"] == client_id), None)


def get_property(property_id: int) -> Optional[dict]:
    return next((p for p in PROPERTIES if p["id"] == property_id), None)


def get_stop(stop_id: int) -> Optional[dict]:
    return next((s for s in SERVICE_STOPS if s["id"] == stop_id), None)


def login_required(route_func):
    @wraps(route_func)
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if request is None:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

        if request is None or not request.session.get("logged_in"):
            return RedirectResponse("/login", status_code=302)

        return await route_func(*args, **kwargs)

    return wrapper


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if request.session.get("logged_in"):
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("logged_in"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "",
        },
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = next(
        (
            u
            for u in USERS
            if u["username"].lower() == username.strip().lower()
            and u["password"] == password.strip()
        ),
        None,
    )

    if not user:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid username or password.",
            },
            status_code=400,
        )

    request.session["logged_in"] = True
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]
    request.session["employee_name"] = user["employee_name"]

    return RedirectResponse("/dashboard", status_code=302)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
@login_required
async def dashboard(request: Request):
    recent_properties = PROPERTIES[:4]
    recent_stops = SERVICE_STOPS[:4]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "username": request.session.get("username", "User"),
            "employee_name": request.session.get("employee_name", "User"),
            "client_count": len(CLIENTS),
            "property_count": len(PROPERTIES),
            "stop_count": len(SERVICE_STOPS),
            "employee_count": len(EMPLOYEES),
            "recent_properties": recent_properties,
            "recent_stops": recent_stops,
        },
    )


@app.get("/clients", response_class=HTMLResponse)
@login_required
async def clients_page(request: Request):
    return templates.TemplateResponse(
        "clients.html",
        {
            "request": request,
            "clients": CLIENTS,
        },
    )


@app.get("/properties", response_class=HTMLResponse)
@login_required
async def properties_page(request: Request):
    property_rows = []
    for prop in PROPERTIES:
        client = get_client(prop["client_id"])
        property_rows.append(
            {
                **prop,
                "client_name": client["name"] if client else "Unknown",
            }
        )

    return templates.TemplateResponse(
        "properties.html",
        {
            "request": request,
            "properties": property_rows,
        },
    )


@app.get("/jobs", response_class=HTMLResponse)
@login_required
async def jobs_page(request: Request):
    job_rows = []
    for stop in SERVICE_STOPS:
        prop = get_property(stop["property_id"])
        client = get_client(prop["client_id"]) if prop else None
        job_rows.append(
            {
                **stop,
                "property_name": prop["name"] if prop else "Unknown Property",
                "client_name": client["name"] if client else "Unknown Client",
            }
        )

    return templates.TemplateResponse(
        "jobs.html",
        {
            "request": request,
            "jobs": job_rows,
        },
    )


@app.get("/employees", response_class=HTMLResponse)
@login_required
async def employees_page(request: Request):
    return templates.TemplateResponse(
        "employees.html",
        {
            "request": request,
            "employees": EMPLOYEES,
        },
    )


@app.get("/service-stops/{stop_id}", response_class=HTMLResponse)
@login_required
async def service_stop_detail(request: Request, stop_id: int):
    stop = get_stop(stop_id)
    if not stop:
        return RedirectResponse("/jobs", status_code=302)

    prop = get_property(stop["property_id"])
    client = get_client(prop["client_id"]) if prop else None

    detail = {
        **stop,
        "property_name": prop["name"] if prop else "Unknown Property",
        "property_address": prop["address"] if prop else "",
        "client_name": client["name"] if client else "Unknown Client",
    }

    return templates.TemplateResponse(
        "service_stop_detail.html",
        {
            "request": request,
            "stop": detail,
        },
    )