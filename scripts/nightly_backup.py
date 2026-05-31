from datetime import datetime
from pathlib import Path
import json
import os
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.app import rows

BACKUP_DIR = ROOT / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

R2_ENABLED = os.environ.get("R2_ENABLED", "").lower() == "true"
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "")


def upload_to_r2(file_path: Path):
    if not R2_ENABLED:
        print("R2 upload skipped: R2_ENABLED is not true")
        return

    missing = []
    if not R2_ACCOUNT_ID:
        missing.append("R2_ACCOUNT_ID")
    if not R2_ACCESS_KEY_ID:
        missing.append("R2_ACCESS_KEY_ID")
    if not R2_SECRET_ACCESS_KEY:
        missing.append("R2_SECRET_ACCESS_KEY")
    if not R2_BUCKET_NAME:
        missing.append("R2_BUCKET_NAME")

    if missing:
        print("R2 upload skipped. Missing: " + ", ".join(missing))
        return

    endpoint_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    object_key = f"poolops-backups/{file_path.name}"

    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )

        s3.upload_file(str(file_path), R2_BUCKET_NAME, object_key)

        print(f"R2 upload complete: {object_key}")

    except (BotoCoreError, ClientError) as e:
        print(f"R2 upload failed: {e}")


def run_backup():
    ts = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")

    backup = {
        "timestamp": ts,
        "clients": rows("SELECT * FROM poolops2_clients"),
        "properties": rows("SELECT * FROM poolops2_properties"),
        "jobs": rows("SELECT * FROM poolops2_jobs"),
        "employees": rows("SELECT * FROM poolops2_employees"),
        "field_logs": rows("SELECT * FROM field_logs"),
    }

    filename = BACKUP_DIR / f"backup_{ts}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2, default=str)

    print(f"Backup written: {filename}")

    upload_to_r2(filename)


if __name__ == "__main__":
    run_backup()