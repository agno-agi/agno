from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

from agno.models.base import Model

if TYPE_CHECKING:
    from agno.registry import Registry


@dataclass
class FollowupConfig:
    """Options shared by Agent and Team follow-up generation.

    Passing it as ``followups=FollowupConfig(...)`` enables follow-ups and configures them.
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
        """Serialize for component storage; a model keeps only its identity (see Model.to_dict)."""
        config: Dict[str, Any] = {}
        if self.model is not None:
            config["model"] = self.model.to_dict() if isinstance(self.model, Model) else str(self.model)
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


def _resolve_followups(
    followups: Union[bool, FollowupConfig],
    num_followups: int,
    followup_config: Optional[FollowupConfig],
) -> Tuple[bool, int, Optional[FollowupConfig]]:
    """Normalize the Agent/Team follow-up arguments into (enabled, effective count, config).

    A FollowupConfig passed as ``followups`` enables the feature and becomes the config.
    ``followup_config`` stays accepted as the separate argument, but a different object
    there is a conflict: identity decides, so two equal-looking configs still conflict.
    """
    if isinstance(followups, FollowupConfig):
        if followup_config is not None and followup_config is not followups:
            raise ValueError("Got two different FollowupConfig objects as followups= and followup_config=; pass one.")
        followup_config = followups
        followups = True

    # None on the config means unset, so an explicit 3 there still overrides the component's count
    if followup_config is not None and followup_config.num_followups is not None:
        num_followups = followup_config.num_followups
    if num_followups < 1:
        raise ValueError("num_followups must be at least 1")
    return followups, num_followups, followup_config
