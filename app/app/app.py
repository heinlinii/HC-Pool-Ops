from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates
import os

app = FastAPI()

# Sessions
app.add_middleware(
    SessionMiddleware,
    secret_key="poolops-secret-key",
)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

templates = Jinja2Templates(
    directory=os.path.join(BASE_DIR, "../templates")
)

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(BASE_DIR, "../static")),
    name="static"
)

# Users (temp)
users = {
    "mike": {"password": "1234", "role": "admin"},
    "jake": {"password": "1234", "role": "crew"},
    "smith": {"password": "1234", "role": "client"},
}

# LOGIN PAGE
@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# LOGIN ACTION
@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = users.get(username)

    if user and user["password"] == password:
        request.session["user"] = username
        request.session["role"] = user["role"]
        return RedirectResponse("/dashboard", status_code=303)

    return RedirectResponse("/", status_code=303)

# DASHBOARD
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = request.session.get("user")
    role = request.session.get("role")

    if not user:
        return RedirectResponse("/")

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "role": role
        }
    )

# LOGOUT
@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")

# HEALTH
@app.get("/health")
def health():
    return {"status": "ok", "app": "PoolOps Pro"}