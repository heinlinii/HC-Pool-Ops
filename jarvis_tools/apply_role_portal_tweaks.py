
from pathlib import Path
import shutil
import re

ROOT = Path.cwd()
APP = ROOT / "app"
TEMPLATES = APP / "templates"
APP_PY = APP / "app.py"

backup = ROOT / "jarvis_backups" / "before_role_portal_tweaks"
backup.mkdir(parents=True, exist_ok=True)

def backup_file(path):
    if path.exists():
        dest = backup / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

for path in [
    APP_PY,
    TEMPLATES / "base.html",
    TEMPLATES / "employee_portal.html",
    TEMPLATES / "employee.html",
    TEMPLATES / "field_logs.html",
    TEMPLATES / "field_log.html",
]:
    backup_file(path)

# ---------------------------
# Patch app.py
# ---------------------------
if APP_PY.exists():
    txt = APP_PY.read_text(encoding="utf-8")

    # API for Field Ops client dropdown.
    if '@app.get("/api/clients"' not in txt:
        api_route = '''
@app.get("/api/clients")
def api_clients(request: Request):
    user = require_login(request)
    if not user:
        return []
    try:
        return rows("SELECT id, client_name, contact_name, phone, email FROM poolops2_clients ORDER BY client_name LIMIT 1000")
    except Exception:
        try:
            return rows("SELECT id, client_name, contact_name, phone, email FROM clients ORDER BY client_name LIMIT 1000")
        except Exception:
            return []
'''
        txt = txt.rstrip() + "\n\n" + api_route + "\n"

    # Utility to force Mike into admin role when app starts or login routes run.
    if "def jarvis_force_admin_role()" not in txt:
        helper = '''
def jarvis_force_admin_role():
    try:
        exec_sql("UPDATE poolops2_users SET role='admin' WHERE username='mike'")
    except Exception:
        pass
'''
        txt = txt.rstrip() + "\n\n" + helper + "\n"

    # Add a safer admin redirect check before employee redirects if possible.
    if "JARVIS_ADMIN_REDIRECT_BEFORE_EMPLOYEE" not in txt:
        redirect_block = '''
        # JARVIS_ADMIN_REDIRECT_BEFORE_EMPLOYEE
        try:
            role_check = ""
            try:
                role_check = (user.get("role") or "").lower()
            except Exception:
                role_check = str(getattr(user, "role", "") or "").lower()
            username_check = ""
            try:
                username_check = (user.get("username") or "").lower()
            except Exception:
                username_check = str(getattr(user, "username", "") or "").lower()
            if role_check == "admin" or username_check == "mike":
                return RedirectResponse("/dashboard", status_code=303)
        except Exception:
            pass
'''
        for target in [
            'return RedirectResponse("/employee", status_code=303)',
            'return RedirectResponse("/employee-portal", status_code=303)',
            'return RedirectResponse("/client-portal", status_code=303)',
        ]:
            idx = txt.find(target)
            if idx != -1:
                line_start = txt.rfind("\n", 0, idx) + 1
                indent = re.match(r"\s*", txt[line_start:idx]).group(0)
                patched = "\n".join(indent + line if line.strip() else line for line in redirect_block.strip("\n").split("\n")) + "\n"
                txt = txt[:line_start] + patched + txt[line_start:]
                break

    # If app has HEINLIN FIELD OPS READY print, call admin force before it.
    if "jarvis_force_admin_role()" not in txt.split("def jarvis_force_admin_role()")[0]:
        if 'print("HEINLIN FIELD OPS READY")' in txt:
            txt = txt.replace('print("HEINLIN FIELD OPS READY")', 'jarvis_force_admin_role()\n    print("HEINLIN FIELD OPS READY")', 1)
        elif "print('HEINLIN FIELD OPS READY')" in txt:
            txt = txt.replace("print('HEINLIN FIELD OPS READY')", "jarvis_force_admin_role()\n    print('HEINLIN FIELD OPS READY')", 1)

    APP_PY.write_text(txt, encoding="utf-8")

# ---------------------------
# Universal back/dashboard bar
# ---------------------------
base = TEMPLATES / "base.html"
if base.exists():
    b = base.read_text(encoding="utf-8")
    b = b.replace(">My Jobs<", ">My Info<").replace("My Jobs", "My Info")
    if "jarvis-back-bar" not in b:
        back_html = '''
<div class="jarvis-back-bar">
  <button type="button" onclick="history.length > 1 ? history.back() : window.location.href='/dashboard'">← Back</button>
  <a href="/dashboard">Dashboard</a>
</div>
<style>
.jarvis-back-bar{position:sticky;top:0;z-index:999;display:flex;gap:10px;align-items:center;padding:10px 14px;background:rgba(8,13,24,.92);backdrop-filter:blur(10px);border-bottom:1px solid rgba(255,255,255,.10)}
.jarvis-back-bar button,.jarvis-back-bar a{border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.08);color:inherit;text-decoration:none;border-radius:12px;padding:9px 13px;font-weight:800}
@media(max-width:800px){.jarvis-back-bar{padding:8px 10px}.jarvis-back-bar button,.jarvis-back-bar a{font-size:.9rem;padding:8px 10px}}
</style>
'''
        if re.search(r"<body[^>]*>", b, flags=re.I):
            b = re.sub(r"(<body[^>]*>)", r"\1\n" + back_html, b, count=1, flags=re.I)
        else:
            b = back_html + "\n" + b
    base.write_text(b, encoding="utf-8")

# ---------------------------
# Employee portal: My Info wording + calendar schedule
# ---------------------------
for filename in ["employee_portal.html", "employee.html"]:
    p = TEMPLATES / filename
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    s = s.replace("My Jobs", "My Info").replace("my jobs", "my info")
    if "Calendar Schedule" not in s:
        card = '''
<section class="panel">
  <h2>Calendar Schedule</h2>
  <p class="muted">View the company schedule and assigned work.</p>
  <a class="btn" href="/schedule/month">Open Calendar Schedule</a>
</section>
'''
        if "{% block content %}" in s:
            s = s.replace("{% block content %}", "{% block content %}\n" + card, 1)
        else:
            s = card + "\n" + s
    p.write_text(s, encoding="utf-8")

# ---------------------------
# Field Ops: client dropdown selector
# ---------------------------
dropdown = '''
<div class="form-group jarvis-client-dropdown">
  <label for="client_name">Client</label>
  <select name="client_name" id="client_name">
    <option value="">Select client...</option>
  </select>
</div>
<script id="jarvis-client-dropdown-script">
fetch('/api/clients')
  .then(r => r.json())
  .then(clients => {
    const sel = document.getElementById('client_name');
    if (!sel) return;
    clients.forEach(c => {
      const name = c.client_name || c.name || '';
      if (!name) return;
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    });
  })
  .catch(() => {});
</script>
'''
for filename in ["field_logs.html", "field_log.html"]:
    p = TEMPLATES / filename
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    if "jarvis-client-dropdown-script" in s:
        continue

    replaced = False
    s2 = re.sub(r'<input[^>]+name=["\\\']client_name["\\\'][^>]*>', dropdown, s, count=1, flags=re.I)
    if s2 != s:
        s = s2
        replaced = True

    if not replaced:
        s2 = re.sub(r"(<form[^>]*>)", r"\1\n" + dropdown, s, count=1, flags=re.I)
        s = s2

    p.write_text(s, encoding="utf-8")

print("DONE. Role/portal tweaks applied.")
print("Backups saved to:", backup)
print("Included: admin dashboard redirect, My Info wording, universal Back button, employee calendar, Field Ops client dropdown.")
