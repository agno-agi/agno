from __future__ import annotations

from importlib import metadata

from pydantic import field_validator
from pydantic_core.core_schema import ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

from agno.utils.log import log_error


class AgnoAPISettings(BaseSettings):
    app_name: str = "agno"
    app_version: str = metadata.version("agno")

    api_runtime: str = "prd"
    alpha_features: bool = False

    api_url: str = "https://os-api.agno.com"

    # Background telemetry delivery. Override with AGNO_TELEMETRY_TIMEOUT and
    # AGNO_TELEMETRY_SHUTDOWN_TIMEOUT (seconds). The shutdown timeout bounds the
    # at-exit flush of queued events; set it to 0 to skip that flush entirely.
    telemetry_timeout: float = 5.0
    telemetry_shutdown_timeout: float = 2.0

    model_config = SettingsConfigDict(env_prefix="AGNO_")

    @field_validator("telemetry_timeout", "telemetry_shutdown_timeout")
    def clamp_non_negative(cls, v: float) -> float:
        """A negative timeout is meaningless; treat it as zero rather than failing import."""
        return max(0.0, v)

    @field_validator("api_runtime", mode="before")
    def validate_runtime_env(cls, v):
        """Validate api_runtime."""

        valid_api_runtimes = ["dev", "stg", "prd"]
        if v.lower() not in valid_api_runtimes:
            raise ValueError(f"Invalid api_runtime: {v}")

        return v.lower()

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
