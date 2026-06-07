from fastapi import APIRouter, Request, File, UploadFile, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.database import SessionLocal
from app.models import User, Client, Property

import csv
import io
import re
import os
from datetime import datetime


router = APIRouter()


def db_session():
    return SessionLocal()


def read_csv_upload(upload: UploadFile):
    raw = upload.file.read().decode("utf-8-sig")
    stream = io.StringIO(raw)
    return list(csv.DictReader(stream))


def pick(row, *keys):
    for key in keys:
        for actual_key, value in row.items():
            if actual_key and actual_key.strip().lower() == key.lower():
                return (value or "").strip()
    return ""


def get_current_user(request: Request):
    username = request.session.get("username")

    if not username:
        return None

    db = db_session()

    try:
        user = db.query(User).filter(User.username == username).first()

        if not user:
            return None

        return {
            "username": user.username,
            "name": user.name,
            "role": user.role,
        }

    finally:
        db.close()


def require_admin(request: Request):
    user = get_current_user(request)

    if not user:
        return None

    if user["role"] != "admin":
        return None

    return user


def normalize_phone(value):
    if not value:
        return ""

    digits = re.sub(r"\D", "", str(value))

    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) >= 10:
        return digits[-10:]

    return ""


def extract_phones(value):
    if not value:
        return set()

    parts = re.split(r"[|,;/\n]+", str(value))
    phones = set()

    for part in parts:
        normalized = normalize_phone(part)

        if normalized:
            phones.add(normalized)

    return phones


def normalize_email(value):
    if not value:
        return ""

    value = str(value).strip().lower()

    if "@" not in value:
        return ""

    return value


def extract_emails(value):
    if not value:
        return set()

    parts = re.split(r"[|,;/\n\s]+", str(value))
    emails = set()

    for part in parts:
        email = normalize_email(part)

        if email:
            emails.add(email)

    return emails


def safe_name(row):
    name = pick(
        row,
        "name",
        "Name",
        "customer",
        "Customer",
        "client",
        "Client",
        "display name",
        "Display Name",
        "company",
        "Company",
    )

    return name.strip()


def contact_record(row):
    name = safe_name(row)

    phone = pick(
        row,
        "phone",
        "Phone",
        "phone number",
        "Phone Number",
        "mobile",
        "Mobile",
        "main phone",
        "Main Phone",
    )

    all_phones = pick(
        row,
        "all phones",
        "All Phones",
        "phones",
        "Phones",
    )

    email = pick(
        row,
        "email",
        "Email",
        "email address",
        "Email Address",
        "main email",
        "Main Email",
        "E-mail 1 - Value",
    )

    all_emails = pick(
        row,
        "all emails",
        "All Emails",
        "emails",
        "Emails",
    )

    notes = pick(
        row,
        "notes",
        "Notes",
        "memo",
        "Memo",
        "description",
        "Description",
    )

    phones = set()
    phones.update(extract_phones(phone))
    phones.update(extract_phones(all_phones))

    emails = set()
    emails.update(extract_emails(email))
    emails.update(extract_emails(all_emails))

    return {
        "name": name,
        "phone": phone.strip(),
        "email": email.strip(),
        "notes": notes.strip(),
        "phones": phones,
        "emails": emails,
    }


def qb_record(row):
    name = safe_name(row)

    phone = pick(
        row,
        "phone",
        "Phone",
        "phone number",
        "Phone Number",
        "mobile",
        "Mobile",
        "main phone",
        "Main Phone",
    )

    all_phones = pick(
        row,
        "all phones",
        "All Phones",
        "phones",
        "Phones",
    )

    email = pick(
        row,
        "email",
        "Email",
        "email address",
        "Email Address",
        "main email",
        "Main Email",
        "E-mail 1 - Value",
    )

    all_emails = pick(
        row,
        "all emails",
        "All Emails",
        "emails",
        "Emails",
    )

    phones = set()
    phones.update(extract_phones(phone))
    phones.update(extract_phones(all_phones))

    emails = set()
    emails.update(extract_emails(email))
    emails.update(extract_emails(all_emails))

    return {
        "name": name,
        "phones": phones,
        "emails": emails,
    }


def backup_existing_clients(db):
    os.makedirs("app/static/uploads", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"clients_before_qb_matched_only_{timestamp}.csv"
    path = os.path.join("app/static/uploads", filename)

    clients = db.query(Client).order_by(Client.id.asc()).all()

    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        writer.writerow([
            "id",
            "name",
            "phone",
            "email",
            "notes",
        ])

        for client in clients:
            writer.writerow([
                client.id,
                client.name or "",
                client.phone or "",
                client.email or "",
                client.notes or "",
            ])

    return f"/static/uploads/{filename}"


@router.get("/imports/qb-matched-only")
async def qb_matched_only_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>QB Matched Contacts Only</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                background:#07111f;
                color:#e5f0ff;
                font-family:Arial, sans-serif;
                padding:24px;
            }
            .card {
                max-width:720px;
                margin:auto;
                background:#0f1b2d;
                border:1px solid rgba(255,255,255,.12);
                border-radius:18px;
                padding:22px;
            }
            h1 { margin-top:0; }
            label {
                display:block;
                margin-top:18px;
                font-weight:bold;
            }
            input {
                width:100%;
                margin-top:8px;
                padding:12px;
                border-radius:10px;
                border:1px solid rgba(255,255,255,.18);
                background:#07111f;
                color:white;
            }
            button {
                margin-top:22px;
                width:100%;
                padding:14px;
                border:0;
                border-radius:12px;
                background:#22d3ee;
                font-weight:bold;
                cursor:pointer;
            }
            .warning {
                background:#3b1b1b;
                border:1px solid #ef4444;
                color:#fecaca;
                padding:14px;
                border-radius:12px;
                margin-bottom:18px;
            }
            .note {
                color:#9fb3c8;
                line-height:1.5;
            }
            a { color:#67e8f9; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>QB Matched Contacts Only</h1>

            <div class="warning">
                This will wipe the current client list and rebuild it using ONLY phone contacts that match the ORIGINAL QuickBooks customer CSV by exact phone or exact email.
            </div>

            <p class="note">
                Use the original QuickBooks customer list — the one with about 312 customers.
                Do NOT use the current PoolOps export with 1,190 rows.
            </p>

            <form method="post" action="/imports/qb-matched-only" enctype="multipart/form-data">
                <label>Phone Contacts CSV</label>
                <input type="file" name="contacts_csv" accept=".csv" required>

                <label>Original QuickBooks Customers CSV</label>
                <input type="file" name="qb_csv" accept=".csv" required>

                <label>Type YES to confirm rebuild</label>
                <input type="text" name="confirm" placeholder="YES" required>

                <button type="submit">Rebuild Clients From QB Matches Only</button>
            </form>

            <p class="note">
                A backup CSV of the current client list will be created automatically before wiping.
            </p>

            <p><a href="/imports">Back to Imports</a></p>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(html)


@router.post("/imports/qb-matched-only")
async def rebuild_qb_matched_only(
    request: Request,
    contacts_csv: UploadFile = File(...),
    qb_csv: UploadFile = File(...),
    confirm: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    if confirm.strip() != "YES":
        return RedirectResponse(
            url="/imports?message=QB matched rebuild cancelled. Confirmation must be YES.",
            status_code=303,
        )

    contact_rows = read_csv_upload(contacts_csv)
    qb_rows = read_csv_upload(qb_csv)

    if len(qb_rows) > 500:
        return RedirectResponse(
            url=(
                "/imports?message="
                "Rebuild refused. Your QuickBooks file has more than 500 rows. "
                "Use the ORIGINAL QuickBooks customer list, not the current PoolOps export."
            ),
            status_code=303,
        )

    qb_phones = set()
    qb_emails = set()

    for row in qb_rows:
        record = qb_record(row)
        qb_phones.update(record["phones"])
        qb_emails.update(record["emails"])

    matched = []
    seen_keys = set()
    skipped_no_match = 0
    skipped_blank_name = 0
    skipped_duplicate = 0

    for row in contact_rows:
        contact = contact_record(row)

        if not contact["name"]:
            skipped_blank_name += 1
            continue

        phone_match = bool(contact["phones"] & qb_phones)
        email_match = bool(contact["emails"] & qb_emails)

        if not phone_match and not email_match:
            skipped_no_match += 1
            continue

        strongest_key = ""

        if contact["phones"]:
            strongest_key = sorted(contact["phones"])[0]
        elif contact["emails"]:
            strongest_key = sorted(contact["emails"])[0]
        else:
            strongest_key = contact["name"].strip().lower()

        if strongest_key in seen_keys:
            skipped_duplicate += 1
            continue

        seen_keys.add(strongest_key)

        match_note = []

        if phone_match:
            match_note.append("QB exact phone match")

        if email_match:
            match_note.append("QB exact email match")

        existing_notes = contact["notes"]

        final_notes = " | ".join(match_note)

        if existing_notes:
            final_notes = f"{final_notes} | Contact notes: {existing_notes}"

        matched.append({
            "name": contact["name"],
            "phone": contact["phone"],
            "email": contact["email"],
            "notes": final_notes,
        })

    db = db_session()

    try:
        backup_url = backup_existing_clients(db)

        db.query(Client).delete()

        imported = 0

        for item in matched:
            db.add(
                Client(
                    name=item["name"],
                    phone=item["phone"],
                    email=item["email"],
                    notes=item["notes"],
                )
            )

            imported += 1

        db.commit()

    finally:
        db.close()

    return RedirectResponse(
        url=(
            f"/imports?message="
            f"QB matched-only rebuild complete. "
            f"Imported {imported} matched clients. "
            f"Skipped {skipped_no_match} non-matches. "
            f"Skipped {skipped_blank_name} blank names. "
            f"Skipped {skipped_duplicate} duplicates. "
            f"Backup saved at {backup_url}"
        ),
        status_code=303,
    )

@router.post("/imports/clients")
async def import_clients(
    request: Request,
    csv_file: UploadFile = File(...),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    rows = read_csv_upload(csv_file)

    db = db_session()

    imported = 0
    updated = 0
    duplicate_skipped = 0
    blank_name_skipped = 0

    def pick(row, *keys):
        for key in keys:
            value = row.get(key)
            if value and str(value).strip():
                return str(value).strip()
        return ""

    def clean_text(value):
        return (value or "").lower().strip()

    def clean_phone(value):
        return (
            (value or "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
            .replace(" ", "")
            .replace(".", "")
            .replace("+1", "")
            .strip()
        )

    def find_existing_client(name, phone, email):
        clean_name = clean_text(name)
        clean_email = clean_text(email)
        clean_phone_value = clean_phone(phone)

        clients = db.query(Client).all()

        for client in clients:
            client_name = clean_text(client.name)
            client_email = clean_text(client.email)
            client_phone = clean_phone(client.phone or client.mobile)

            if clean_email and client_email and clean_email == client_email:
                return client

            if clean_phone_value and client_phone and clean_phone_value[-7:] == client_phone[-7:]:
                return client

            if clean_name and client_name and clean_name == client_name:
                return client

        return None

    for row in rows:

        name = pick(
            row,
            "name",
            "Name",
            "customer",
            "Customer",
            "client",
            "Client",
            "Display Name",
            "Full Name",
            "Customer Name",
            "Company",
            "Company Name",
        )

        phone = pick(
            row,
            "phone",
            "Phone",
            "mobile",
            "Mobile",
            "Cell",
            "Cell Phone",
            "Main Phone",
            "Primary Phone",
            "Phone Number",
        )

        email = pick(
            row,
            "email",
            "Email",
            "email address",
            "Email Address",
            "main email",
            "Main Email",
            "Primary Email",
            "E-mail",
        )

        notes = pick(
            row,
            "notes",
            "Notes",
            "memo",
            "Memo",
            "description",
            "Description",
        )

        if not name:
            blank_name_skipped += 1
            continue

        client_data = {
            "name": name,
            "contact_name": pick(row, "contact_name", "Contact Name", "Full Name"),
            "phone": phone,
            "mobile": phone,
            "email": email,
            "billing_address": pick(row, "billing_address", "Billing Address", "Address", "Street"),
            "shipping_address": pick(row, "shipping_address", "Shipping Address"),
            "city": pick(row, "city", "City"),
            "state": pick(row, "state", "State"),
            "zip_code": pick(row, "zip", "ZIP", "Zip Code", "Postal Code"),
            "company": pick(row, "company", "Company", "Company Name"),
            "notes": notes,
        }

        existing = find_existing_client(name, phone, email)

        if existing:
            duplicate_skipped += 1
            updated += 1

            for key, value in client_data.items():
                if value and not getattr(existing, key, None):
                    setattr(existing, key, value)

        else:
            new_client = Client(**client_data)
            db.add(new_client)
            db.flush()
            imported += 1

            address = (client_data.get("billing_address") or client_data.get("shipping_address") or "").strip()
            if address:
                db.add(Property(
                    client_id=new_client.id,
                    client=new_client.name,
                    property_name=f"{new_client.name} Pool",
                    address=address,
                    city=client_data.get("city", ""),
                    state=client_data.get("state", ""),
                    zip_code=client_data.get("zip_code", ""),
                    notes="Created automatically from imported QuickBooks client address.",
                ))

    # Make sure existing clients with imported addresses also get property cards.
    for client in db.query(Client).all():
        address = (client.billing_address or client.shipping_address or "").strip()
        if not address:
            continue
        existing_property = db.query(Property).filter(
            Property.client_id == client.id,
            Property.address == address
        ).first()
        if not existing_property:
            db.add(Property(
                client_id=client.id,
                client=client.name,
                property_name=f"{client.name} Pool",
                address=address,
                city=client.city or "",
                state=client.state or "",
                zip_code=client.zip_code or "",
                notes="Created automatically from imported QuickBooks client address.",
            ))

    db.commit()
    db.close()

    message = (
        f"Client import complete. "
        f"New clients: {imported}. "
        f"Updated existing: {updated}. "
        f"Duplicates matched: {duplicate_skipped}. "
        f"Blank names skipped: {blank_name_skipped}."
    )

    return RedirectResponse(
        url=f"/imports?message={message}",
        status_code=303,
    )

    return RedirectResponse(
        url=(
            f"/imports?message="
            f"Imported {imported} clients. "
            f"Skipped {duplicate_skipped} duplicates. "
            f"Skipped {blank_name_skipped} blank names."
        ),
        status_code=303,
    )