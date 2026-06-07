"""Cloudflare R2 storage helpers for Heinlin Field Ops Core 1.0.
Safe design: if R2 env vars are missing, uploads are blocked instead of silently saving temporary local files.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import BinaryIO, Optional

import boto3
from botocore.client import Config


@dataclass(frozen=True)
class R2Settings:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    public_base_url: Optional[str] = None

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


def get_r2_settings() -> Optional[R2Settings]:
    account_id = os.getenv("CLOUDFLARE_R2_ACCOUNT_ID", "").strip()
    access_key_id = os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "").strip()
    secret_access_key = os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "").strip()
    bucket = os.getenv("CLOUDFLARE_R2_BUCKET", "").strip()
    public_base_url = os.getenv("CLOUDFLARE_R2_PUBLIC_BASE_URL", "").strip() or None
    if not all([account_id, access_key_id, secret_access_key, bucket]):
        return None
    return R2Settings(account_id, access_key_id, secret_access_key, bucket, public_base_url)


def r2_client(settings: R2Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def build_photo_key(filename: str, client_id: Optional[int] = None, property_id: Optional[int] = None) -> str:
    safe_name = filename.replace("\\", "_").replace("/", "_").strip() or "upload.jpg"
    prefix = "field-photos"
    if client_id:
        prefix += f"/client-{client_id}"
    if property_id:
        prefix += f"/property-{property_id}"
    return f"{prefix}/{uuid.uuid4().hex}-{safe_name}"


def upload_fileobj(fileobj: BinaryIO, *, key: str, content_type: str = "application/octet-stream") -> dict:
    settings = get_r2_settings()
    if settings is None:
        raise RuntimeError("Cloudflare R2 is not configured. Add R2 env vars in Render before enabling permanent photo uploads.")
    client = r2_client(settings)
    client.upload_fileobj(fileobj, settings.bucket, key, ExtraArgs={"ContentType": content_type})
    public_url = f"{settings.public_base_url.rstrip('/')}/{key}" if settings.public_base_url else None
    return {"bucket": settings.bucket, "key": key, "public_url": public_url}
