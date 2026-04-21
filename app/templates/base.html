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
        "role": "admin",
        "employee_name": "Mike Heinlin",
    },
    {
        "id": 2,
        "username": "jake",
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
    def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if request is None:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

        if request is None or not request.session.get("logged_in"):
            return RedirectResponse("/login", status_code=302)

        return route_func(*args, **kwargs)

    return wrapper


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if request.session.get("logged_in"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("logged_in"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username.strip() and password.strip():
        request.session["logged_in"] = True
        request.session["username"] = username.strip()
        return RedirectResponse("/dashboard", status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "Username and password required.",
        },
        status_code=400,
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
@login_required
def dashboard(request: Request):
    recent_properties = PROPERTIES[:4]
    recent_stops = SERVICE_STOPS[:4]
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "username": request.session.get("username", "User"),
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
def clients_page(request: Request):
    return templates.TemplateResponse(
        "clients.html",
        {
            "request": request,
            "clients": CLIENTS,
        },
    )


@app.get("/clients/new", response_class=HTMLResponse)
@login_required
def new_client_page(request: Request):
    return templates.TemplateResponse("client_new.html", {"request": request})


@app.post("/clients/new")
@login_required
def create_client(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    notes: str = Form(""),
):
    next_id = max([c["id"] for c in CLIENTS], default=0) + 1
    CLIENTS.append(
        {
            "id": next_id,
            "name": name,
            "phone": phone,
            "email": email,
            "address": address,
            "notes": notes,
        }
    )
    return RedirectResponse("/clients", status_code=302)


@app.get("/properties", response_class=HTMLResponse)
@login_required
def properties_page(request: Request):
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


@app.get("/properties/new", response_class=HTMLResponse)
@login_required
def new_property_page(request: Request):
    return templates.TemplateResponse(
        "property_new.html",
        {
            "request": request,
            "clients": CLIENTS,
        },
    )


@app.post("/properties/new")
@login_required
def create_property(
    request: Request,
    client_id: int = Form(...),
    name: str = Form(...),
    address: str = Form(...),
    pool_type: str = Form(""),
    status: str = Form("Active"),
    notes: str = Form(""),
):
    next_id = max([p["id"] for p in PROPERTIES], default=0) + 1
    PROPERTIES.append(
        {
            "id": next_id,
            "client_id": client_id,
            "name": name,
            "address": address,
            "pool_type": pool_type,
            "status": status,
            "notes": notes,
        }
    )
    return RedirectResponse("/properties", status_code=302)


@app.get("/property/{property_id}", response_class=HTMLResponse)
@login_required
def property_detail(request: Request, property_id: int):
    prop = get_property(property_id)
    if not prop:
        return RedirectResponse("/properties", status_code=302)

    client = get_client(prop["client_id"])
    related_stops = [s for s in SERVICE_STOPS if s["property_id"] == property_id]

    return templates.TemplateResponse(
        "property_detail.html",
        {
            "request": request,
            "property": prop,
            "client": client,
            "service_stops": related_stops,
        },
    )


@app.get("/schedule", response_class=HTMLResponse)
@login_required
def schedule_page(request: Request):
    stop_rows = []
    for stop in SERVICE_STOPS:
        prop = get_property(stop["property_id"])
        stop_rows.append(
            {
                **stop,
                "property_name": prop["name"] if prop else "Unknown",
            }
        )

    return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "service_stops": stop_rows,
        },
    )


@app.get("/schedule/new", response_class=HTMLResponse)
@login_required
def schedule_new_page(request: Request):
    return templates.TemplateResponse(
        "schedule_new.html",
        {
            "request": request,
            "properties": PROPERTIES,
            "employees": EMPLOYEES,
        },
    )


@app.post("/schedule/new")
@login_required
def create_schedule_item(
    request: Request,
    property_id: int = Form(...),
    title: str = Form(...),
    scheduled_for: str = Form(...),
    technician: str = Form(...),
    status: str = Form("Scheduled"),
    notes: str = Form(""),
):
    next_id = max([s["id"] for s in SERVICE_STOPS], default=0) + 1
    SERVICE_STOPS.append(
        {
            "id": next_id,
            "property_id": property_id,
            "title": title,
            "scheduled_for": scheduled_for,
            "status": status,
            "technician": technician,
            "notes": notes,
        }
    )
    return RedirectResponse("/schedule", status_code=302)


@app.get("/service-stop/new", response_class=HTMLResponse)
@login_required
def service_stop_new_page(request: Request):
    return templates.TemplateResponse(
        "service_stop_new.html",
        {
            "request": request,
            "properties": PROPERTIES,
            "employees": EMPLOYEES,
        },
    )


@app.post("/service-stop/new")
@login_required
def create_service_stop(
    request: Request,
    property_id: int = Form(...),
    title: str = Form(...),
    scheduled_for: str = Form(...),
    technician: str = Form(...),
    status: str = Form("Open"),
    notes: str = Form(""),
):
    next_id = max([s["id"] for s in SERVICE_STOPS], default=0) + 1
    SERVICE_STOPS.append(
        {
            "id": next_id,
            "property_id": property_id,
            "title": title,
            "scheduled_for": scheduled_for,
            "status": status,
            "technician": technician,
            "notes": notes,
        }
    )
    return RedirectResponse(f"/service-stop/{next_id}", status_code=302)


@app.get("/service-stop/{stop_id}", response_class=HTMLResponse)
@login_required
def service_stop_detail(request: Request, stop_id: int):
    stop = get_stop(stop_id)
    if not stop:
        return RedirectResponse("/schedule", status_code=302)

    prop = get_property(stop["property_id"])

    return templates.TemplateResponse(
        "service_stop_detail.html",
        {
            "request": request,
            "stop": stop,
            "property": prop,
        },
    )


@app.get("/today", response_class=HTMLResponse)
@login_required
def today_page(request: Request):
    today_items = SERVICE_STOPS[:5]
    enriched = []
    for stop in today_items:
        prop = get_property(stop["property_id"])
        enriched.append(
            {
                **stop,
                "property_name": prop["name"] if prop else "Unknown",
            }
        )

    return templates.TemplateResponse(
        "today.html",
        {
            "request": request,
            "items": enriched,
        },
    )


@app.get("/users", response_class=HTMLResponse)
@login_required
def users_page(request: Request):
    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "users": USERS,
        },
    )


@app.get("/employees", response_class=HTMLResponse)
@login_required
def employees_page(request: Request):
    return templates.TemplateResponse(
        "employees.html",
        {
            "request": request,
            "employees": EMPLOYEES,
        },
    )


@app.get("/employees/new", response_class=HTMLResponse)
@login_required
def employee_new_page(request: Request):
    return templates.TemplateResponse("employee_new.html", {"request": request})


@app.post("/employees/new")
@login_required
def create_employee(
    request: Request,
    name: str = Form(...),
    role: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    status: str = Form("Active"),
):
    next_id = max([e["id"] for e in EMPLOYEES], default=0) + 1
    EMPLOYEES.append(
        {
            "id": next_id,
            "name": name,
            "role": role,
            "phone": phone,
            "email": email,
            "status": status,
        }
    )
    return RedirectResponse("/employees", status_code=302)


@app.get("/portal/request", response_class=HTMLResponse)
def portal_request_page(request: Request):
    return templates.TemplateResponse("portal_request.html", {"request": request})


@app.post("/portal/request")
def submit_portal_request(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    request_type: str = Form(...),
    message: str = Form(""),
):
    return RedirectResponse("/portal/thanks", status_code=302)


@app.get("/portal/thanks", response_class=HTMLResponse)
def portal_thanks_page(request: Request):
    return templates.TemplateResponse("portal_thanks.html", {"request": request})


@app.get("/search", response_class=HTMLResponse)
@login_required
def search_page(request: Request, q: str = ""):
    q_lower = q.lower().strip()

    client_matches = [c for c in CLIENTS if q_lower in c["name"].lower()] if q_lower else []
    property_matches = [p for p in PROPERTIES if q_lower in p["name"].lower()] if q_lower else []
    stop_matches = [s for s in SERVICE_STOPS if q_lower in s["title"].lower()] if q_lower else []

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "query": q,
            "client_matches": client_matches,
            "property_matches": property_matches,
            "stop_matches": stop_matches,
        },
    )