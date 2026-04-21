from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.post("/login")
def login(
    username: str = Form(...),
    password: str = Form(...),
):
    if username.strip() and password.strip():
        return RedirectResponse("/dashboard", status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": Request,
            "error": "Username and password required.",
        },
        status_code=400,
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/clients", response_class=HTMLResponse)
def clients(request: Request):
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request):
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/employees", response_class=HTMLResponse)
def employees(request: Request):
    return RedirectResponse("/dashboard", status_code=302)