from typing import Union

from agno.exceptions import CheckTrigger, InputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput


class PIIDetectionGuardrail(BaseGuardrail):
    """Guardrail for detecting Personally Identifiable Information (PII)."""

    def __init__(self):
        import re

        self.pii_patterns = {
            "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
            "Credit Card": re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
            "Email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
            "Phone": re.compile(r"\b\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b"),
        }

    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check for PII patterns in the input."""
        content = run_input.input_content_string()
        for pii_type, pattern in self.pii_patterns.items():
            if pattern.search(content):
                raise InputCheckError(
                    f"Potential {pii_type} detected in input", check_trigger=CheckTrigger.PII_DETECTED
                )

    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Asynchronously check for PII patterns in the input."""
        content = run_input.input_content_string()
        for pii_type, pattern in self.pii_patterns.items():
            if pattern.search(content):
                raise InputCheckError(
                    f"Potential {pii_type} detected in input", check_trigger=CheckTrigger.PII_DETECTED
                )
