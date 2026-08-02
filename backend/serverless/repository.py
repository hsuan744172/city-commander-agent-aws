"""AWS persistence boundary for the native Lambda runtime.

Production state is never silently redirected to process memory.  In-memory
storage is available only when ``SERVERLESS_LOCAL_MODE=true`` is explicitly set,
which is useful for import/smoke checks and local handler invocations.
"""

from __future__ import annotations

import base64
import copy
import json
import math
import os
import threading
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

import boto3
from botocore.exceptions import BotoCoreError, ClientError

LOCAL_MODE_ENV = "SERVERLESS_LOCAL_MODE"
STATE_TABLE_ENV = "STATE_TABLE"
DATA_BUCKET_ENV = "DATA_BUCKET"
JOB_QUEUE_URL_ENV = "JOB_QUEUE_URL"
GSI_NAME_ENV = "STATE_TABLE_GSI1"
DEFAULT_GSI_NAME = "gsi1"
JOB_PREFIX = "runtime/jobs"


class RepositoryError(RuntimeError):
    """Base error for persistence and queue operations."""


class RepositoryConfigurationError(RepositoryError):
    """Required AWS configuration is missing."""


class RepositoryIOError(RepositoryError):
    """An explicitly configured AWS resource could not complete an operation."""


def _env_true(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_jsonable(value: Any) -> Any:
    """Recursively project arbitrary application values into safe JSON data."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return to_jsonable(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value))
    if hasattr(value, "item"):
        try:
            return to_jsonable(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _to_dynamo(value: Any) -> Any:
    value = to_jsonable(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _to_dynamo(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(item) for item in value]
    return value


def json_bytes(value: Any) -> bytes:
    return json.dumps(
        to_jsonable(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class _LocalStore:
    lock = threading.RLock()
    items: dict[tuple[str, str], dict[str, Any]] = {}
    objects: dict[str, bytes] = {}
    queue: list[dict[str, Any]] = []


class Repository:
    """DynamoDB, S3, and SQS repository with an explicit local smoke mode."""

    def __init__(self, *, local_mode: bool | None = None) -> None:
        self.local_mode = _env_true(LOCAL_MODE_ENV) if local_mode is None else bool(local_mode)
        self.state_table = (os.environ.get(STATE_TABLE_ENV) or "").strip()
        self.data_bucket = (os.environ.get(DATA_BUCKET_ENV) or "").strip()
        self.job_queue_url = (os.environ.get(JOB_QUEUE_URL_ENV) or "").strip()
        self.gsi_name = (os.environ.get(GSI_NAME_ENV) or DEFAULT_GSI_NAME).strip()
        self.region = (os.environ.get("APP_AWS_REGION") or os.environ.get("AWS_REGION") or "").strip() or None
        self._table_resource = None
        self._s3_client = None
        self._sqs_client = None

        if not self.local_mode and not any((self.state_table, self.data_bucket, self.job_queue_url)):
            raise RepositoryConfigurationError(
                "AWS resources are not configured; set STATE_TABLE/DATA_BUCKET/JOB_QUEUE_URL "
                "or explicitly set SERVERLESS_LOCAL_MODE=true for a local smoke run"
            )

    @property
    def mode(self) -> str:
        return "local-memory" if self.local_mode else "aws"

    def configuration(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "state_table_configured": bool(self.state_table),
            "data_bucket_configured": bool(self.data_bucket),
            "job_queue_configured": bool(self.job_queue_url),
        }

    def _require(self, value: str, env_name: str) -> str:
        if self.local_mode:
            return value
        if not value:
            raise RepositoryConfigurationError(f"{env_name} is required for this operation")
        return value

    def _table(self):
        table_name = self._require(self.state_table, STATE_TABLE_ENV)
        if self._table_resource is None:
            resource = boto3.resource("dynamodb", region_name=self.region)
            self._table_resource = resource.Table(table_name)
        return self._table_resource

    def _s3(self):
        self._require(self.data_bucket, DATA_BUCKET_ENV)
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.region)
        return self._s3_client

    def _sqs(self):
        self._require(self.job_queue_url, JOB_QUEUE_URL_ENV)
        if self._sqs_client is None:
            self._sqs_client = boto3.client("sqs", region_name=self.region)
        return self._sqs_client

    @staticmethod
    def _public_item(item: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None
        return {
            key: to_jsonable(value)
            for key, value in item.items()
            if key not in {"pk", "sk", "gsi1pk", "gsi1sk"}
        }

    def _get_item(self, pk: str, sk: str) -> dict[str, Any] | None:
        if self.local_mode:
            with _LocalStore.lock:
                item = _LocalStore.items.get((pk, sk))
                return copy.deepcopy(item) if item is not None else None
        try:
            result = self._table().get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True)
            return result.get("Item")
        except (BotoCoreError, ClientError, OSError) as exc:
            raise RepositoryIOError(f"DynamoDB get_item failed: {type(exc).__name__}") from exc

    def _put_item(self, item: Mapping[str, Any], *, create_only: bool = False) -> None:
        pk, sk = str(item["pk"]), str(item["sk"])
        if self.local_mode:
            with _LocalStore.lock:
                if create_only and (pk, sk) in _LocalStore.items:
                    raise RepositoryError(f"item already exists: {pk}/{sk}")
                _LocalStore.items[(pk, sk)] = copy.deepcopy(to_jsonable(item))
            return
        kwargs: dict[str, Any] = {"Item": _to_dynamo(dict(item))}
        if create_only:
            kwargs["ConditionExpression"] = "attribute_not_exists(pk) AND attribute_not_exists(sk)"
        try:
            self._table().put_item(**kwargs)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise RepositoryIOError(f"DynamoDB put_item failed: {type(exc).__name__}") from exc

    # -- Clock -------------------------------------------------------------

    def get_clock(self) -> dict[str, Any] | None:
        return self._public_item(self._get_item("STATE", "CLOCK"))

    def put_clock(self, state: Mapping[str, Any]) -> dict[str, Any]:
        item = {
            "pk": "STATE",
            "sk": "CLOCK",
            "entity_type": "clock",
            **to_jsonable(dict(state)),
            "updated_at": utc_now_iso(),
        }
        self._put_item(item)
        return self._public_item(item) or {}

    # -- Jobs --------------------------------------------------------------

    def create_job(self, job_id: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
        submitted_at = str(metadata.get("submitted_at") or utc_now_iso())
        item = {
            "pk": f"JOB#{job_id}",
            "sk": "METADATA",
            "gsi1pk": "JOBS",
            "gsi1sk": f"{submitted_at}#{job_id}",
            "entity_type": "job",
            "job_id": job_id,
            "status": "queued",
            "submitted_at": submitted_at,
            "updated_at": submitted_at,
            "report_available": False,
            **to_jsonable(dict(metadata)),
        }
        self._put_item(item, create_only=True)
        return self._public_item(item) or {}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self._public_item(self._get_item(f"JOB#{job_id}", "METADATA"))

    def claim_job(self, job_id: str, worker_id: str) -> dict[str, Any] | None:
        """Atomically move one queued job into baseline processing.

        A duplicate SQS delivery receives ``None`` and performs no Agent work.
        The claim is intentionally conditional in DynamoDB so separate warm
        Lambda environments cannot both process the same queue message.
        """

        normalized_worker = str(worker_id or "").strip()
        if not normalized_worker:
            raise ValueError("worker_id is required")
        claimed_at = utc_now_iso()
        key = (f"JOB#{job_id}", "METADATA")
        if self.local_mode:
            with _LocalStore.lock:
                item = _LocalStore.items.get(key)
                if item is None:
                    raise RepositoryError(f"job not found: {job_id}")
                if item.get("status") != "queued":
                    return None
                item.update(
                    {
                        "status": "processing_baseline",
                        "worker_id": normalized_worker,
                        "processing_started_at": claimed_at,
                        "updated_at": claimed_at,
                    }
                )
                _LocalStore.items[key] = item
                return self._public_item(copy.deepcopy(item)) or {}
        try:
            result = self._table().update_item(
                Key={"pk": key[0], "sk": key[1]},
                UpdateExpression=(
                    "SET #status = :processing, worker_id = :worker, "
                    "processing_started_at = :claimed, updated_at = :claimed"
                ),
                ConditionExpression="#status = :queued",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":queued": "queued",
                    ":processing": "processing_baseline",
                    ":worker": normalized_worker,
                    ":claimed": claimed_at,
                },
                ReturnValues="ALL_NEW",
            )
            return self._public_item(result.get("Attributes")) or {}
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code == "ConditionalCheckFailedException":
                return None
            raise RepositoryIOError(f"DynamoDB claim_job failed: {code or type(exc).__name__}") from exc
        except (BotoCoreError, OSError) as exc:
            raise RepositoryIOError(f"DynamoDB claim_job failed: {type(exc).__name__}") from exc

    def update_job(self, job_id: str, **changes: Any) -> dict[str, Any]:
        updates = {**to_jsonable(changes), "updated_at": utc_now_iso()}
        if self.local_mode:
            key = (f"JOB#{job_id}", "METADATA")
            with _LocalStore.lock:
                item = _LocalStore.items.get(key)
                if item is None:
                    raise RepositoryError(f"job not found: {job_id}")
                item.update(copy.deepcopy(updates))
                _LocalStore.items[key] = item
                return self._public_item(copy.deepcopy(item)) or {}

        expression_names: dict[str, str] = {}
        expression_values: dict[str, Any] = {}
        assignments: list[str] = []
        for index, (key, value) in enumerate(updates.items()):
            name_token = f"#n{index}"
            value_token = f":v{index}"
            expression_names[name_token] = key
            expression_values[value_token] = _to_dynamo(value)
            assignments.append(f"{name_token} = {value_token}")
        try:
            result = self._table().update_item(
                Key={"pk": f"JOB#{job_id}", "sk": "METADATA"},
                UpdateExpression="SET " + ", ".join(assignments),
                ExpressionAttributeNames=expression_names,
                ExpressionAttributeValues=expression_values,
                ConditionExpression="attribute_exists(pk) AND attribute_exists(sk)",
                ReturnValues="ALL_NEW",
            )
            return self._public_item(result.get("Attributes")) or {}
        except (BotoCoreError, ClientError, OSError) as exc:
            raise RepositoryIOError(f"DynamoDB update_item failed: {type(exc).__name__}") from exc

    def list_jobs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 100))
        if self.local_mode:
            with _LocalStore.lock:
                items = [
                    copy.deepcopy(item)
                    for item in _LocalStore.items.values()
                    if item.get("gsi1pk") == "JOBS"
                ]
            items.sort(key=lambda item: str(item.get("gsi1sk") or ""), reverse=True)
            return [self._public_item(item) or {} for item in items[:bounded]]
        try:
            from boto3.dynamodb.conditions import Key

            result = self._table().query(
                IndexName=self.gsi_name,
                KeyConditionExpression=Key("gsi1pk").eq("JOBS"),
                ScanIndexForward=False,
                Limit=bounded,
            )
            return [self._public_item(item) or {} for item in result.get("Items", [])]
        except (BotoCoreError, ClientError, OSError) as exc:
            raise RepositoryIOError(f"DynamoDB GSI query failed: {type(exc).__name__}") from exc

    # -- Chat --------------------------------------------------------------

    def get_chat(self, session_id: str) -> list[Any]:
        item = self._get_item(f"CHAT#{session_id}", "SESSION")
        if not item:
            return []
        history = to_jsonable(item.get("history") or [])
        return history if isinstance(history, list) else []

    def put_chat(self, session_id: str, history: list[Any]) -> None:
        now = utc_now_iso()
        self._put_item(
            {
                "pk": f"CHAT#{session_id}",
                "sk": "SESSION",
                "entity_type": "chat",
                "session_id": session_id,
                "history": to_jsonable(history),
                "updated_at": now,
            }
        )

    def delete_chat(self, session_id: str) -> None:
        pk, sk = f"CHAT#{session_id}", "SESSION"
        if self.local_mode:
            with _LocalStore.lock:
                _LocalStore.items.pop((pk, sk), None)
            return
        try:
            self._table().delete_item(Key={"pk": pk, "sk": sk})
        except (BotoCoreError, ClientError, OSError) as exc:
            raise RepositoryIOError(f"DynamoDB delete_item failed: {type(exc).__name__}") from exc

    # -- S3 job documents -------------------------------------------------

    @staticmethod
    def job_key(job_id: str, filename: str) -> str:
        return f"{JOB_PREFIX}/{job_id}/{filename}"

    def _put_object_json(self, key: str, value: Any) -> None:
        body = json_bytes(value)
        if self.local_mode:
            with _LocalStore.lock:
                _LocalStore.objects[key] = body
            return
        try:
            self._s3().put_object(
                Bucket=self._require(self.data_bucket, DATA_BUCKET_ENV),
                Key=key,
                Body=body,
                ContentType="application/json",
                CacheControl="no-store",
                ServerSideEncryption="AES256",
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise RepositoryIOError(f"S3 put_object failed: {type(exc).__name__}") from exc

    def _get_object_json(self, key: str, *, required: bool) -> Any:
        if self.local_mode:
            with _LocalStore.lock:
                body = _LocalStore.objects.get(key)
            if body is None:
                if required:
                    raise RepositoryError(f"S3 object not found: {key}")
                return None
        else:
            try:
                result = self._s3().get_object(
                    Bucket=self._require(self.data_bucket, DATA_BUCKET_ENV),
                    Key=key,
                )
                body = result["Body"].read()
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in {"NoSuchKey", "404", "NotFound"} and not required:
                    return None
                raise RepositoryIOError(f"S3 get_object failed: {code or type(exc).__name__}") from exc
            except (BotoCoreError, OSError) as exc:
                raise RepositoryIOError(f"S3 get_object failed: {type(exc).__name__}") from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RepositoryIOError(f"S3 object is not valid JSON: {key}") from exc

    def put_job_request(self, job_id: str, request: Mapping[str, Any]) -> None:
        self._put_object_json(self.job_key(job_id, "request.json"), request)

    def get_job_request(self, job_id: str) -> dict[str, Any]:
        value = self._get_object_json(self.job_key(job_id, "request.json"), required=True)
        if not isinstance(value, dict):
            raise RepositoryIOError("job request JSON must be an object")
        return value

    def put_job_result(self, job_id: str, result: Mapping[str, Any]) -> None:
        self._put_object_json(self.job_key(job_id, "result.json"), result)

    def get_job_result(self, job_id: str) -> dict[str, Any] | None:
        value = self._get_object_json(self.job_key(job_id, "result.json"), required=False)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise RepositoryIOError("job result JSON must be an object")
        return value

    # -- Queue -------------------------------------------------------------

    def enqueue_job(self, job_id: str) -> str:
        message = {"job_id": job_id}
        if self.local_mode:
            with _LocalStore.lock:
                _LocalStore.queue.append(copy.deepcopy(message))
                return f"local-{len(_LocalStore.queue)}"
        try:
            result = self._sqs().send_message(
                QueueUrl=self._require(self.job_queue_url, JOB_QUEUE_URL_ENV),
                MessageBody=json.dumps(message, separators=(",", ":")),
            )
            return str(result.get("MessageId") or "")
        except (BotoCoreError, ClientError, OSError) as exc:
            raise RepositoryIOError(f"SQS send_message failed: {type(exc).__name__}") from exc


_repository: Repository | None = None
_repository_lock = threading.Lock()


def get_repository() -> Repository:
    global _repository
    if _repository is None:
        with _repository_lock:
            if _repository is None:
                _repository = Repository()
    return _repository


def reset_repository() -> None:
    """Clear the process singleton; intended for local smoke tooling."""

    global _repository
    with _repository_lock:
        _repository = None


__all__ = [
    "DATA_BUCKET_ENV",
    "JOB_QUEUE_URL_ENV",
    "LOCAL_MODE_ENV",
    "Repository",
    "RepositoryConfigurationError",
    "RepositoryError",
    "RepositoryIOError",
    "STATE_TABLE_ENV",
    "get_repository",
    "json_bytes",
    "reset_repository",
    "to_jsonable",
    "utc_now_iso",
]
