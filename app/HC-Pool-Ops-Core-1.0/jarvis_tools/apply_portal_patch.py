from pathlib import Path
import shutil
from datetime import datetime

ROOT = Path.cwd()
APP = ROOT / 'app' / 'app.py'
STYLE = ROOT / 'app' / 'static' / 'style.css'
SIDEBAR = ROOT / 'app' / 'templates' / '_sidebar.html'
TEMPLATES = ROOT / 'app' / 'templates'

backup_dir = ROOT / 'jarvis_backups' / ('portal_patch_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
backup_dir.mkdir(parents=True, exist_ok=True)
for p in [APP, STYLE, SIDEBAR, TEMPLATES / 'employees.html', TEMPLATES / 'client_detail.html']:
    if p.exists():
        shutil.copy2(p, backup_dir / p.name)

# Kill the legacy fixed sidebar everywhere.
SIDEBAR.write_text('<!-- Legacy fixed sidebar disabled by Jarvis portal patch. Use top/mobile navigation only. -->\n', encoding='utf-8')

css = r'''

/* === JARVIS PORTAL/AUTH + NO-LEFT-SIDEBAR PATCH === */
.sidebar, aside.sidebar, .left-sidebar, .app-sidebar, .desktop-sidebar {
  display: none !important;
  width: 0 !important;
  min-width: 0 !important;
  max-width: 0 !important;
  overflow: hidden !important;
}
body, main, .main, .content, .page, .ops-shell, .dashboard-page {
  margin-left: 0 !important;
  padding-left: max(16px, env(safe-area-inset-left)) !important;
}
.ops-shell {
  max-width: 1240px !important;
  width: min(1240px, calc(100vw - 24px)) !important;
  margin: 0 auto !important;
}
.jarvis-portal-box {
  border: 1px solid rgba(255,255,255,.14);
  border-radius: 22px;
  background: rgba(255,255,255,.045);
  padding: 18px;
  margin-top: 16px;
}
.jarvis-credential-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 10px;
  align-items: end;
}
.jarvis-small-note { opacity:.72; font-size:.92rem; margin-top:8px; }
@media (max-width: 800px) {
  body, main, .main, .content, .page, .ops-shell, .dashboard-page {
    margin-left: 0 !important;
    padding-left: 12px !important;
    padding-right: 12px !important;
  }
  .ops-shell { width: calc(100vw - 24px) !important; }
  .jarvis-credential-row { grid-template-columns: 1fr; }
  .ops-header-actions { width:100%; display:grid !important; grid-template-columns:1fr 1fr 1fr; gap:8px; }
  .ops-header-actions a, .ops-header-actions button { width:100%; text-align:center; }
}
'''
if STYLE.exists():
    current = STYLE.read_text(encoding='utf-8', errors='ignore')
    if 'JARVIS PORTAL/AUTH + NO-LEFT-SIDEBAR PATCH' not in current:
        STYLE.write_text(current + css, encoding='utf-8')
else:
    STYLE.parent.mkdir(parents=True, exist_ok=True)
    STYLE.write_text(css, encoding='utf-8')

# Copy patched templates from package to active app templates.
PATCH_TEMPLATES = ROOT / 'jarvis_tools' / 'templates'
for name in ['employee_login.html', 'employee_portal.html', 'portal_setup.html', 'employees.html', 'client_detail.html']:
    src = PATCH_TEMPLATES / name
    if src.exists():
        shutil.copy2(src, TEMPLATES / name)

portal_code = r'''

# ============================================================
# JARVIS PORTAL / ROLE LOGIN PATCH
# Added by APPLY_PORTAL_AUTH_PATCH.bat
# ============================================================

def _jarvis_safe_username(value):
    raw = (value or '').strip().lower()
    cleaned = ''.join(ch for ch in raw if ch.isalnum() or ch in ['@', '.', '_', '-'])
    return cleaned or 'user'


def _jarvis_default_password(seed, fallback='0318'):
    text_value = ''.join(ch for ch in (seed or '') if ch.isdigit())
    if len(text_value) >= 4:
        return text_value[-4:]
    return fallback


@app.get('/portal-setup')
async def jarvis_portal_setup_page(request: Request):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url='/', status_code=303)
    db = db_session()
    try:
        employees = db.query(Employee).order_by(Employee.name.asc()).all()
        clients = db.query(Client).order_by(Client.name.asc()).all()
        users = db.query(User).order_by(User.role.asc(), User.username.asc()).all()
        return templates.TemplateResponse(request, 'portal_setup.html', {
            'user': user,
            'employees': employees,
            'clients': clients,
            'users': users,
        })
    finally:
        db.close()


@app.post('/portal-setup/seed')
async def jarvis_seed_portal_logins(request: Request):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url='/', status_code=303)
    db = db_session()
    try:
        for employee in db.query(Employee).all():
            username = _jarvis_safe_username(employee.email or employee.name)
            password = _jarvis_default_password(employee.phone, '0318')
            existing = db.query(User).filter(User.username == username).first()
            if existing:
                existing.password = password
                existing.role = 'crew'
                existing.name = employee.name
            else:
                db.add(User(username=username, password=password, role='crew', name=employee.name))

        for client_obj in db.query(Client).all():
            if not (client_obj.portal_username or '').strip():
                client_obj.portal_username = _jarvis_safe_username(client_obj.email or client_obj.name)
            if not (client_obj.portal_password or '').strip():
                client_obj.portal_password = str(client_obj.id).zfill(4)
        db.commit()
        return RedirectResponse(url='/portal-setup', status_code=303)
    finally:
        db.close()


@app.get('/employee-login')
async def jarvis_employee_login_page(request: Request):
    return templates.TemplateResponse(request, 'employee_login.html', {'error': None})


@app.post('/employee-login')
async def jarvis_employee_login(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip().lower()
    password = password.strip()
    db = db_session()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or user.role not in ['crew', 'employee', 'admin'] or user.password != password:
            return templates.TemplateResponse(request, 'employee_login.html', {'error': 'Employee login not found or password is incorrect.'}, status_code=401)
        request.session['username'] = user.username
        request.session['employee_name'] = user.name
        return RedirectResponse(url='/employee-portal', status_code=303)
    finally:
        db.close()


@app.get('/employee-portal')
async def jarvis_employee_portal(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url='/employee-login', status_code=303)
    db = db_session()
    try:
        employee_name = user.get('name') or request.session.get('employee_name') or user.get('username')
        jobs = db.query(Job).filter(Job.crew == employee_name).order_by(Job.id.desc()).all()
        if user.get('role') == 'admin' and not jobs:
            jobs = db.query(Job).order_by(Job.id.desc()).limit(25).all()
        logs = []
        try:
            logs = db.query(FieldLog).filter(FieldLog.employee_name == employee_name).order_by(FieldLog.id.desc()).limit(25).all()
        except Exception:
            logs = []
        return templates.TemplateResponse(request, 'employee_portal.html', {
            'user': user,
            'employee_name': employee_name,
            'jobs': jobs,
            'logs': logs,
        })
    finally:
        db.close()


@app.post('/employees/{employee_id}/portal-login')
async def jarvis_save_employee_portal_login(request: Request, employee_id: int, username: str = Form(''), password: str = Form('')):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url='/', status_code=303)
    db = db_session()
    try:
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if employee:
            username_value = _jarvis_safe_username(username or employee.email or employee.name)
            password_value = (password or _jarvis_default_password(employee.phone, '0318')).strip()
            existing = db.query(User).filter(User.username == username_value).first()
            if existing:
                existing.password = password_value
                existing.role = 'crew'
                existing.name = employee.name
            else:
                db.add(User(username=username_value, password=password_value, role='crew', name=employee.name))
            db.commit()
        return RedirectResponse(url='/employees', status_code=303)
    finally:
        db.close()




@app.post('/clients/{client_id}/upload-card-photo')
async def jarvis_upload_client_card_photo(request: Request, client_id: int, photo: UploadFile = File(None)):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url='/', status_code=303)
    db = db_session()
    try:
        client_obj = db.query(Client).filter(Client.id == client_id).first()
        if client_obj and photo and photo.filename:
            os.makedirs('app/static/uploads', exist_ok=True)
            safe_name = ''.join(ch for ch in photo.filename if ch.isalnum() or ch in ['.', '_', '-']) or 'client_photo.jpg'
            filename = f"client_{client_id}_{uuid4().hex}_{safe_name}"
            file_path = os.path.join('app/static/uploads', filename)
            with open(file_path, 'wb') as buffer:
                shutil.copyfileobj(photo.file, buffer)
            client_obj.card_image = '/' + file_path.replace('app/', '').replace('\\', '/')
            db.commit()
        return RedirectResponse(url=f'/clients/{client_id}', status_code=303)
    finally:
        db.close()

@app.get('/client-portal')
async def jarvis_client_portal_alias(request: Request):
    return RedirectResponse(url='/client-dashboard', status_code=303)

# ============================================================
# END JARVIS PORTAL PATCH
# ============================================================
'''

if APP.exists():
    app_text = APP.read_text(encoding='utf-8', errors='ignore')
    if 'JARVIS PORTAL / ROLE LOGIN PATCH' not in app_text:
        APP.write_text(app_text.rstrip() + portal_code + '\n', encoding='utf-8')

print('DONE. Portal/auth patch installed.')
print('Backup saved in:', backup_dir)
print('Restart PoolOps: uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload')
