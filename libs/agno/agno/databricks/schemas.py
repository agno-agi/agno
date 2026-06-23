from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class DatabricksAPIError(BaseModel):
    error_code: Optional[str] = None
    code: Optional[str] = None

    @field_validator("error_code", "code", mode="before")
    @classmethod
    def coerce_to_str(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else None
    message: Optional[str] = None
    details: Optional[Any] = None
    raw: Optional[Any] = Field(default=None, exclude=True)  # Preserved for debugging; not serialized

    @classmethod
    def from_payload(cls, payload: Any) -> "DatabricksAPIError":
        if isinstance(payload, cls):
            return payload

        if isinstance(payload, dict):
            nested_error = payload.get("error")
            if isinstance(nested_error, dict):
                return cls(
                    error_code=nested_error.get("error_code") or payload.get("error_code"),
                    code=nested_error.get("code") or payload.get("code"),
                    message=nested_error.get("message") or payload.get("message"),
                    details=nested_error.get("details") or payload.get("details"),
                    raw=payload,
                )

            return cls(
                error_code=payload.get("error_code"),
                code=payload.get("code"),
                message=payload.get("message") or payload.get("error"),
                details=payload.get("details"),
                raw=payload,
            )

        if isinstance(payload, str):
            return cls(message=payload, raw=payload)

        return cls(raw=payload)

    def best_message(self, fallback: str) -> str:
        if self.message:
            if self.error_code:
                return f"{self.error_code}: {self.message}"
            if self.code:
                return f"{self.code}: {self.message}"
            return self.message
        if self.error_code:
            return self.error_code
        if self.code:
            return self.code
        return fallback
