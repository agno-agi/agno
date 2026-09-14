from __future__ import annotations

import math
from importlib import metadata
from typing import Any

from pydantic import field_validator
from pydantic_core.core_schema import ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

from agno.utils.log import log_error, log_warning

# Telemetry timeouts above this are capped: larger values overflow the socket
# and lock timeout APIs and would turn a misconfiguration into zero delivery.
MAX_TELEMETRY_TIMEOUT_SECONDS = 3600.0


def _coerce_timeout(name: str, value: Any, default: float, *, zero_allowed: bool) -> float:
    """Turn a timeout setting into a usable float, never raising.

    These settings are read when telemetry first runs, from inside agent, team,
    workflow, eval and AgentOS code paths. A value that cannot be used must not
    make those paths fail, so anything unusable falls back to the default with a
    warning: non-numeric or empty values, nan, inf, and (unless zero is a
    documented setting) zero or negative values. Finite values above the cap
    are clamped.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        log_warning(f"Ignoring {name}={value!r}: not a number, using {default}")
        return default
    if math.isnan(number) or math.isinf(number):
        log_warning(f"Ignoring {name}={value!r}: must be finite, using {default}")
        return default
    if number < 0:
        if zero_allowed:
            return 0.0
        log_warning(f"Ignoring {name}={value!r}: must be positive, using {default}")
        return default
    if number == 0 and not zero_allowed:
        log_warning(f"Ignoring {name}=0: a zero request timeout fails every request, using {default}")
        return default
    if number > MAX_TELEMETRY_TIMEOUT_SECONDS:
        log_warning(f"Capping {name}={value!r} at {MAX_TELEMETRY_TIMEOUT_SECONDS} seconds")
        return MAX_TELEMETRY_TIMEOUT_SECONDS
    return number


class AgnoAPISettings(BaseSettings):
    app_name: str = "agno"
    app_version: str = metadata.version("agno")

    api_runtime: str = "prd"
    alpha_features: bool = False

    api_url: str = "https://os-api.agno.com"

    # Background telemetry delivery. Override with AGNO_TELEMETRY_TIMEOUT and
    # AGNO_TELEMETRY_SHUTDOWN_TIMEOUT (seconds). Both are read once, when
    # telemetry first runs. The request timeout must be positive. The shutdown
    # timeout bounds the at-exit flush of queued events; set it to 0 to skip
    # that flush entirely. Unusable values fall back to these defaults with a
    # warning instead of failing the import.
    telemetry_timeout: float = 5.0
    telemetry_shutdown_timeout: float = 2.0

    model_config = SettingsConfigDict(env_prefix="AGNO_")

    @field_validator("alpha_features", mode="before")
    def coerce_alpha_features(cls, v: Any) -> bool:
        """An unparsable AGNO_ALPHA_FEATURES must not fail the import either; anything but a true-ish value is off."""
        if isinstance(v, bool):
            return v
        text = str(v).strip().lower() if v is not None else ""
        if text in ("1", "true", "yes", "on"):
            return True
        if text not in ("", "0", "false", "no", "off"):
            log_warning(f"Ignoring AGNO_ALPHA_FEATURES={v!r}: expected a boolean, using False")
        return False

    @field_validator("telemetry_timeout", mode="before")
    def coerce_telemetry_timeout(cls, v: Any) -> float:
        return _coerce_timeout("AGNO_TELEMETRY_TIMEOUT", v, 5.0, zero_allowed=False)

    @field_validator("telemetry_shutdown_timeout", mode="before")
    def coerce_telemetry_shutdown_timeout(cls, v: Any) -> float:
        return _coerce_timeout("AGNO_TELEMETRY_SHUTDOWN_TIMEOUT", v, 2.0, zero_allowed=True)

    @field_validator("api_runtime", mode="before")
    def validate_runtime_env(cls, v):
        """Validate api_runtime; an unknown value falls back to production rather than failing import."""

        valid_api_runtimes = ["dev", "stg", "prd"]
        runtime = str(v).strip().lower() if v is not None else ""
        if runtime not in valid_api_runtimes:
            log_warning(f"Ignoring AGNO_API_RUNTIME={v!r}: expected one of {valid_api_runtimes}, using prd")
            return "prd"

        return runtime

    @field_validator("api_url", mode="before")
    def update_api_url(cls, v, info: ValidationInfo):
        api_runtime = info.data["api_runtime"]
        if api_runtime == "dev":
            from os import getenv

            if getenv("AGNO_RUNTIME") == "docker":
                return "http://host.docker.internal:7070"
            return "http://localhost:7070"
        elif api_runtime == "stg":
            return "https://api-stg.agno.com"
        else:
            return "https://os-api.agno.com"

    def gate_alpha_feature(self):
        if not self.alpha_features:
            log_error("This is an Alpha feature not for general use.\nPlease message the Agno team for access.")
            exit(1)


agno_api_settings = AgnoAPISettings()
