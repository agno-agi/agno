from typing import List, Optional, Union

from agno.exceptions import CheckTrigger, InputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput


class PromptInjectionGuardrail(BaseGuardrail):
    """Guardrail for detecting prompt injection attempts.

    Matching is case-insensitive: the input and every pattern are lowercased
    before they are compared.

    Args:
        injection_patterns (Optional[List[str]]): A list of patterns to check for. Defaults to a list of common prompt injection patterns.
    """

    def __init__(self, injection_patterns: Optional[List[str]] = None):
        patterns = injection_patterns or [
            "ignore previous instructions",
            "ignore your instructions",
            "you are now a",
            "forget everything above",
            "developer mode",
            "override safety",
            "disregard guidelines",
            "system prompt",
            "jailbreak",
            "act as if",
            "pretend you are",
            "roleplay as",
            "simulate being",
            "bypass restrictions",
            "ignore safeguards",
            "admin override",
            "root access",
            "forget everything",
        ]
        # Both checks lowercase the input before matching, so a pattern has to be
        # lowercased once here: a capital letter in a custom pattern could never
        # match the lowercased input, and the prompt it guards would be let through.
        self.injection_patterns = [pattern.lower() for pattern in patterns]

    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check for prompt injection patterns in the input."""
        if any(keyword in run_input.input_content_string().lower() for keyword in self.injection_patterns):
            raise InputCheckError(
                "Potential jailbreaking or prompt injection detected.",
                check_trigger=CheckTrigger.PROMPT_INJECTION,
            )

    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Asynchronously check for prompt injection patterns in the input."""
        if any(keyword in run_input.input_content_string().lower() for keyword in self.injection_patterns):
            raise InputCheckError(
                "Potential jailbreaking or prompt injection detected.",
                check_trigger=CheckTrigger.PROMPT_INJECTION,
            )
