"""Cloudflare R2 (S3-compatible) object storage for report PDFs. Callers check `settings.r2_enabled` first."""

import logging
from functools import lru_cache

import boto3
from botocore.config import Config

from app.common.config import settings

log = logging.getLogger(__name__)


@lru_cache
def _client(account_id: str, access_key_id: str, secret_access_key: str):
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def _s3():
    return _client(settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key)


def put_pdf(key: str, data: bytes) -> None:
    _s3().put_object(Bucket=settings.r2_bucket, Key=key, Body=data, ContentType="application/pdf")


def get_pdf(key: str) -> bytes:
    return _s3().get_object(Bucket=settings.r2_bucket, Key=key)["Body"].read()


def signed_url(key: str, seconds: int = 300, disposition: str | None = None) -> str:
    """A temporary download link. `disposition` sets the Content-Disposition (file name) the browser sees."""
    params = {"Bucket": settings.r2_bucket, "Key": key}
    if disposition:
        params["ResponseContentDisposition"] = disposition
    return _s3().generate_presigned_url("get_object", Params=params, ExpiresIn=seconds)


def delete(key: str) -> None:
    """Best effort: a failed delete leaves an orphan object, which must not fail the request that removed the row."""
    try:
        _s3().delete_object(Bucket=settings.r2_bucket, Key=key)
    except Exception:
        log.exception("Could not delete %s from R2", key)
