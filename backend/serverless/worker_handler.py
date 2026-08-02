"""Idempotent SQS worker for asynchronous incident commander jobs."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from backend.agents import architect

from .public_payload import sanitize_public
from .repository import Repository, RepositoryError, get_repository, utc_now_iso

logger = logging.getLogger(__name__)
BUDGET_SECONDS = 60.0
_AI_SOURCES = frozenset({"ai_generated", "ai_generated_partial"})


def _usable_baseline(report: object) -> bool:
    if not isinstance(report, Mapping):
        return False
    advisories = report.get("advisories")
    if not isinstance(advisories, list) or not advisories:
        return False
    try:
        return int(report.get("processed") or 0) > 0
    except (TypeError, ValueError):
        return False


def _ai_succeeded(report: object) -> bool:
    if not isinstance(report, Mapping) or report.get("status") != "completed":
        return False
    advisories = report.get("advisories")
    if not isinstance(advisories, list) or not advisories:
        return False
    for advisory in advisories:
        if not isinstance(advisory, Mapping) or advisory.get("error"):
            return False
        if advisory.get("ai_narrative_source") not in _AI_SOURCES:
            return False
    return True


def _metrics(
    report: Mapping[str, Any],
    *,
    started: float,
    deadline_fallback: bool,
    fallback_reason: str = "",
) -> dict[str, Any]:
    elapsed = time.monotonic() - started
    projected = dict(sanitize_public(report))
    projected["elapsed_seconds"] = round(elapsed, 2)
    projected["elapsed_ms"] = int(elapsed * 1000)
    projected["budget_seconds"] = int(BUDGET_SECONDS)
    projected["within_budget"] = elapsed <= BUDGET_SECONDS
    projected["deadline_fallback"] = bool(deadline_fallback)
    if deadline_fallback:
        projected["fallback_reason"] = fallback_reason or "AI 強化未完成，使用確定性 SOP 方案"
    else:
        projected.pop("fallback_reason", None)
    return projected


def _failed_report(started: float, job_id: str) -> dict[str, Any]:
    elapsed = time.monotonic() - started
    return {
        "status": "failed",
        "job_id": job_id,
        "advisories": [],
        "elapsed_seconds": round(elapsed, 2),
        "elapsed_ms": int(elapsed * 1000),
        "budget_seconds": int(BUDGET_SECONDS),
        "within_budget": elapsed <= BUDGET_SECONDS,
        "deadline_fallback": False,
        "failure_code": "deterministic_processing_failed",
    }


def _mark_failed(repository: Repository, job_id: str, started: float) -> None:
    report = _failed_report(started, job_id)
    repository.put_job_result(job_id, report)
    repository.update_job(
        job_id,
        status="failed",
        report_available=True,
        completed_at=utc_now_iso(),
        elapsed_seconds=report["elapsed_seconds"],
        budget_seconds=int(BUDGET_SECONDS),
        within_budget=report["within_budget"],
        deadline_fallback=False,
        failure_code=report["failure_code"],
    )


def _process_job(job_id: str, worker_id: str, repository: Repository) -> None:
    claimed = repository.claim_job(job_id, worker_id)
    if claimed is None:
        # Completed, failed, or currently owned by another SQS delivery.
        return
    started = time.monotonic()
    try:
        request = repository.get_job_request(job_id)
        incidents = request.get("incidents")
        if not isinstance(incidents, list) or not incidents:
            raise ValueError("job request has no incidents")
        session_id = str(request.get("session_id") or job_id)
        sim_time = str(request.get("sim_time") or "")

        baseline = architect.run_commander(
            {"incidents": incidents}, session_id, sim_time, allow_ai=False
        )
        if not _usable_baseline(baseline):
            logger.error("Deterministic baseline produced no usable advisory job=%s", job_id)
            _mark_failed(repository, job_id, started)
            return

        pending = _metrics(
            baseline,
            started=started,
            deadline_fallback=True,
            fallback_reason="AI 強化處理中，暫提供確定性 SOP 方案",
        )
        repository.put_job_result(job_id, pending)
        repository.update_job(
            job_id,
            status="processing_ai",
            report_available=True,
            baseline_completed_at=utc_now_iso(),
            elapsed_seconds=pending["elapsed_seconds"],
            budget_seconds=int(BUDGET_SECONDS),
            within_budget=pending["within_budget"],
        )

        fallback_reason = ""
        ai_report: Mapping[str, Any] | None = None
        if time.monotonic() - started >= BUDGET_SECONDS:
            fallback_reason = "確定性方案完成後已無 AI 強化時間"
        else:
            try:
                candidate = architect.run_commander(
                    {"incidents": incidents}, session_id, sim_time, allow_ai=True
                )
                if _ai_succeeded(candidate):
                    ai_report = candidate
                else:
                    fallback_reason = "AI 處理未完成，已保留確定性 SOP 方案"
            except Exception:
                logger.exception("AI commander failed; retaining baseline job=%s", job_id)
                fallback_reason = "AI 處理異常，已保留確定性 SOP 方案"

        elapsed = time.monotonic() - started
        if ai_report is not None and elapsed <= BUDGET_SECONDS:
            final = _metrics(
                ai_report,
                started=started,
                deadline_fallback=False,
            )
        else:
            if ai_report is not None and elapsed > BUDGET_SECONDS:
                fallback_reason = "AI 處理超過 60 秒期限，已回傳確定性 SOP 方案"
            final = _metrics(
                baseline,
                started=started,
                deadline_fallback=True,
                fallback_reason=fallback_reason,
            )
        repository.put_job_result(job_id, final)
        repository.update_job(
            job_id,
            status="completed",
            report_available=True,
            completed_at=utc_now_iso(),
            elapsed_seconds=final["elapsed_seconds"],
            budget_seconds=int(BUDGET_SECONDS),
            within_budget=final["within_budget"],
            deadline_fallback=final["deadline_fallback"],
        )
    except (RepositoryError, OSError):
        # Persistence failures are retryable by SQS; leave the claimed state for
        # operators rather than replacing it with a misleading application error.
        raise
    except Exception:
        logger.exception("Incident job failed before a baseline was available job=%s", job_id)
        _mark_failed(repository, job_id, started)


def _job_id(record: Mapping[str, Any]) -> str:
    body = record.get("body")
    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError as exc:
        raise ValueError("SQS body is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("SQS body must be an object")
    value = str(payload.get("job_id") or "").strip()
    if not value or len(value) > 160:
        raise ValueError("SQS body has no valid job_id")
    return value


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    repository = get_repository()
    failures: list[dict[str, str]] = []
    records = event.get("Records") if isinstance(event, Mapping) else None
    for index, record in enumerate(records if isinstance(records, list) else []):
        if not isinstance(record, Mapping):
            continue
        message_id = str(record.get("messageId") or f"record-{index}")
        worker_id = str(
            getattr(context, "aws_request_id", "")
            or f"worker-{uuid4().hex}"
        )
        try:
            _process_job(_job_id(record), worker_id, repository)
        except Exception:
            logger.exception("Retryable SQS record failure message_id=%s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


__all__ = ["lambda_handler"]
