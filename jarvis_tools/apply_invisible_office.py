
from pathlib import Path
import shutil

ROOT = Path.cwd()
app_py = ROOT / "app" / "app.py"
base_html = ROOT / "app" / "templates" / "base.html"
dash_html = ROOT / "app" / "templates" / "dashboard.html"

backup = ROOT / "jarvis_backups" / "before_invisible_office_patch"
backup.mkdir(parents=True, exist_ok=True)
for p in [app_py, base_html, dash_html]:
    if p.exists():
        shutil.copy2(p, backup / p.name)

txt = app_py.read_text(encoding="utf-8")

if "poolops2_office_notes" not in txt:
    marker = 'c.execute(' + chr(34)*3 + 'CREATE TABLE IF NOT EXISTS poolops2_invoices'
    insert = (
        'c.execute(' + chr(34)*3 + 'CREATE TABLE IF NOT EXISTS poolops2_office_notes (\\n'
        "            id INTEGER PRIMARY KEY AUTOINCREMENT,\\n"
        "            note TEXT DEFAULT '',\\n"
        "            created_at TEXT DEFAULT ''\\n"
        '        )' + chr(34)*3 + ')\\n'
        '        '
    )
    txt = txt.replace(marker, insert + marker)

if '@app.get("/invisible-office"' not in txt:
    route = """
@app.get("/invisible-office", response_class=HTMLResponse)
def invisible_office(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    notes = rows("SELECT * FROM poolops2_office_notes ORDER BY id DESC LIMIT 25")
    return templates.TemplateResponse("invisible_office.html", {"request": request, "user": user, "theme": theme(), "notes": notes, "title": "Invisible Office"})


@app.post("/invisible-office/note")
def invisible_office_note(request: Request, note: str = Form("")):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if note.strip():
        exec_sql("INSERT INTO poolops2_office_notes (note, created_at) VALUES (?,?)", (note.strip(), datetime.now().strftime("%Y-%m-%d %I:%M %p")))
    return RedirectResponse("/invisible-office", status_code=303)
"""
    txt = txt.rstrip() + "\n\n" + route + "\n"

app_py.write_text(txt, encoding="utf-8")

if base_html.exists():
    b = base_html.read_text(encoding="utf-8")
    if "/invisible-office" not in b:
        b = b.replace('<a href="/schedule/month">Calendar</a>', '<a href="/schedule/month">Calendar</a>\n    <a href="/invisible-office">Invisible Office</a>')
    base_html.write_text(b, encoding="utf-8")

if dash_html.exists():
    d = dash_html.read_text(encoding="utf-8")
    if "Invisible Office" not in d:
        old = "('Photos','Field photos','/photos',theme.photos_image)"
        new = "('Invisible Office','Jarvis command desk','/invisible-office',theme.field_log_image),('Photos','Field photos','/photos',theme.photos_image)"
        d = d.replace(old, new)
    dash_html.write_text(d, encoding="utf-8")

print("DONE. Invisible Office restored.")
print("Backups saved to:", backup)
print("Restart server with: uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload")
