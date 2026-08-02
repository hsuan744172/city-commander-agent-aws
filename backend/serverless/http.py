"""Small API Gateway HTTP API (payload v2) request/response adapter.

This module deliberately has no FastAPI or Mangum dependency.  Every handler uses
one stable error envelope and returns the dictionary shape expected by API Gateway
HTTP API and Lambda Function URLs.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import math
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, unquote
from uuid import uuid4

logger = logging.getLogger(__name__)

_JSON_HEADERS = {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "access-control-allow-origin": "*",
}
_BINARY_HEADERS = {
    "cache-control": "no-store",
    "access-control-allow-origin": "*",
}


class HTTPError(ValueError):
    """A safe client-facing error that may be rendered without leaking internals."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code)
        self.message = str(message)
        self.details = list(details or ())
        self.headers = dict(headers or {})


class Request:
    """Normalized API Gateway payload-v2 request."""

    def __init__(self, event: Mapping[str, Any], context: Any = None) -> None:
        if not isinstance(event, Mapping):
            raise HTTPError(400, "REQUEST_EVENT_INVALID", "請求事件格式無效")
        self.event = dict(event)
        self.context = context

        request_context = self.event.get("requestContext") or {}
        http_context = request_context.get("http") or {}
        self.method = str(
            http_context.get("method")
            or self.event.get("httpMethod")
            or "GET"
        ).upper()
        raw_path = str(
            self.event.get("rawPath")
            or http_context.get("path")
            or self.event.get("path")
            or "/"
        )
        decoded_path = unquote(raw_path.split("?", 1)[0])
        self.path = "/" + decoded_path.strip("/") if decoded_path != "/" else "/"

        self.headers = {
            str(key).lower(): str(value)
            for key, value in (self.event.get("headers") or {}).items()
            if value is not None
        }
        cookies = self.event.get("cookies")
        if isinstance(cookies, list) and cookies and "cookie" not in self.headers:
            self.headers["cookie"] = "; ".join(str(item) for item in cookies)

        raw_query = str(self.event.get("rawQueryString") or "")
        if raw_query:
            parsed = parse_qs(raw_query, keep_blank_values=True, strict_parsing=False)
            self.query_all = {str(key): [str(v) for v in values] for key, values in parsed.items()}
        else:
            self.query_all = {
                str(key): [str(value)]
                for key, value in (self.event.get("queryStringParameters") or {}).items()
                if value is not None
            }
        self.query = {key: values[-1] if values else "" for key, values in self.query_all.items()}

        raw_body = self.event.get("body")
        if raw_body is None:
            self.body = b""
        elif self.event.get("isBase64Encoded"):
            try:
                self.body = base64.b64decode(str(raw_body), validate=True)
            except (binascii.Error, ValueError, TypeError) as exc:
                raise HTTPError(
                    400,
                    "REQUEST_BODY_BASE64_INVALID",
                    "請求內容不是有效的 base64",
                ) from exc
        elif isinstance(raw_body, bytes):
            self.body = raw_body
        else:
            self.body = str(raw_body).encode("utf-8")

        self.request_id = str(
            request_context.get("requestId")
            or getattr(context, "aws_request_id", "")
            or uuid4().hex
        )

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(part for part in self.path.strip("/").split("/") if part)

    def route_parts(self, *prefixes: str) -> tuple[str, ...]:
        """Return path components after optional deployment prefixes.

        ``api`` is always stripped for compatibility with the existing public
        paths.  A handler-specific prefix (for example ``monitoring`` or
        ``incidents``) may be supplied by the caller.
        """

        parts = list(self.parts)
        if parts and parts[0] == "api":
            parts.pop(0)
        allowed = {prefix.strip("/") for prefix in prefixes if prefix.strip("/")}
        if parts and parts[0] in allowed:
            parts.pop(0)
        return tuple(parts)

    def header(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name.lower(), default)

    def query_value(self, name: str, default: str | None = None) -> str | None:
        return self.query.get(name, default)

    def query_bool(self, name: str, default: bool = False) -> bool:
        value = self.query.get(name)
        if value is None or not value.strip():
            return default
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise HTTPError(
            400,
            "QUERY_BOOLEAN_INVALID",
            f"查詢參數 {name} 必須是 true 或 false",
            details=[{"path": name, "code": "boolean"}],
        )

    def query_int(
        self,
        name: str,
        default: int,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int:
        raw = self.query.get(name)
        if raw is None or not raw.strip():
            value = default
        else:
            try:
                value = int(raw)
            except ValueError as exc:
                raise HTTPError(400, "QUERY_INTEGER_INVALID", f"查詢參數 {name} 必須是整數") from exc
        if minimum is not None and value < minimum:
            raise HTTPError(400, "QUERY_INTEGER_RANGE", f"查詢參數 {name} 不得小於 {minimum}")
        if maximum is not None and value > maximum:
            raise HTTPError(400, "QUERY_INTEGER_RANGE", f"查詢參數 {name} 不得大於 {maximum}")
        return value

    def text(self) -> str:
        try:
            return self.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPError(400, "REQUEST_BODY_ENCODING_INVALID", "JSON 請求內容必須使用 UTF-8") from exc

    def json(self, *, required: bool = True) -> Any:
        if not self.body:
            if required:
                raise HTTPError(400, "REQUEST_BODY_REQUIRED", "請提供 JSON 請求內容")
            return None
        try:
            return json.loads(self.text(), parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPError(400, "REQUEST_JSON_INVALID", "JSON 請求內容無法解析") from exc

    def json_object(self, *, required: bool = True) -> dict[str, Any]:
        value = self.json(required=required)
        if value is None and not required:
            return {}
        if not isinstance(value, dict):
            raise HTTPError(400, "REQUEST_JSON_OBJECT_REQUIRED", "JSON 頂層必須是物件")
        return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
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
        return _jsonable(value.value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _merge_headers(base: Mapping[str, str], extra: Mapping[str, str] | None) -> dict[str, str]:
    headers = {str(key).lower(): str(value) for key, value in base.items()}
    for key, value in (extra or {}).items():
        headers[str(key).lower()] = str(value)
    return headers


def json_response(
    payload: Any,
    status_code: int = 200,
    *,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "statusCode": int(status_code),
        "headers": _merge_headers(_JSON_HEADERS, headers),
        "body": json.dumps(
            _jsonable(payload),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ),
        "isBase64Encoded": False,
    }


def binary_response(
    data: bytes | bytearray,
    content_type: str = "application/octet-stream",
    status_code: int = 200,
    *,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("binary response data must be bytes")
    merged = _merge_headers(_BINARY_HEADERS, headers)
    merged["content-type"] = content_type
    return {
        "statusCode": int(status_code),
        "headers": merged,
        "body": base64.b64encode(bytes(data)).decode("ascii"),
        "isBase64Encoded": True,
    }


def redirect_response(
    location: str,
    status_code: int = 307,
    *,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    merged = _merge_headers(_BINARY_HEADERS, headers)
    merged["location"] = str(location)
    merged["content-type"] = "application/json; charset=utf-8"
    return {
        "statusCode": int(status_code),
        "headers": merged,
        "body": json.dumps({"location": str(location)}, ensure_ascii=False, separators=(",", ":")),
        "isBase64Encoded": False,
    }


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    request_id: str | None = None,
    details: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the stable public error envelope used by every Lambda handler."""

    trace_id = request_id or uuid4().hex
    return json_response(
        {
            "error": {
                "code": str(code),
                "message": str(message),
                "trace_id": trace_id,
                "details": list(details or ()),
            }
        },
        status_code,
        headers=headers,
    )


def not_found(request: Request) -> dict[str, Any]:
    return error_response(
        404,
        "ROUTE_NOT_FOUND",
        "找不到要求的 API 路徑",
        request_id=request.request_id,
        details=[{"path": request.path, "code": "not_found"}],
    )


def method_not_allowed(request: Request, allowed: str) -> dict[str, Any]:
    return error_response(
        405,
        "METHOD_NOT_ALLOWED",
        "此路徑不支援該 HTTP 方法",
        request_id=request.request_id,
        headers={"allow": allowed},
    )


def invoke(
    event: Mapping[str, Any],
    context: Any,
    dispatcher: Callable[[Request], dict[str, Any]],
) -> dict[str, Any]:
    """Parse, dispatch, and safely map exceptions to public HTTP responses."""

    request: Request | None = None
    try:
        request = Request(event, context)
        return dispatcher(request)
    except HTTPError as exc:
        return error_response(
            exc.status_code,
            exc.code,
            exc.message,
            request_id=request.request_id if request else None,
            details=exc.details,
            headers=exc.headers,
        )
    except Exception:
        request_id = request.request_id if request else getattr(context, "aws_request_id", None)
        logger.exception("Unhandled Lambda HTTP error trace_id=%s", request_id)
        return error_response(
            500,
            "INTERNAL_ERROR",
            "伺服器暫時無法完成請求",
            request_id=request_id,
        )


_PATH_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def require_path_token(value: str, name: str) -> str:
    text = str(value or "").strip()
    if not _PATH_TOKEN.fullmatch(text):
        raise HTTPError(400, "PATH_PARAMETER_INVALID", f"路徑參數 {name} 格式無效")
    return text


__all__ = [
    "HTTPError",
    "Request",
    "binary_response",
    "error_response",
    "invoke",
    "json_response",
    "method_not_allowed",
    "not_found",
    "redirect_response",
    "require_path_token",
]
