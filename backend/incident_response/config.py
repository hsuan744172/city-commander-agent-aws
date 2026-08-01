"""Versioned configuration for the incident response v1 API."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

CONTRACT_VERSION: Final[str] = "1.0"
INCIDENT_V1_FEATURE_FLAG: Final[str] = "INCIDENT_V1_ENABLED"

_ENABLED_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})


def is_incident_v1_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether the opt-in incident response v1 feature is enabled."""

    source = os.environ if environ is None else environ
    value = source.get(INCIDENT_V1_FEATURE_FLAG, "")
    return value.strip().casefold() in _ENABLED_VALUES
