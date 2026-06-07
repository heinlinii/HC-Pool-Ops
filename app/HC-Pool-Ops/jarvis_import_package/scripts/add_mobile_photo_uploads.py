from pathlib import Path
import re
import shutil
from datetime import datetime

ROOT = Path.cwd()
APP = ROOT / 'app' / 'app.py'
CLIENT_TPL = ROOT / 'app' / 'templates' / 'client_detail.html'
PROPERTY_TPL = ROOT / 'app' / 'templates' / 'property_detail.html'
BACKUP_DIR = ROOT / 'jarvis_backups' / ('mobile_photo_uploads_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

for p in [APP, CLIENT_TPL, PROPERTY_TPL]:
    if not p.exists():
        raise SystemExit(f'MISSING FILE: {p}')
    shutil.copy2(p, BACKUP_DIR / p.name)

app = APP.read_text(encoding='utf-8')

# Make sure UploadFile/File imports exist.
if 'from fastapi import FastAPI, Request, Form, File, UploadFile' not in app:
    app = app.replace('from fastapi import FastAPI, Request, Form', 'from fastapi import FastAPI, Request, Form, File, UploadFile')

client_func = '''@app.post("/clients/{client_id}/card-image")
async def update_client_card_image(
    request: Request,
    client_id: int,
    card_image: str = Form(""),
    card_upload: UploadFile = File(None),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    db = db_session()
    try:
        client = db.query(Client).filter(Client.id == client_id).first()
        if client:
            if card_upload and card_upload.filename:
                client.card_image = save_uploaded_photo(card_upload)
            elif card_image.strip():
                client.card_image = card_image.strip()
            db.commit()
        return RedirectResponse(url=f"/clients/{client_id}", status_code=303)
    finally:
        db.close()

'''

property_func = '''@app.post("/properties/{property_id}/card-image")
async def update_property_card_image(
    request: Request,
    property_id: int,
    card_image: str = Form(""),
    card_upload: UploadFile = File(None),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    db = db_session()
    try:
        prop = db.query(Property).filter(Property.id == property_id).first()
        if prop:
            if card_upload and card_upload.filename:
                prop.card_image = save_uploaded_photo(card_upload)
            elif card_image.strip():
                prop.card_image = card_image.strip()
            db.commit()
        return RedirectResponse(url=f"/properties/{property_id}", status_code=303)
    finally:
        db.close()

'''

app = re.sub(
    r'@app\.post\("/clients/\{client_id\}/card-image"\)\s*async def update_client_card_image\([\s\S]*?\n\s*finally:\s*\n\s*db\.close\(\)\s*\n',
    client_func,
    app,
    count=1,
)
app = re.sub(
    r'@app\.post\("/properties/\{property_id\}/card-image"\)\s*async def update_property_card_image\([\s\S]*?\n\s*finally:\s*\n\s*db\.close\(\)\s*\n',
    property_func,
    app,
    count=1,
)

APP.write_text(app, encoding='utf-8')

client_tpl = CLIENT_TPL.read_text(encoding='utf-8')
client_tpl = client_tpl.replace(
    '<form method="post" action="/clients/{{ client.id }}/card-image" class="ops-form-grid">',
    '<form method="post" action="/clients/{{ client.id }}/card-image" enctype="multipart/form-data" class="ops-form-grid">'
)
old_client_block = '''<div class="full">
                    <label>Client Card Background URL</label>
                    <input name="card_image" value="{{ client.card_image or '' }}" placeholder="/static/uploads/photo.jpg">
                </div>
                <div class="full"><button class="secondary-button">Save Card Image</button></div>'''
new_client_block = '''<div class="full">
                    <label>Upload Client Card Photo</label>
                    <input type="file" name="card_upload" accept="image/*" capture="environment">
                    <p class="role-note">On your phone, tap this to choose a photo or take one with the camera.</p>
                </div>
                <div class="full">
                    <label>Or Paste Background URL</label>
                    <input name="card_image" value="{{ client.card_image or '' }}" placeholder="/static/uploads/photo.jpg">
                </div>
                <div class="full"><button class="secondary-button">Save Card Image</button></div>'''
client_tpl = client_tpl.replace(old_client_block, new_client_block)
CLIENT_TPL.write_text(client_tpl, encoding='utf-8')

prop_tpl = PROPERTY_TPL.read_text(encoding='utf-8')
prop_tpl = prop_tpl.replace(
    '<form method="post" action="/properties/{{ property.id }}/card-image" class="ops-form-grid">',
    '<form method="post" action="/properties/{{ property.id }}/card-image" enctype="multipart/form-data" class="ops-form-grid">'
)
old_prop_line = '<div class="full"><label>Background Image URL</label><input name="card_image" value="{{ property.card_image or \'\' }}" placeholder="/static/uploads/photo.jpg"></div>'
new_prop_line = '''<div class="full">
                <label>Upload Property Card Photo</label>
                <input type="file" name="card_upload" accept="image/*" capture="environment">
                <p class="role-note">On your phone, tap this to choose a photo or take one with the camera.</p>
            </div>
            <div class="full"><label>Or Paste Background Image URL</label><input name="card_image" value="{{ property.card_image or '' }}" placeholder="/static/uploads/photo.jpg"></div>'''
prop_tpl = prop_tpl.replace(old_prop_line, new_prop_line)
PROPERTY_TPL.write_text(prop_tpl, encoding='utf-8')

print('DONE. Mobile photo upload fields added.')
print('Backups saved in:', BACKUP_DIR)
