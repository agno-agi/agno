from typing import Union

from agno.exceptions import CheckTrigger, InputCheckError
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput


class Guardrails:
    @staticmethod
    def prompt_injection(
        run_input: Union[RunInput, TeamRunInput],
    ):
        # Simple keyword-based detection
        injection_patterns = [
            "ignore previous instructions",
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
        ]

        if any(keyword in run_input.input_content_string().lower() for keyword in injection_patterns):
            raise InputCheckError(
                "Potential jailbreaking or prompt injection detected.",
                check_trigger=CheckTrigger.PROMPT_INJECTION,
            )

    @staticmethod
    async def async_prompt_injection(
        run_input: Union[RunInput, TeamRunInput],
    ):
        # Simple keyword-based detection
        injection_patterns = [
            "ignore previous instructions",
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
        ]

        if any(keyword in run_input.input_content_string().lower() for keyword in injection_patterns):
            raise InputCheckError(
                "Potential jailbreaking or prompt injection detected.",
                check_trigger=CheckTrigger.PROMPT_INJECTION,
            )

    @staticmethod
    def pii_detection(run_input: Union[RunInput, TeamRunInput]) -> None:
        import re

        pii_patterns = {
            "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
            "Credit Card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            "Email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "Phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        }

        content = run_input.input_content_string()
        for pii_type, pattern in pii_patterns.items():
            if re.search(pattern, content):
                raise InputCheckError(
                    f"Potential {pii_type} detected in input", check_trigger=CheckTrigger.PII_DETECTED
                )

    @staticmethod
    def async_pii_detection(run_input: Union[RunInput, TeamRunInput]) -> None:
        import re

        pii_patterns = {
            "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
            "Credit Card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            "Email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "Phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        }

        content = run_input.input_content_string()
        for pii_type, pattern in pii_patterns.items():
            if re.search(pattern, content):
                raise InputCheckError(
                    f"Potential {pii_type} detected in input", check_trigger=CheckTrigger.PII_DETECTED
                )
