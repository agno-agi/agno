import re
import pytest
from unittest.mock import MagicMock

from agno.guardrails.pii import PIIDetectionGuardrail
from agno.run.agent import RunInput


def _make_input(text: str) -> RunInput:
    inp = MagicMock(spec=RunInput)
    inp.input_content_string.return_value = text
    inp.input_content = text
    return inp


class TestPIICustomPatterns:
    def test_raw_string_pattern_is_compiled_and_detects_pii(self):
        """Raw regex strings in custom_patterns should be auto-compiled."""
        guardrail = PIIDetectionGuardrail(
            enable_ssn_check=False,
            enable_credit_card_check=False,
            enable_email_check=False,
            enable_phone_check=False,
            custom_patterns={"bank_account": r"\b\d{10}\b"},
        )
        from agno.exceptions import InputCheckError
        inp = _make_input("Account number: 1234567890")
        with pytest.raises(InputCheckError):
            guardrail.check(inp)

    def test_compiled_pattern_still_works(self):
        """Existing callers passing compiled patterns are unaffected."""
        guardrail = PIIDetectionGuardrail(
            enable_ssn_check=False,
            enable_credit_card_check=False,
            enable_email_check=False,
            enable_phone_check=False,
            custom_patterns={"employee_id": re.compile(r"EMP-\d{4}")},
        )
        from agno.exceptions import InputCheckError
        inp = _make_input("My employee ID is EMP-1234")
        with pytest.raises(InputCheckError):
            guardrail.check(inp)

    def test_raw_string_pattern_no_false_positive(self):
        """Non-matching input should not trigger the guardrail."""
        guardrail = PIIDetectionGuardrail(
            enable_ssn_check=False,
            enable_credit_card_check=False,
            enable_email_check=False,
            enable_phone_check=False,
            custom_patterns={"bank_account": r"\b\d{10}\b"},
        )
        inp = _make_input("Hello, how are you?")
        guardrail.check(inp)  # should not raise

    def test_mixed_string_and_compiled_patterns(self):
        """Dict with both raw strings and compiled patterns works correctly."""
        guardrail = PIIDetectionGuardrail(
            enable_ssn_check=False,
            enable_credit_card_check=False,
            enable_email_check=False,
            enable_phone_check=False,
            custom_patterns={
                "bank_account": r"\b\d{10}\b",
                "employee_id": re.compile(r"EMP-\d{4}"),
            },
        )
        assert "bank_account" in guardrail.pii_patterns
        assert "employee_id" in guardrail.pii_patterns
        assert hasattr(guardrail.pii_patterns["bank_account"], "search")
        assert hasattr(guardrail.pii_patterns["employee_id"], "search")

    def test_invalid_regex_string_raises_at_init(self):
        """Malformed regex strings must raise re.error at __init__ time (fail-fast).

        This documents intentional behaviour: bad patterns surface immediately
        at configuration time rather than silently failing on the first agent input.
        """
        with pytest.raises(re.error):
            PIIDetectionGuardrail(
                enable_ssn_check=False,
                enable_credit_card_check=False,
                enable_email_check=False,
                enable_phone_check=False,
                custom_patterns={"broken": r"[unclosed"},
            )
