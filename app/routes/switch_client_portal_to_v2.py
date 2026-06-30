from pathlib import Path
import re

APP_PATH = Path("app/app.py")

if not APP_PATH.exists():
    raise SystemExit("Could not find app/app.py. Run this from the project root.")

text = APP_PATH.read_text(encoding="utf-8")

include_block = "from app.routes import client_portal_v2\napp.include_router(client_portal_v2.router)\n"

if "from app.routes import client_portal_v2" not in text:
    marker = "from app.routes import property_brain\napp.include_router(property_brain.router)"
    if marker in text:
        text = text.replace(marker, marker + "\n\n" + include_block)
    else:
        text = text.rstrip() + "\n\n" + include_block + "\n"

pattern = re.compile(
    r'@app\.get\("/client-portal", response_class=HTMLResponse\)\n'
    r'def client_portal\(request: Request\):\n'
    r'(?P<body>(?:    .*\n)+?)(?=\n@app\.|\n# |\n\n# |$)',
    re.MULTILINE
)

replacement = """@app.get("/client-portal", response_class=HTMLResponse)
def client_portal(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    # Client Portal 2.0 is now the active client portal.
    # Keep the old URL alive so existing client login redirects still work.
    return RedirectResponse("/client-portal-v2", status_code=303)
"""

if pattern.search(text):
    text = pattern.sub(replacement, text, count=1)
else:
    text = text.rstrip() + "\n\n" + replacement + "\n"

APP_PATH.write_text(text, encoding="utf-8")

print("Client Portal 2.0 switch applied.")
print("Now restart:")
print("python -m uvicorn app.app:app --reload")
print("Then test /client-portal and /client-portal-v2")
