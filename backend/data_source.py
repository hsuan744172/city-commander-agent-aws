"""S3-first data access with the packaged ``data/`` directory as fallback."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DATA_DIR = PROJECT_ROOT / "data"
S3_CACHE_DIR = Path(os.environ.get("S3_DATA_CACHE_DIR", "/tmp/city-commander-data"))

_lock = threading.Lock()
_records: dict[str, dict] = {}
_s3_client = None


def _bucket() -> str:
    return (os.environ.get("S3_DATA_BUCKET") or "").strip()


def _prefix() -> str:
    return (os.environ.get("S3_DATA_PREFIX") or "data").strip("/")


def _refresh_seconds() -> float:
    raw = (os.environ.get("S3_DATA_REFRESH_SECONDS") or "60").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("S3_DATA_REFRESH_SECONDS 無效，改用 60 秒")
        return 60.0


def _client():
    global _s3_client
    if _s3_client is None:
        region = os.environ.get("APP_AWS_REGION") or os.environ.get("AWS_REGION")
        _s3_client = boto3.client("s3", region_name=region)
    return _s3_client


def _object_key(filename: str) -> str:
    prefix = _prefix()
    return f"{prefix}/{filename}" if prefix else filename


def get_data_path(filename: str) -> Path:
    """Return an S3-backed local cache path when readable, otherwise local data."""
    safe_name = Path(filename).name
    if safe_name != filename:
        raise ValueError(f"資料檔名不可包含路徑: {filename}")

    local_path = LOCAL_DATA_DIR / safe_name
    bucket = _bucket()
    if not bucket:
        return local_path

    now = time.monotonic()
    refresh_seconds = _refresh_seconds()
    with _lock:
        record = _records.get(safe_name)
        if record and now - record["checked_at"] < refresh_seconds:
            return record["path"]

        key = _object_key(safe_name)
        target = S3_CACHE_DIR / safe_name
        try:
            metadata = _client().head_object(Bucket=bucket, Key=key)
            fingerprint = (
                metadata.get("VersionId"),
                metadata.get("ETag"),
                metadata.get("ContentLength"),
                metadata.get("LastModified"),
            )
            if not target.exists() or not record or record.get("fingerprint") != fingerprint:
                S3_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                temp_path = target.with_name(f".{target.name}.{os.getpid()}.tmp")
                try:
                    _client().download_file(bucket, key, str(temp_path))
                    os.replace(temp_path, target)
                finally:
                    temp_path.unlink(missing_ok=True)
                logger.info("資料來源使用 S3: s3://%s/%s", bucket, key)

            _records[safe_name] = {
                "checked_at": now,
                "fingerprint": fingerprint,
                "path": target,
                "source": "s3",
            }
            return target
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.warning(
                "S3 資料讀取失敗，改用本地檔案 %s: %s: %s",
                safe_name,
                type(exc).__name__,
                exc,
            )
            _records[safe_name] = {
                "checked_at": now,
                "fingerprint": None,
                "path": local_path,
                "source": "local",
            }
            return local_path


def get_data_source_name(filename: str) -> str:
    """Return the source selected by the latest resolution for a data file."""
    safe_name = Path(filename).name
    with _lock:
        record = _records.get(safe_name)
        return record["source"] if record else "local"


def data_source_status() -> dict:
    """Return current configuration and resolved source states without network I/O."""
    with _lock:
        files = {name: record["source"] for name, record in _records.items()}
    return {
        "s3_configured": bool(_bucket()),
        "bucket": _bucket() or None,
        "prefix": _prefix(),
        "files": files,
    }
