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

USERS = {"mike": "1234", "jake": "1234"}

DATA = {
    "clients": [],
    "properties": [],
    "jobs": [],
}

COUNTERS = {"clients": 1, "properties": 1, "jobs": 1}


def get_user(request: Request):
    return request.session.get("user")


def require_login(request: Request):
    if not get_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return None


def get_client_name(client_id):
    for c in DATA["clients"]:
        if c["id"] == client_id:
            return c["name"]
    return "Unknown"


def get_property_name(property_id):
    for p in DATA["properties"]:
        if p["id"] == property_id:
            return p["name"]
    return "Unknown"


def jobs_with_names():
    result = []
    for j in DATA["jobs"]:
        result.append({
            **j,
            "property_name": get_property_name(j["property_id"])
        })
    return result


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "user": None,
        "error": None
    })


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if USERS.get(username) == password:
        request.session["user"] = username
        return RedirectResponse("/dashboard", status_code=303)

    return templates.TemplateResponse("login.html", {
        "request": request,
        "user": None,
        "error": "Invalid login"
    })


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if require_login(request):
        return require_login(request)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": get_user(request),
        "client_count": len(DATA["clients"]),
        "property_count": len(DATA["properties"]),
        "job_count": len(DATA["jobs"]),
        "recent_jobs": jobs_with_names()
    })


# ================= CLIENTS =================

@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    if require_login(request):
        return require_login(request)

    return templates.TemplateResponse("clients.html", {
        "request": request,
        "user": get_user(request),
        "clients": DATA["clients"],
        "error": None
    })


@app.post("/clients")
def add_client(request: Request, name: str = Form(...), phone: str = Form(""), email: str = Form("")):
    DATA["clients"].append({
        "id": COUNTERS["clients"],
        "name": name,
        "phone": phone,
        "email": email
    })
    COUNTERS["clients"] += 1
    return RedirectResponse("/clients", status_code=303)


@app.post("/clients/delete")
def delete_client(id: int = Form(...)):
    DATA["clients"] = [c for c in DATA["clients"] if c["id"] != id]
    return RedirectResponse("/clients", status_code=303)


# ================= PROPERTIES =================

@app.get("/properties", response_class=HTMLResponse)
def properties_page(request: Request):
    if require_login(request):
        return require_login(request)

    props = []
    for p in DATA["properties"]:
        props.append({
            **p,
            "client_name": get_client_name(p["client_id"])
        })

    return templates.TemplateResponse("properties.html", {
        "request": request,
        "user": get_user(request),
        "clients": DATA["clients"],
        "properties": props,
        "error": None
    })


@app.post("/properties")
def add_property(name: str = Form(...), client_id: int = Form(...)):
    DATA["properties"].append({
        "id": COUNTERS["properties"],
        "name": name,
        "client_id": client_id
    })
    COUNTERS["properties"] += 1
    return RedirectResponse("/properties", status_code=303)


@app.post("/properties/delete")
def delete_property(id: int = Form(...)):
    DATA["properties"] = [p for p in DATA["properties"] if p["id"] != id]
    return RedirectResponse("/properties", status_code=303)


# ================= JOBS =================

@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    if require_login(request):
        return require_login(request)

    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "user": get_user(request),
        "properties": DATA["properties"],
        "jobs": jobs_with_names(),
        "error": None
    })


@app.post("/jobs")
def add_job(title: str = Form(...), property_id: int = Form(...)):
    DATA["jobs"].append({
        "id": COUNTERS["jobs"],
        "title": title,
        "property_id": property_id,
        "status": "Scheduled"
    })
    COUNTERS["jobs"] += 1
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/delete")
def delete_job(id: int = Form(...)):
    DATA["jobs"] = [j for j in DATA["jobs"] if j["id"] != id]
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/status")
def update_status(id: int = Form(...), status: str = Form(...)):
    for j in DATA["jobs"]:
        if j["id"] == id:
            j["status"] = status
    return RedirectResponse("/jobs", status_code=303)