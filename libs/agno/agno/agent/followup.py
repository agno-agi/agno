from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, NamedTuple, Optional, Union

from agno.models.base import Model
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.registry import Registry


def model_identity(model: Model) -> Dict[str, Any]:
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

    ``model`` generates the suggestions; None falls back to ``followup_model``, then the
    component model. A ``provider:model_id`` string is resolved when the component is
    constructed, on a copy of this object; an unknown reference raises ValueError there.
    ``instructions`` adds domain or style constraints to the default system prompt.
    The main instructions and retrieved context are not copied into this call.
    ``num_followups`` is a maximum; fewer or no suggestions may be returned when the
    answer does not support a useful continuation. None falls back to the component's
    ``num_followups`` (default 3).

    Setting the count or model both here and on the component raises ValueError
    unless the two values agree, so neither is silently ignored.
    """

    model: Optional[Union[Model, str]] = None
    instructions: Optional[str] = None
    # Last, so FollowupConfig(model, instructions) keeps its positional meaning
    num_followups: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for component storage; a model keeps only its identity (see model_identity)."""
        config: Dict[str, Any] = {}
        if self.model is not None:
            config["model"] = model_identity(self.model) if isinstance(self.model, Model) else str(self.model)
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


def resolve_followup_settings(
    followups: Union[bool, FollowupConfig],
    num_followups: Optional[int],
    followup_model: Optional[Union[Model, str]] = None,
) -> int:
    """Check that the config and the component agree on count and model; return the effective count."""
    if isinstance(followups, FollowupConfig):
        if followups.num_followups is not None:
            if num_followups is not None and num_followups != followups.num_followups:
                raise ValueError(
                    f"num_followups={num_followups} conflicts with FollowupConfig.num_followups="
                    f"{followups.num_followups}; set the count in one place"
                )
            num_followups = followups.num_followups
        if (
            followups.model is not None
            and followup_model is not None
            and followups.model is not followup_model
            and followups.model != followup_model
        ):
            raise ValueError("followup_model conflicts with FollowupConfig.model; set the model in one place")
    if num_followups is None:
        num_followups = 3
    if num_followups < 1:
        raise ValueError("num_followups must be at least 1")
    return num_followups


def reconcile_copied_followup_fields(fields: Dict[str, Any], update: Optional[Dict[str, Any]]) -> None:
    """Let a copy's config own the count and model it sets, unless the update names those fields.

    deep_copy re-passes num_followups and followup_model as the source component held them; without
    this, replacing the config through update would collide with the source's values.
    """
    update = update or {}
    config = fields.get("followups")
    if not isinstance(config, FollowupConfig):
        return
    if config.num_followups is not None and "num_followups" not in update:
        fields.pop("num_followups", None)
    if config.model is not None and "followup_model" not in update:
        fields.pop("followup_model", None)


class FollowupCall(NamedTuple):
    model: Model
    instructions: Optional[str]
    num_followups: int


def prepare_followup_call(component: Any, run_response: Any) -> Optional[FollowupCall]:
    """Clear the previous answer's suggestions and choose how to generate new ones; None skips generation."""
    # A resumed run still carries the earlier answer's suggestions; they never describe a new answer.
    run_response.followups = None
    if not component.followups or run_response.content is None:
        return None

    config = component.followups if isinstance(component.followups, FollowupConfig) else None
    selected = (config.model if config else None) or component.followup_model or component.model
    if selected is None:
        return None
    try:
        from agno.models.utils import get_model

        # Strings are resolved at construction; this covers a config assigned afterwards.
        model = get_model(selected)
    except Exception as e:
        log_warning(f"Error resolving followup model: {str(e)}")
        return None
    if model is None:
        return None
    return FollowupCall(
        model=model, instructions=config.instructions if config else None, num_followups=component.num_followups
    )
