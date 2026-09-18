from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from agno.models.base import Model

if TYPE_CHECKING:
    from agno.registry import Registry


@dataclass
class FollowupConfig:
    """Options shared by Agent and Team follow-up generation.

    ``model`` overrides ``followup_model``, then falls back to the component model.
    A ``provider:model_id`` string is resolved when the component is constructed,
    on a copy of this object; an unknown reference raises ValueError there.
    ``instructions`` adds domain or style constraints to the default system prompt.
    The main instructions and retrieved context are not copied into this call.
    ``num_followups`` on the component is a maximum; fewer or no suggestions may
    be returned when the answer does not support a useful continuation.
    """

    model: Optional[Union[Model, str]] = None
    instructions: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for component storage; a model keeps only its identity (see Model.to_dict)."""
        config: Dict[str, Any] = {}
        if self.model is not None:
            config["model"] = self.model.to_dict() if isinstance(self.model, Model) else str(self.model)
        if self.instructions is not None:
            config["instructions"] = self.instructions
        return config

    @classmethod
    def from_dict(cls, data: Dict[str, Any], registry: Optional["Registry"] = None) -> "FollowupConfig":
        """Rebuild from to_dict output; a registered live model is preferred over its identity dict."""
        from agno.models.utils import resolve_model

        model = data.get("model")
        return cls(
            model=resolve_model(model, registry) if model is not None else None,
            instructions=data.get("instructions"),
        )
