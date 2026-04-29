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
    secret_key="poolops-secret-key"
)

# Static + Templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Fake users (for now)
users = {
    "mike": {"password": "5500", "role": "admin"},
    "randy": {"password": "0318", "role": "crew"},
    "traylor": {"password": "8899", "role": "client"},
}

# HEALTH
@app.get("/health")
def health():
    return {"status": "ok", "app": "PoolOps Pro"}

# HOME
@app.get("/", response_class=HTMLResponse)
def home():
    return "<h1>PoolOps Pro is LIVE</h1><a href='/login'>Go to Login</a>"

# LOGIN PAGE
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# LOGIN SUBMIT
@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = users.get(username)

    if not user or user["password"] != password:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid login"}
        )

    request.session["user"] = username
    request.session["role"] = user["role"]

    return RedirectResponse("/dashboard", status_code=302)

# DASHBOARD
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = request.session.get("user")

    if not user:
        return RedirectResponse("/login")

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "role": request.session.get("role")
        }
    )