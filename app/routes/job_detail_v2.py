from datetime import datetime, date
import re
from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from app.routes.auth import require_login, login_redirect, admin_redirect, is_admin, is_office, is_employee, is_client

router = APIRouter()

def core():
    from app import app as core_app
    return core_app

def ctx(*args, **kwargs): return core().ctx(*args, **kwargs)
def rows(*args, **kwargs): return core().rows(*args, **kwargs)
def one(*args, **kwargs): return core().one(*args, **kwargs)
def exec_sql(*args, **kwargs): return core().exec_sql(*args, **kwargs)
async def save_upload(*args, **kwargs): return await core().save_upload(*args, **kwargs)

class _TemplatesProxy:
    def __getattr__(self, name): return getattr(core().templates, name)
templates = _TemplatesProxy()

def _safe_float(value):
    try: return float(value or 0)
    except Exception: return 0.0

def _safe_date(value): return str(value or '')[:10]
def _is_done(status): return str(status or '').strip().lower() in ('complete','completed','done','closed')

def _materials_from_text(text):
    text = text or ''
    found = []
    structured = re.search(r'Materials:\s*(.+)', text, flags=re.I)
    if structured:
        chunk = structured.group(1).split('\n',1)[0]
        found.extend([x.strip(' -•\t') for x in re.split(r',|;|\band\b', chunk) if x.strip(' -•\t')])
    lower = text.lower()
    for pat in [r'bring\s+([^\.\n]+)', r'need\s+([^\.\n]+)', r'materials?\s*[:\-]\s*([^\.\n]+)', r'order\s+([^\.\n]+)', r'pick up\s+([^\.\n]+)', r'pickup\s+([^\.\n]+)']:
        for m in re.finditer(pat, lower, flags=re.I):
            chunk = re.split(r'\bfor\b|\bto\b|\bbefore\b', m.group(1))[0]
            found.extend([x.strip(' -•\t') for x in re.split(r',|;|\band\b', chunk) if x.strip(' -•\t')])
    clean, seen = [], set()
    for item in found:
        item = item.strip()
        if not item or len(item) > 80: continue
        key = item.lower()
        if key not in seen:
            clean.append(item); seen.add(key)
    return clean[:12]

def _property_for_job(job):
    if not job: return None
    address = str(job.get('address') or '').strip()
    property_name = str(job.get('property') or '').strip()
    client = str(job.get('client') or '').strip()
    prop = None
    if address: prop = one('SELECT * FROM poolops2_properties WHERE address=? LIMIT 1', (address,))
    if not prop and property_name: prop = one('SELECT * FROM poolops2_properties WHERE property_name=? LIMIT 1', (property_name,))
    if not prop and client: prop = one('SELECT * FROM poolops2_properties WHERE client=? ORDER BY id LIMIT 1', (client,))
    return prop

def _can_access_job(user, job):
    if not user or not job: return False
    if is_admin(user) or is_office(user): return True
    if is_employee(user):
        crew = str(job.get('crew') or '').lower()
        name = str(user.get('name') or '').lower()
        username = str(user.get('username') or '').lower()
        return crew in ('','unassigned') or (name and name in crew) or (username and username in crew)
    if is_client(user):
        return str(job.get('client') or '').strip().lower() == str(user.get('name') or '').strip().lower()
    return False

def _visible_job(user, job_id):
    job = one('SELECT * FROM poolops2_jobs WHERE id=?', (job_id,))
    return job if job and _can_access_job(user, job) else None

def _job_total_cost(costs):
    total = 0
    for c in costs:
        for key in ['labor','materials','subs','equipment','fuel','other']:
            total += _safe_float(c.get(key))
    return total

@router.get('/job-v2/{job_id}', response_class=HTMLResponse)
@router.get('/jobs/{job_id}/v2', response_class=HTMLResponse)
def job_detail_v2(request: Request, job_id: int):
    user = require_login(request)
    if not user: return login_redirect()
    job = _visible_job(user, job_id)
    if not job: return admin_redirect(user)
    prop = _property_for_job(job)
    property_id = prop.get('id') if prop else None
    client_name = job.get('client') or ''
    photos = rows('SELECT * FROM poolops2_photo_logs WHERE job_id=? ORDER BY id DESC', (job_id,))
    property_photos = rows('SELECT * FROM poolops2_photo_logs WHERE property_id=? ORDER BY id DESC LIMIT 30', (property_id,)) if property_id else []
    costs = rows('SELECT * FROM poolops2_job_costs WHERE job_id=? ORDER BY id DESC', (job_id,))
    invoices = rows('SELECT * FROM poolops2_invoices WHERE job_id=? OR client=? ORDER BY id DESC LIMIT 50', (job_id, client_name))
    field_logs = rows('SELECT * FROM field_logs WHERE client=? OR property=? OR address=? ORDER BY id DESC LIMIT 40', (client_name, job.get('property') or '', job.get('address') or ''))
    office_items = rows('SELECT * FROM invisible_office_items WHERE job_id=? OR client=? OR property=? ORDER BY id DESC LIMIT 80', (job_id, client_name, job.get('property') or ''))
    gps_points = []
    if job.get('crew'):
        crew_name = str(job.get('crew') or '').strip(); job_day = _safe_date(job.get('scheduled_start') or job.get('date'))
        if job_day:
            gps_points = rows('SELECT * FROM employee_location_points WHERE created_at LIKE ? AND lower(employee_name)=lower(?) ORDER BY created_at ASC LIMIT 300', (f'{job_day}%', crew_name))
    materials = _materials_from_text(job.get('notes') or '')
    cost_total = _job_total_cost(costs)
    invoice_total = sum(_safe_float(inv.get('amount')) for inv in invoices if inv.get('job_id') == job_id)
    open_balance = sum(_safe_float(inv.get('open_balance')) for inv in invoices if inv.get('job_id') == job_id)
    return templates.TemplateResponse('job_detail_v2.html', ctx(request, job=job, prop=prop, property_id=property_id, photos=photos, property_photos=property_photos, costs=costs, invoices=invoices, field_logs=field_logs, office_items=office_items, gps_points=gps_points, materials=materials, cost_total=cost_total, invoice_total=invoice_total, open_balance=open_balance, is_done=_is_done(job.get('status'))))

@router.post('/job-v2/{job_id}/status')
def job_detail_v2_status(request: Request, job_id: int, status: str = Form('Scheduled')):
    user = require_login(request)
    if not user: return login_redirect()
    job = _visible_job(user, job_id)
    if not job: return admin_redirect(user)
    if not (is_admin(user) or is_office(user) or is_employee(user)): return admin_redirect(user)
    exec_sql('UPDATE poolops2_jobs SET status=? WHERE id=?', (status, job_id))
    return RedirectResponse(f'/job-v2/{job_id}', status_code=303)

@router.post('/job-v2/{job_id}/notes')
def job_detail_v2_notes(request: Request, job_id: int, notes: str = Form(''), materials: str = Form('')):
    user = require_login(request)
    if not user: return login_redirect()
    job = _visible_job(user, job_id)
    if not job: return admin_redirect(user)
    if not (is_admin(user) or is_office(user) or is_employee(user)): return admin_redirect(user)
    final_notes = notes.strip()
    if materials.strip(): final_notes = final_notes + ('\n\n' if final_notes else '') + f'Materials: {materials.strip()}'
    exec_sql('UPDATE poolops2_jobs SET notes=? WHERE id=?', (final_notes, job_id))
    return RedirectResponse(f'/job-v2/{job_id}', status_code=303)

@router.post('/job-v2/{job_id}/photo')
async def job_detail_v2_photo(request: Request, job_id: int, title: str = Form('Job Photo'), notes: str = Form(''), photo: UploadFile = File(None)):
    user = require_login(request)
    if not user: return login_redirect()
    job = _visible_job(user, job_id)
    if not job: return admin_redirect(user)
    if is_client(user): return admin_redirect(user)
    url = await save_upload(photo)
    if url:
        prop = _property_for_job(job)
        exec_sql('INSERT INTO poolops2_photo_logs (job_id,property_id,client,photo_type,title,photo_url,date,notes) VALUES (?,?,?,?,?,?,?,?)', (job_id, prop.get('id') if prop else None, job.get('client') or '', 'Job', title.strip() or 'Job Photo', url, date.today().isoformat(), notes))
    return RedirectResponse(f'/job-v2/{job_id}', status_code=303)

@router.post('/job-v2/{job_id}/field-note')
def job_detail_v2_field_note(request: Request, job_id: int, note: str = Form(''), next_steps: str = Form(''), materials_used: str = Form(''), hours: float = Form(0)):
    user = require_login(request)
    if not user: return login_redirect()
    job = _visible_job(user, job_id)
    if not job: return admin_redirect(user)
    if is_client(user): return admin_redirect(user)
    exec_sql('INSERT INTO field_logs (employee_name,client,property,address,date,total_hours,materials_used,work_completed,next_steps,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)', (user.get('name') or user.get('username') or '', job.get('client') or '', job.get('property') or '', job.get('address') or '', date.today().isoformat(), hours, materials_used, note, next_steps, datetime.now().isoformat(timespec='seconds')))
    return RedirectResponse(f'/job-v2/{job_id}', status_code=303)

@router.post('/job-v2/{job_id}/billing-draft')
def job_detail_v2_billing_draft(request: Request, job_id: int, description: str = Form(''), amount: float = Form(0)):
    user = require_login(request)
    if not user: return login_redirect()
    job = _visible_job(user, job_id)
    if not job: return admin_redirect(user)
    if not (is_admin(user) or is_office(user)): return admin_redirect(user)
    desc = description.strip() or job.get('job_type') or 'Job Billing'
    exec_sql('INSERT INTO poolops2_invoices (job_id,client,description,amount,status,date,notes,open_balance,source) VALUES (?,?,?,?,?,?,?,?,?)', (job_id, job.get('client') or '', desc, amount, 'Draft', date.today().isoformat(), 'Created from Job Detail 2.0', amount, 'Job Detail 2.0'))
    return RedirectResponse(f'/job-v2/{job_id}', status_code=303)
