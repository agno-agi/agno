from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from agno.models.base import Model


@dataclass
class FollowupConfig:
    """Options shared by Agent and Team follow-up generation.

    ``model`` overrides ``followup_model``, then falls back to the component model.
    ``instructions`` adds domain or style constraints to the default system prompt.
    The main instructions and retrieved context are not copied into this call.
    ``num_followups`` on the component is a maximum; fewer or no suggestions may
    be returned when the answer does not support a useful continuation.
    """

    model: Optional[Model] = None
    instructions: Optional[str] = None
