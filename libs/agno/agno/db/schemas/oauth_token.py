from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s


@dataclass
class OAuthToken:
    provider: str
    user_id: str
    service: str
    token_data: Dict[str, Any] = field(default_factory=dict)
    granted_scopes: Optional[List[str]] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.updated_at is not None:
            self.updated_at = to_epoch_s(self.updated_at)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "user_id": self.user_id,
            "service": self.service,
            "token_data": self.token_data,
            "granted_scopes": self.granted_scopes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuthToken":
        data = dict(data)
        valid_keys = {
            "provider",
            "user_id",
            "service",
            "token_data",
            "granted_scopes",
            "created_at",
            "updated_at",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)
