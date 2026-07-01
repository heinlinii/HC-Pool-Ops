from pathlib import Path
import re

APP_PATH = Path("app/app.py")
if not APP_PATH.exists():
    raise SystemExit("Could not find app/app.py. Run this from the project root.")

text = APP_PATH.read_text(encoding="utf-8")

include_block = "from app.routes import mike_mode\napp.include_router(mike_mode.router)\n"
if "from app.routes import mike_mode" not in text:
    text = text.rstrip() + "\n\n" + include_block + "\n"

# Admin login/root landing should go to Mike Mode.
text = text.replace('return RedirectResponse("/jarvis", status_code=303)', 'return RedirectResponse("/mike", status_code=303)')

root_pattern = re.compile(
    r'@app\.get\("/", response_class=HTMLResponse\)\n'
    r'def root\(request: Request\):\n'
    r'(?:    .*\n)+?(?=\n\n@app\.get\("/login"|\n@app\.get\("/login")',
    re.MULTILINE
)

root_replacement = """@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    u = current_user(request)
    if not u:
        return RedirectResponse("/login", status_code=303)

    role = str(u.get("role", "")).lower()

    if role == "admin":
        return RedirectResponse("/mike", status_code=303)
    if role == "office":
        return RedirectResponse("/office", status_code=303)
    if role in ("crew", "employee"):
        return RedirectResponse("/employee", status_code=303)
    if role == "client":
        return RedirectResponse("/client-portal-v2", status_code=303)

    return RedirectResponse("/login", status_code=303)
"""

text = root_pattern.sub(root_replacement, text, count=1)

APP_PATH.write_text(text, encoding="utf-8")

AUTH_PATH = Path("app/routes/auth.py")
if AUTH_PATH.exists():
    auth = AUTH_PATH.read_text(encoding="utf-8")
    auth = auth.replace('return "/jarvis"', 'return "/mike"')
    AUTH_PATH.write_text(auth, encoding="utf-8")

print("Mike Mode takeover applied.")
print("Admin now lands on /mike.")
print("Restart:")
print("python -m uvicorn app.app:app --reload")
