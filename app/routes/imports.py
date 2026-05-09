from fastapi import APIRouter, Request, File, UploadFile
from fastapi.responses import RedirectResponse

from app.database import SessionLocal
from app.models import User, Client

import csv
import io


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


@router.post("/imports/clients")
async def import_clients(
    request: Request,
    csv_file: UploadFile = File(...)
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    rows = read_csv_upload(csv_file)

    db = db_session()

    imported = 0
    duplicate_skipped = 0
    blank_name_skipped = 0

    try:
        for row in rows:
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
                "All Phones",
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

            existing = (
                db.query(Client)
                .filter(Client.name == name)
                .first()
            )

            if existing:
                duplicate_skipped += 1
                continue

            db.add(
                Client(
                    name=name.strip(),
                    phone=phone.strip(),
                    email=email.strip(),
                    notes=notes.strip(),
                )
            )

            imported += 1

        db.commit()

    finally:
        db.close()

    return RedirectResponse(
        url=(
            f"/imports?message="
            f"Imported {imported} clients. "
            f"Skipped {duplicate_skipped} duplicates. "
            f"Skipped {blank_name_skipped} blank names."
        ),
        status_code=303,
    )