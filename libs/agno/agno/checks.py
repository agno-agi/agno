from enum import Enum
from typing import Any


class CheckTrigger(Enum):
    """Enum for guardrail triggers."""

    OFF_TOPIC = "off_topic"
    INJECTION_DETECTED = "injection_detected"
    INPUT_NOT_ALLOWED = "input_not_allowed"
    OUTPUT_NOT_ALLOWED = "output_not_allowed"
    VALIDATION_FAILED = "validation_failed"


class Checks:
    @staticmethod
    def prompt_injection(
        input: Any,
    ) -> None:
        """Synchronous pre-hook function."""
        # Simple keyword-based detection
        injection_patterns = [
            "ignore previous instructions",
            "you are now a",
            "forget everything above",
            "developer mode",
            "override safety",
            "disregard guidelines",
        ]

        if any(keyword in input.lower() for keyword in injection_patterns):
            from agno.exceptions import InputCheckError

            raise InputCheckError(
                "Potential jailbreaking or prompt injection detected.",
                check_trigger=CheckTrigger.INJECTION_DETECTED,
            )
