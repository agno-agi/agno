from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from agno.models.base import Model

if TYPE_CHECKING:
    from agno.registry import Registry


def _model_identity(model: Model) -> Dict[str, Any]:
    """The stored form of a follow-up model: id, name and provider, nothing else.

    Provider ``to_dict`` methods also emit request options such as ``extra_headers``,
    which can carry credentials; reconstruction and registry lookup only read these
    three fields (see ``resolve_model``).
    """
    identity = {"id": model.id, "name": model.name, "provider": model.provider}
    return {key: value for key, value in identity.items() if value is not None}


@dataclass
class FollowupConfig:
    """Follow-up generation options; pass it as ``followups=FollowupConfig(...)`` on an Agent or Team.

    ``model`` overrides ``followup_model``, then falls back to the component model.
    A ``provider:model_id`` string is resolved when the component is constructed,
    on a copy of this object; an unknown reference raises ValueError there.
    ``instructions`` adds domain or style constraints to the default system prompt.
    The main instructions and retrieved context are not copied into this call.
    ``num_followups`` is a maximum; fewer or no suggestions may be returned when the
    answer does not support a useful continuation. It overrides the component's
    ``num_followups``; None leaves the count to the component (default 3).
    """

    model: Optional[Union[Model, str]] = None
    instructions: Optional[str] = None
    # Last, so FollowupConfig(model, instructions) keeps its positional meaning
    num_followups: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for component storage; a model keeps only its identity (see _model_identity)."""
        config: Dict[str, Any] = {}
        if self.model is not None:
            config["model"] = _model_identity(self.model) if isinstance(self.model, Model) else str(self.model)
        if self.instructions is not None:
            config["instructions"] = self.instructions
        if self.num_followups is not None:
            config["num_followups"] = self.num_followups
        return config

    @classmethod
    def from_dict(cls, data: Dict[str, Any], registry: Optional["Registry"] = None) -> "FollowupConfig":
        """Rebuild from to_dict output; a registered live model is preferred over its identity dict."""
        from agno.models.utils import resolve_model

        model = data.get("model")
        return cls(
            model=resolve_model(model, registry) if model is not None else None,
            instructions=data.get("instructions"),
            num_followups=data.get("num_followups"),
        )


def _effective_num_followups(followups: Union[bool, FollowupConfig], num_followups: int) -> int:
    """The count the component runs with: the config's when it sets one, else ``num_followups``.

    None on the config means unset, so an explicit 3 there still overrides the component's count.
    """
    if isinstance(followups, FollowupConfig) and followups.num_followups is not None:
        num_followups = followups.num_followups
    if num_followups < 1:
        raise ValueError("num_followups must be at least 1")
    return num_followups
