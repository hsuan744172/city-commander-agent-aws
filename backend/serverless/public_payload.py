"""Projection helpers for public Lambda responses and persisted reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from .repository import to_jsonable

# Keys are normalized to lowercase alphanumerics before comparison.  The list is
# intentionally about raw model/provider material; structured ``decision_trace``
# and evidence fields are not removed.
_PRIVATE_KEYS = frozenset(
    {
        "aireasoning",
        "chainofthought",
        "internalreasoning",
        "messages",
        "modelinput",
        "modeloutput",
        "providerresponse",
        "raw",
        "rawresponse",
        "reasoning",
        "reasoningcontent",
        "responsemetadata",
        "scratchpad",
        "signature",
        "thinking",
        "thinkingtext",
        "toolquality",
        "traceback",
        "vendordetail",
        "vendormetadata",
        "vendorprivate",
    }
)
_PRIVATE_PREFIXES = ("vendor", "providerprivate")


def _normalized_key(value: object) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _is_private_key(value: object) -> bool:
    text = str(value)
    normalized = _normalized_key(text)
    return (
        text.startswith("_")
        or normalized in _PRIVATE_KEYS
        or any(normalized.startswith(prefix) for prefix in _PRIVATE_PREFIXES)
    )


def sanitize_public(value: Any) -> Any:
    """Recursively remove raw chain-of-thought and provider-private fields."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_public(child)
            for key, child in value.items()
            if not _is_private_key(key)
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_public(child) for child in value]
    return to_jsonable(value)


__all__ = ["sanitize_public"]
