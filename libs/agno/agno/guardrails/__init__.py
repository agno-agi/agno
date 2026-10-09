from typing import TYPE_CHECKING, Any

from agno.guardrails.base import BaseGuardrail
from agno.guardrails.openai import OpenAIModerationGuardrail
from agno.guardrails.pii import PIIDetectionGuardrail
from agno.guardrails.prompt_injection import PromptInjectionGuardrail

if TYPE_CHECKING:
    from agno.guardrails.typesafe import JevGuardrail

__all__ = [
    "BaseGuardrail",
    "OpenAIModerationGuardrail",
    "PIIDetectionGuardrail",
    "PromptInjectionGuardrail",
    "JevGuardrail",
]


def __getattr__(name: str) -> Any:
    if name == "JevGuardrail":
        from agno.guardrails.typesafe import JevGuardrail

        return JevGuardrail
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
