"""Read-only legacy business snapshot; success requires verified off-host storage."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "backups"
REQUIRED_TABLES = {
    "clients": "poolops2_clients",
    "properties": "poolops2_properties",
    "jobs": "poolops2_jobs",
    "employees": "poolops2_employees",
    "field_logs": "field_logs",
    "invoices": "poolops2_invoices",
}
# This operational export does not copy authentication credentials or tokens.
EXCLUDED_TABLES = {"app_users", "users", "poolops2_users", "quickbooks_tokens"}


class BackupError(RuntimeError):
    pass


def database_url(environ):
    value = environ.get("DATABASE_URL", "").strip()
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"postgres", "postgresql"} and parsed.hostname and parsed.path.strip("/")
    except ValueError:
        valid = False
    if not valid:
        raise BackupError("DATABASE_URL must identify the verified legacy PostgreSQL database")
    # Never substitute a different database automatically when this host fails.
    return value


def r2_settings(environ):
    if environ.get("R2_ENABLED", "").strip().lower() != "true":
        raise BackupError("R2_ENABLED must be true; temporary local files are not a durable backup")
    names = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME")
    missing = [name for name in names if not environ.get(name, "").strip()]
    if missing:
        raise BackupError("Missing backup settings: " + ", ".join(missing))
    return {name: environ[name].strip() for name in names}


def collect_snapshot(url, connect=None):
    # Deliberately avoid importing app.app: a backup must not start the web app
    # or run application schema initialization.
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    connect = connect or psycopg.connect
    with connect(url, row_factory=dict_row, connect_timeout=15) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '120s'")
            cursor.execute("SELECT current_database() AS name, current_timestamp AS captured_at")
            source = cursor.fetchone()
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
            tables = [row["table_name"] for row in cursor.fetchall() if row["table_name"] not in EXCLUDED_TABLES]
            missing = set(REQUIRED_TABLES.values()) - set(tables)
            if missing:
                raise BackupError("Required legacy tables missing; check DATABASE_URL: " + ", ".join(sorted(missing)))
            records = {}
            for table in tables:
                cursor.execute(sql.SQL("SELECT * FROM public.{}").format(sql.Identifier(table)))
                records[table] = cursor.fetchall()
    snapshot = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y_%m_%d_%H_%M_%S_%f"),
        "format_version": 2,
        "source_database": source["name"],
        "captured_at": str(source["captured_at"]),
        "excluded_tables": sorted(EXCLUDED_TABLES),
        "tables": records,
        "table_counts": {table: len(rows) for table, rows in records.items()},
    }
    # Preserve the original top-level sections for existing backup readers.
    snapshot.update({section: records[table] for section, table in REQUIRED_TABLES.items()})
    return snapshot


def create_s3(settings):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=settings["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=settings["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 3}),
    )


def upload_to_r2(file_path, settings, s3=None):
    s3 = s3 or create_s3(settings)
    bucket = settings["R2_BUCKET_NAME"]
    key = f"poolops-backups/{file_path.name}"
    expected_size = file_path.stat().st_size
    expected_digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    # Exceptions must propagate. A skipped or failed upload cannot be success.
    s3.upload_file(str(file_path), bucket, key, ExtraArgs={
        "ContentType": "application/json", "Metadata": {"sha256": expected_digest},
    })
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    digest = hashlib.sha256()
    size = 0
    try:
        for chunk in body.iter_chunks(chunk_size=1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    finally:
        body.close()
    if size != expected_size or digest.hexdigest() != expected_digest:
        raise BackupError("Stored backup verification failed: size or SHA-256 mismatch")
    print(f"R2 backup verified: {key}; bytes={size}; sha256={expected_digest}")
    return {"object_key": key, "bytes": size, "sha256": expected_digest}


def run_backup(environ=None, backup_dir=None, collector=None, uploader=None):
    environ = os.environ if environ is None else environ
    url = database_url(environ)
    settings = r2_settings(environ)
    backup = (collector or collect_snapshot)(url)
    directory = BACKUP_DIR if backup_dir is None else Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    filename = directory / f"backup_{backup['timestamp']}.json"
    with filename.open("x", encoding="utf-8") as handle:
        json.dump(backup, handle, indent=2, default=str, allow_nan=False)
    result = (uploader or upload_to_r2)(filename, settings)
    print(json.dumps({"status": "success", "source_database": backup["source_database"],
                      "table_counts": backup["table_counts"], **result}))
    return result


def main():
    try:
        run_backup()
    except Exception as exc:
        # Database/SDK exception strings can contain connection URLs or secrets.
        message = str(exc) if isinstance(exc, BackupError) else type(exc).__name__
        print("Backup failed: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
