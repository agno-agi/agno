from typing import Any, Dict, Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agno.databricks.utils import normalize_host


def _get_default_user_agent() -> str:
    try:
        from importlib.metadata import version as pkg_version

        ver = pkg_version("agno")
    except Exception:
        ver = "unknown"
    return f"agno-databricks/{ver}"


def _normalize_databricks_host(value: Optional[str]) -> Optional[str]:
    return normalize_host(value)


def _validate_databricks_timeout(value: float) -> float:
    if value <= 0:
        raise ValueError("timeout must be greater than 0")
    return value


def _validate_databricks_max_retries(value: int) -> int:
    if value < 0:
        raise ValueError("max_retries must be greater than or equal to 0")
    return value


# Proxy model used by `from_values()` to validate & normalize user-supplied kwargs
# before constructing the environment-aware DatabricksSettings. Kept separate because
# BaseSettings would read env vars during validation, which we want to avoid here.
class _DatabricksSettingsData(BaseModel):
    host: Optional[str] = None
    workspace_url: Optional[str] = None
    token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = Field(default=None, repr=False)
    account_id: Optional[str] = None
    timeout: float = 60.0
    max_retries: int = 3
    default_headers: Dict[str, str] = Field(default_factory=dict)
    user_agent: str = _get_default_user_agent()

    @field_validator("host", "workspace_url", mode="before")
    def validate_host(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_databricks_host(value)

    @field_validator("timeout")
    def validate_timeout(cls, value: float) -> float:
        return _validate_databricks_timeout(value)

    @field_validator("max_retries")
    def validate_max_retries(cls, value: int) -> int:
        return _validate_databricks_max_retries(value)

    @model_validator(mode="after")
    def resolve_workspace_url(self) -> "_DatabricksSettingsData":
        if self.host and not self.workspace_url:
            self.workspace_url = self.host
        elif self.workspace_url and not self.host:
            self.host = self.workspace_url
        return self


class DatabricksSettings(BaseSettings):
    host: Optional[str] = Field(
        default=None,
        validation_alias="DATABRICKS_HOST",
    )
    workspace_url: Optional[str] = Field(
        default=None,
        validation_alias="DATABRICKS_WORKSPACE_URL",
    )
    token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("DATABRICKS_TOKEN", "DATABRICKS_PAT"),
        repr=False,
    )
    client_id: Optional[str] = Field(
        default=None,
        validation_alias="DATABRICKS_CLIENT_ID",
    )
    client_secret: Optional[str] = Field(
        default=None,
        validation_alias="DATABRICKS_CLIENT_SECRET",
        repr=False,
    )
    account_id: Optional[str] = Field(
        default=None,
        validation_alias="DATABRICKS_ACCOUNT_ID",
    )
    timeout: float = Field(
        default=60.0,
        validation_alias="DATABRICKS_TIMEOUT",
    )
    max_retries: int = Field(
        default=3,
        validation_alias="DATABRICKS_MAX_RETRIES",
    )
    default_headers: Dict[str, str] = Field(default_factory=dict)
    user_agent: str = _get_default_user_agent()

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("host", "workspace_url", mode="before")
    def validate_host(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_databricks_host(value)

    @field_validator("timeout")
    def validate_timeout(cls, value: float) -> float:
        return _validate_databricks_timeout(value)

    @field_validator("max_retries")
    def validate_max_retries(cls, value: int) -> int:
        return _validate_databricks_max_retries(value)

    @model_validator(mode="after")
    def resolve_workspace_url(self) -> "DatabricksSettings":
        if self.host and not self.workspace_url:
            self.workspace_url = self.host
        elif self.workspace_url and not self.host:
            self.host = self.workspace_url
        return self

    @property
    def base_url(self) -> Optional[str]:
        return self.host

    @property
    def has_pat_auth(self) -> bool:
        return self.token is not None and self.token.strip() != ""

    @property
    def has_oauth_client_credentials(self) -> bool:
        return bool(
            self.client_id and self.client_id.strip()
            and self.client_secret and self.client_secret.strip()
        )

    @classmethod
    def from_values(cls, **values: Any) -> "DatabricksSettings":
        payload = {key: value for key, value in values.items() if value is not None}
        validated = _DatabricksSettingsData.model_validate(payload)
        explicit_keys = set(payload.keys())
        if "host" in explicit_keys:
            explicit_keys.add("workspace_url")
        if "workspace_url" in explicit_keys:
            explicit_keys.add("host")
        validated_dump = validated.model_dump()
        filtered = {k: v for k, v in validated_dump.items() if k in explicit_keys}
        # Build a complete dict: env-var baseline + explicit overrides.
        # Using model_construct avoids BaseSettings re-reading env vars
        # via validation_alias, which would override explicit values.
        baseline = cls()
        merged = baseline.model_dump()
        merged.update(filtered)
        return cls.model_construct(**merged)

    def with_overrides(self, **overrides: Any) -> "DatabricksSettings":
        payload = self.model_dump()
        normalized_overrides = {key: value for key, value in overrides.items() if value is not None}

        if "default_headers" in normalized_overrides:
            payload["default_headers"] = {
                **payload.get("default_headers", {}),
                **normalized_overrides.pop("default_headers"),
            }

        # Sync host/workspace_url when only one is overridden
        if "host" in normalized_overrides and "workspace_url" not in normalized_overrides:
            normalized_overrides["workspace_url"] = normalized_overrides["host"]
        elif "workspace_url" in normalized_overrides and "host" not in normalized_overrides:
            normalized_overrides["host"] = normalized_overrides["workspace_url"]

        payload.update(normalized_overrides)
        return self.__class__.from_values(**payload)
