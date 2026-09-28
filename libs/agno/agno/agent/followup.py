from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, NamedTuple, Optional, Tuple, Union

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


DEFAULT_NUM_FOLLOWUPS = 3


@dataclass
class FollowupConfig:
    """Follow-up generation options; pass it as ``followups=FollowupConfig(...)`` on an Agent or Team.

    An alternative to the top-level ``num_followups`` and ``followup_model`` arguments;
    passing it together with either of them raises ValueError.

    ``model`` generates the suggestions; None uses the component model. A
    ``provider:model_id`` string is resolved when the component is constructed, on a
    copy of this object; an unknown reference raises ValueError there.
    ``instructions`` adds domain or style constraints to the default system prompt.
    The main instructions and retrieved context are not copied into this call.

    ``max_followups`` (default 3) is enforced: extra suggestions are dropped.
    ``min_followups`` (default: equal to ``max_followups``, so exactly that many) is
    only requested from the model; fewer can come back. ``min_followups=0`` lets the
    model return fewer or none when the answer does not support a useful
    continuation, which best keeps suggestions within the answer's boundaries.
    """

    model: Optional[Union[Model, str]] = None
    instructions: Optional[str] = None
    # After model and instructions, so FollowupConfig(model, instructions) keeps its positional meaning
    max_followups: Optional[int] = None
    min_followups: Optional[int] = None

    def __post_init__(self) -> None:
        self.count_range()

    def count_range(self) -> Tuple[int, int]:
        """The (minimum, maximum) number of suggestions this config asks for."""
        maximum = self.max_followups if self.max_followups is not None else DEFAULT_NUM_FOLLOWUPS
        minimum = self.min_followups if self.min_followups is not None else maximum
        if maximum < 1:
            raise ValueError("max_followups must be at least 1")
        if not 0 <= minimum <= maximum:
            raise ValueError("min_followups must be between 0 and max_followups")
        return minimum, maximum

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for component storage; a model keeps only its identity (see model_identity)."""
        config: Dict[str, Any] = {}
        if self.model is not None:
            config["model"] = model_identity(self.model) if isinstance(self.model, Model) else str(self.model)
        if self.instructions is not None:
            config["instructions"] = self.instructions
        if self.max_followups is not None:
            config["max_followups"] = self.max_followups
        if self.min_followups is not None:
            config["min_followups"] = self.min_followups
        return config

    @classmethod
    def from_dict(cls, data: Dict[str, Any], registry: Optional["Registry"] = None) -> "FollowupConfig":
        """Rebuild from to_dict output; a registered live model is preferred over its identity dict."""
        from agno.models.utils import resolve_model

        model = data.get("model")
        return cls(
            model=resolve_model(model, registry) if model is not None else None,
            instructions=data.get("instructions"),
            max_followups=data.get("max_followups"),
            min_followups=data.get("min_followups"),
        )


def resolve_followup_settings(
    followups: Union[bool, FollowupConfig],
    num_followups: Optional[int],
    followup_model: Optional[Union[Model, str]] = None,
) -> int:
    """Reject a FollowupConfig combined with the top-level arguments; return the effective maximum count."""
    if isinstance(followups, FollowupConfig):
        if num_followups is not None or followup_model is not None:
            raise ValueError(
                "Pass the count and model either inside FollowupConfig or as top-level num_followups and "
                "followup_model, not both"
            )
        return followups.count_range()[1]
    if num_followups is None:
        num_followups = DEFAULT_NUM_FOLLOWUPS
    if num_followups < 1:
        raise ValueError("num_followups must be at least 1")
    return num_followups


def drop_derived_followup_fields(fields: Dict[str, Any], update: Optional[Dict[str, Any]]) -> None:
    """With a FollowupConfig, num_followups and followup_model are derived from it; deep_copy must not re-pass them."""
    if isinstance(fields.get("followups"), FollowupConfig):
        for name in ("num_followups", "followup_model"):
            if name not in (update or {}):
                fields.pop(name, None)


class FollowupCall(NamedTuple):
    model: Model
    instructions: Optional[str]
    min_followups: int
    max_followups: int


def prepare_followup_call(component: Any, run_response: Any) -> Optional[FollowupCall]:
    """Clear the previous answer's suggestions and choose how to generate new ones; None skips generation."""
    # A resumed run still carries the earlier answer's suggestions; they never describe a new answer.
    run_response.followups = None
    if not component.followups or run_response.content is None:
        return None

    config = component.followups if isinstance(component.followups, FollowupConfig) else None
    selected = (config.model if config else component.followup_model) or component.model
    if selected is None:
        return None
    try:
        from agno.models.utils import get_model

        # A config assigned after construction may still hold a model string or an invalid count.
        model = get_model(selected)
        # num_followups is an exact count; a config can ask for a range.
        minimum, maximum = config.count_range() if config else (component.num_followups, component.num_followups)
    except Exception as e:
        log_warning(f"Error preparing followups: {str(e)}")
        return None
    if model is None:
        return None
    return FollowupCall(
        model=model,
        instructions=config.instructions if config else None,
        min_followups=minimum,
        max_followups=maximum,
    )
