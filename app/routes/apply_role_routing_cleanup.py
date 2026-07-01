from pathlib import Path
import re

APP_PATH = Path("app/app.py")
AUTH_PATH = Path("app/routes/auth.py")

if not APP_PATH.exists():
    raise SystemExit("Missing app/app.py. Run this from your project root.")

if not AUTH_PATH.exists():
    raise SystemExit("Missing app/routes/auth.py. Run this from your project root.")

AUTH_PATH.write_text('''from fastapi import Request
from fastapi.responses import RedirectResponse


def current_user(request: Request):
    return request.session.get("user")


def require_login(request: Request):
    return current_user(request)


def role_of(user):
    return str((user or {}).get("role", "")).lower().strip()


def is_admin(user):
    return role_of(user) == "admin"


def is_office(user):
    return role_of(user) == "office"


def is_client(user):
    return role_of(user) == "client"


def is_employee(user):
    return role_of(user) in ("employee", "crew")


def login_redirect():
    return RedirectResponse("/login", status_code=303)


def home_for_user(user):
    if is_admin(user):
        return "/jarvis"
    if is_office(user):
        return "/office"
    if is_employee(user):
        return "/employee"
    if is_client(user):
        return "/client-portal-v2"
    return "/login"


def home_redirect(user):
    return RedirectResponse(home_for_user(user), status_code=303)


def admin_redirect(user):
    return home_redirect(user)
''', encoding="utf-8")

text = APP_PATH.read_text(encoding="utf-8")

old_import = '''from app.routes.auth import (
    current_user,
    require_login,
    is_admin,
    is_client,
    is_employee,
    login_redirect,
    admin_redirect,
)'''

new_import = '''from app.routes.auth import (
    current_user,
    require_login,
    is_admin,
    is_office,
    is_client,
    is_employee,
    login_redirect,
    admin_redirect,
    home_redirect,
)'''

if old_import in text:
    text = text.replace(old_import, new_import)
else:
    if "home_redirect" not in text:
        text = text.replace("admin_redirect,", "admin_redirect,\n    home_redirect,", 1)
    if "is_office" not in text:
        text = text.replace("is_admin,", "is_admin,\n    is_office,", 1)

text = text.replace('return RedirectResponse("/billing", status_code=303)', 'return RedirectResponse("/office", status_code=303)')
text = text.replace('return RedirectResponse("/client-portal", status_code=303)', 'return RedirectResponse("/client-portal-v2", status_code=303)')

root_pattern = re.compile(
    r'@app\.get\("/", response_class=HTMLResponse\)\ndef root\(request: Request\):\n(?:    .*\n)+?(?=\n\n@app\.get\("/login"|\n@app\.get\("/login")',
    re.MULTILINE
)

root_replacement = '''@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    u = current_user(request)
    if u:
        return home_redirect(u)
    return RedirectResponse("/login", status_code=303)
'''

text = root_pattern.sub(root_replacement, text, count=1)

# Allow office into accounting pages by patching common strict checks.
text = text.replace(
    "if not is_admin(u):\n        return admin_redirect(u)\n\n    return templates.TemplateResponse(\n        \"quickbooks.html\"",
    "if not (is_admin(u) or is_office(u)):\n        return admin_redirect(u)\n\n    return templates.TemplateResponse(\n        \"quickbooks.html\""
)

text = text.replace(
    "if not is_admin(u):\n        return admin_redirect(u)\n\n    invoice_rows = rows(",
    "if not (is_admin(u) or is_office(u)):\n        return admin_redirect(u)\n\n    invoice_rows = rows("
)

text = text.replace(
    "if not is_admin(u):\n        return admin_redirect(u)\n\n    return templates.TemplateResponse(\n        \"simple_crud.html\"",
    "if not (is_admin(u) or is_office(u)):\n        return admin_redirect(u)\n\n    return templates.TemplateResponse(\n        \"simple_crud.html\""
)

text = text.replace(
    "if not is_admin(u):\n        return admin_redirect(u)\n\n    return templates.TemplateResponse(\n        \"job_costing.html\"",
    "if not (is_admin(u) or is_office(u)):\n        return admin_redirect(u)\n\n    return templates.TemplateResponse(\n        \"job_costing.html\""
)

text = text.replace(
    "if not is_admin(u):\n        return RedirectResponse(\"/jarvis\", status_code=303)",
    "if not (is_admin(u) or is_office(u)):\n        return admin_redirect(u)"
)

include_office = "from app.routes import office\napp.include_router(office.router)\n"
if "from app.routes import office" not in text:
    text = text.rstrip() + "\n\n" + include_office

include_client_v2 = "from app.routes import client_portal_v2\napp.include_router(client_portal_v2.router)\n"
if "from app.routes import client_portal_v2" not in text:
    text = text.rstrip() + "\n\n" + include_client_v2

APP_PATH.write_text(text, encoding="utf-8")

print("Role routing cleanup applied.")
print("Admin  -> /jarvis")
print("Office -> /office")
print("Crew   -> /employee")
print("Client -> /client-portal-v2")
print("Restart: python -m uvicorn app.app:app --reload")
