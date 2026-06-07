from pathlib import Path
import shutil

ROOT = Path.cwd()
app_py = ROOT / "app" / "app.py"
tmpl = ROOT / "app" / "templates" / "invisible_office.html"
backup = ROOT / "jarvis_backups" / "before_invisible_office_command_desk"
backup.mkdir(parents=True, exist_ok=True)

for p in [app_py, tmpl]:
    if p.exists():
        shutil.copy2(p, backup / p.name)

txt = app_py.read_text(encoding="utf-8")

route = '\n@app.get("/invisible-office/search", response_class=HTMLResponse)\ndef invisible_office_search(request: Request, q: str = ""):\n    user = require_login(request)\n    if not user:\n        return RedirectResponse("/login", status_code=303)\n\n    q = (q or "").strip()\n    like = f"%{q}%"\n    results = []\n\n    def add_results(kind, sql, params, url_prefix, title_fields, detail_fields):\n        try:\n            for row in rows(sql, params):\n                title = " ".join(str(row.get(f) or "") for f in title_fields).strip() or kind\n                detail = " | ".join(str(row.get(f) or "") for f in detail_fields if row.get(f)).strip()\n                results.append({"kind": kind, "title": title, "detail": detail, "url": f"{url_prefix}{row.get(\'id\')}"})\n        except Exception:\n            pass\n\n    if q:\n        add_results("Client",\n            "SELECT * FROM poolops2_clients WHERE client_name LIKE ? OR contact_name LIKE ? OR phone LIKE ? OR email LIKE ? OR notes LIKE ? LIMIT 25",\n            (like, like, like, like, like), "/clients/", ["client_name"], ["contact_name", "phone", "email", "notes"])\n\n        add_results("Property",\n            "SELECT * FROM poolops2_properties WHERE property_name LIKE ? OR address LIKE ? OR city LIKE ? OR notes LIKE ? LIMIT 25",\n            (like, like, like, like), "/properties/", ["property_name"], ["address", "city", "notes"])\n\n        add_results("Job",\n            "SELECT * FROM poolops2_jobs WHERE client_name LIKE ? OR property_name LIKE ? OR job_type LIKE ? OR description LIKE ? OR notes LIKE ? LIMIT 25",\n            (like, like, like, like, like), "/jobs/", ["client_name", "property_name"], ["job_type", "status", "description", "notes"])\n\n        try:\n            for row in rows("SELECT * FROM poolops2_office_notes WHERE note LIKE ? ORDER BY id DESC LIMIT 25", (like,)):\n                results.append({"kind": "Office Note", "title": row.get("created_at") or "Note", "detail": row.get("note") or "", "url": "/invisible-office"})\n        except Exception:\n            pass\n\n    try:\n        notes = rows("SELECT * FROM poolops2_office_notes ORDER BY id DESC LIMIT 25")\n    except Exception:\n        notes = []\n\n    return templates.TemplateResponse("invisible_office.html", {"request": request, "user": user, "theme": theme(), "notes": notes, "q": q, "results": results, "title": "Invisible Office"})\n'

if '@app.get("/invisible-office/search"' not in txt:
    txt = txt.rstrip() + "\n\n" + route + "\n"
    app_py.write_text(txt, encoding="utf-8")

print("DONE. Invisible Office Command Desk upgraded.")
print("Backups saved to:", backup)
print("Restart server with: uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload")
