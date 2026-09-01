import re

import pytest

from agno.exceptions import InputCheckError
from agno.guardrails.pii import PIIDetectionGuardrail
from agno.run.agent import RunInput


def _custom_pattern_guardrail(custom_patterns, mask_pii=False):
    """Build a guardrail with only the given custom patterns, default checks disabled."""
    return PIIDetectionGuardrail(
        mask_pii=mask_pii,
        enable_ssn_check=False,
        enable_credit_card_check=False,
        enable_email_check=False,
        enable_phone_check=False,
        custom_patterns=custom_patterns,
    )


class TestPIICustomPatterns:
    def test_raw_string_pattern_is_compiled_and_detects_pii(self):
        """Raw regex strings in custom_patterns are auto-compiled and used for detection."""
        guardrail = _custom_pattern_guardrail({"bank_account": r"\b\d{10}\b"})
        with pytest.raises(InputCheckError, match="Potential PII detected"):
            guardrail.check(RunInput(input_content="Account number: 1234567890"))

    @pytest.mark.asyncio
    async def test_raw_string_pattern_is_compiled_and_detects_pii_async(self):
        """Raw regex strings are auto-compiled on the async check path as well."""
        guardrail = _custom_pattern_guardrail({"bank_account": r"\b\d{10}\b"})
        with pytest.raises(InputCheckError, match="Potential PII detected"):
            await guardrail.async_check(RunInput(input_content="Account number: 1234567890"))

    def test_compiled_pattern_still_works(self):
        """Existing callers passing compiled patterns are unaffected."""
        guardrail = _custom_pattern_guardrail({"employee_id": re.compile(r"EMP-\d{4}")})
        with pytest.raises(InputCheckError, match="Potential PII detected"):
            guardrail.check(RunInput(input_content="My employee ID is EMP-1234"))

    def test_raw_string_pattern_no_false_positive(self):
        """Non-matching input does not trigger the guardrail."""
        guardrail = _custom_pattern_guardrail({"bank_account": r"\b\d{10}\b"})
        guardrail.check(RunInput(input_content="Hello, how are you?"))  # should not raise

    def test_mixed_string_and_compiled_patterns(self):
        """A dict mixing raw strings and compiled patterns is stored as compiled patterns."""
        guardrail = _custom_pattern_guardrail(
            {
                "bank_account": r"\b\d{10}\b",
                "employee_id": re.compile(r"EMP-\d{4}"),
            }
        )
        assert isinstance(guardrail.pii_patterns["bank_account"], re.Pattern)
        assert isinstance(guardrail.pii_patterns["employee_id"], re.Pattern)

    def test_invalid_regex_string_raises_at_init(self):
        """A malformed regex string raises re.error at __init__ time, not on the first check()."""
        with pytest.raises(re.error):
            _custom_pattern_guardrail({"broken": r"[unclosed"})

    def test_invalid_pattern_type_raises_at_init(self):
        """A pattern that is neither str nor re.Pattern raises TypeError at __init__ time."""
        with pytest.raises(TypeError, match="must be a str or re.Pattern"):
            _custom_pattern_guardrail({"bad": 12345})
