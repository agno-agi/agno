from re import Pattern
from typing import Dict, Optional, Union

from agno.exceptions import CheckTrigger, InputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput


class PIIDetectionGuardrail(BaseGuardrail):
    """Guardrail for detecting Personally Identifiable Information (PII).

    Args:
        mask_pii: Whether to mask the PII in the input, rather than raising an error.
        enable_ssn_check: Whether to check for Social Security Numbers. True by default.
        enable_credit_card_check: Whether to check for credit cards. True by default.
        enable_email_check: Whether to check for emails. True by default.
        enable_phone_check: Whether to check for phone numbers. True by default.
        custom_patterns: A dictionary of custom PII patterns to detect. This is added to the default patterns.
    """

    def __init__(
        self,
        mask_pii: bool = False,
        enable_ssn_check: bool = True,
        enable_credit_card_check: bool = True,
        enable_email_check: bool = True,
        enable_phone_check: bool = True,
        custom_patterns: Optional[Dict[str, Pattern[str]]] = None,
    ):
        import re

        self.mask_pii = mask_pii
        self.pii_patterns = {}

        if enable_ssn_check:
            self.pii_patterns["SSN"] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
        if enable_credit_card_check:
            self.pii_patterns["Credit Card"] = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
        if enable_email_check:
            self.pii_patterns["Email"] = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
        if enable_phone_check:
            self.pii_patterns["Phone"] = re.compile(r"\b\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b")

        if custom_patterns:
            self.pii_patterns.update(custom_patterns)

    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check for PII patterns in the input."""
        content = run_input.input_content_string()
        detected_pii = []
        for pii_type, pattern in self.pii_patterns.items():
            if pattern.search(content):
                detected_pii.append(pii_type)
        if detected_pii:
            if self.mask_pii:
                for pii_type in detected_pii:

                    def mask_match(match):
                        return "*" * len(match.group(0))

                    content = self.pii_patterns[pii_type].sub(mask_match, content)
                run_input.input_content = content
                return
            else:
                raise InputCheckError(
                    "Potential PII detected in input",
                    additional_data={"detected_pii": detected_pii},
                    check_trigger=CheckTrigger.PII_DETECTED,
                )

    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Asynchronously check for PII patterns in the input."""
        content = run_input.input_content_string()
        detected_pii = []
        for pii_type, pattern in self.pii_patterns.items():
            if pattern.search(content):
                detected_pii.append(pii_type)
        if detected_pii:
            if self.mask_pii:
                for pii_type in detected_pii:

                    def mask_match(match):
                        return "*" * len(match.group(0))

                    content = self.pii_patterns[pii_type].sub(mask_match, content)
                run_input.input_content = content
                return
            else:
                raise InputCheckError(
                    "Potential PII detected in input",
                    additional_data={"detected_pii": detected_pii},
                    check_trigger=CheckTrigger.PII_DETECTED,
                )
