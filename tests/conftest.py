"""Shared deterministic test configuration."""

from __future__ import annotations

import os

from hypothesis import settings

HYPOTHESIS_PROFILE = "incident_response"

settings.register_profile(
    HYPOTHESIS_PROFILE,
    deadline=None,
    derandomize=True,
    database=None,
    max_examples=100,
    print_blob=True,
)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", HYPOTHESIS_PROFILE))
