"""Foundation tests for the incident response v1 package."""

from hypothesis import settings

from backend.incident_response import (
    CONTRACT_VERSION,
    INCIDENT_V1_FEATURE_FLAG,
    is_incident_v1_enabled,
)


def test_contract_version_is_v1() -> None:
    assert CONTRACT_VERSION == "1.0"


def test_feature_flag_is_opt_in() -> None:
    assert INCIDENT_V1_FEATURE_FLAG == "INCIDENT_V1_ENABLED"
    assert is_incident_v1_enabled({}) is False
    assert is_incident_v1_enabled({INCIDENT_V1_FEATURE_FLAG: "false"}) is False
    assert is_incident_v1_enabled({INCIDENT_V1_FEATURE_FLAG: "unexpected"}) is False


def test_feature_flag_accepts_explicit_enabled_values() -> None:
    for value in ("1", "true", "TRUE", " yes ", "On"):
        assert is_incident_v1_enabled({INCIDENT_V1_FEATURE_FLAG: value}) is True


def test_hypothesis_profile_is_reproducible() -> None:
    profile = settings.get_profile("incident_response")

    assert profile.derandomize is True
    assert profile.database is None
    assert profile.deadline is None
    assert profile.max_examples == 100
