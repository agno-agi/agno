import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from agno.exceptions import CheckTrigger, InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail, OnFailCallback
from agno.run.agent import RunInput, RunOutput
from agno.run.messages import RunMessages
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.utils.guardrails import extract_all_text_from_run_messages


class PIIDetectionGuardrail(BaseGuardrail):
    """Guardrail for detecting Personally Identifiable Information (PII)."""

    def __init__(
        self,
        mask_pii: bool = False,
        strategy: Optional[Literal["block", "mask", "replace", "redact", "tokenize"]] = None,
        pii_engine: Literal["regex", "presidio"] = "regex",
        enable_ssn_check: bool = True,
        enable_credit_card_check: bool = True,
        enable_email_check: bool = True,
        enable_phone_check: bool = True,
        custom_patterns: Optional[Dict[str, re.Pattern[str]]] = None,
        dry_run: bool = False,
        on_fail: Optional[OnFailCallback] = None,
    ):
        """Initialize a new PIIDetectionGuardrail.

        Args:
            mask_pii: If True, mask PII instead of raising an error.
            strategy: How to handle detected PII. Overrides mask_pii if provided.
                     Options: "block", "mask", "replace", "redact", "tokenize".
            pii_engine: Detection engine. "regex" (default, fast) or "presidio"
                       (NER-based, requires presidio-analyzer).
            enable_ssn_check: Whether to check for Social Security Numbers.
            enable_credit_card_check: Whether to check for credit cards.
            enable_email_check: Whether to check for emails.
            enable_phone_check: Whether to check for phone numbers.
            custom_patterns: Custom PII patterns to detect (regex engine only).
            dry_run: If True, logs violations without raising errors.
            on_fail: Optional callback invoked when a check fails.
                     Receives (error, input_data, context).
        """
        super().__init__(dry_run=dry_run, on_fail=on_fail)

        # Explicit strategy parameter overrides mask_pii
        if strategy is not None:
            self.strategy = strategy
        else:
            self.strategy = "mask" if mask_pii else "block"

        self.pii_engine = pii_engine
        self.pii_mapping: Dict[str, str] = {}  # For tokenize strategy: {token: original}
        self.token_counter = 0

        if pii_engine == "presidio":
            try:
                from presidio_analyzer import AnalyzerEngine  # type: ignore[import-not-found]

                self.analyzer = AnalyzerEngine()
            except ImportError:
                raise ImportError(
                    "`presidio-analyzer` not installed. "
                    "Install using `pip install presidio-analyzer` or use pii_engine='regex'"
                )
        else:
            self.analyzer = None

        self.pii_patterns = {}

        if enable_ssn_check:
            self.pii_patterns["SSN"] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
        if enable_credit_card_check:
            self.pii_patterns["Credit Card"] = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
        if enable_email_check:
            self.pii_patterns["Email"] = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
        if enable_phone_check:
            self.pii_patterns["Phone"] = re.compile(r"\b\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b")

        if custom_patterns:
            self.pii_patterns.update(custom_patterns)

    def _detect_pii_regex(self, content: str) -> List[Tuple[str, int, int, str]]:
        """Detect PII using regex patterns. Returns list of (pii_type, start, end, matched_text)."""
        detected = []
        for pii_type, pattern in self.pii_patterns.items():
            for match in pattern.finditer(content):
                detected.append((pii_type, match.start(), match.end(), match.group(0)))
        detected.sort(key=lambda x: x[1])
        return detected

    def _detect_pii_presidio(self, content: str) -> List[Tuple[str, int, int, str]]:
        """Detect PII using Presidio analyzer. Returns list of (pii_type, start, end, matched_text)."""
        if self.analyzer is None:
            raise RuntimeError("Presidio analyzer not initialized")

        results = self.analyzer.analyze(text=content, language="en")
        detected = []
        for result in results:
            matched_text = content[result.start : result.end]
            detected.append((result.entity_type, result.start, result.end, matched_text))
        detected.sort(key=lambda x: x[1])
        return detected

    def _apply_strategy(self, content: str, detected: List[Tuple[str, int, int, str]]) -> str:
        """Apply the selected strategy to transform content based on detected PII."""
        if not detected:
            return content

        # Process in reverse order to maintain indices
        for pii_type, start, end, matched_text in reversed(detected):
            if self.strategy == "mask":
                replacement = "*" * len(matched_text)
            elif self.strategy == "replace":
                replacement = f"[{pii_type.upper()}]"
            elif self.strategy == "redact":
                replacement = ""
            elif self.strategy == "tokenize":
                token = f"<PII_{self.token_counter}>"
                self.pii_mapping[token] = matched_text
                self.token_counter += 1
                replacement = token
            else:
                continue

            content = content[:start] + replacement + content[end:]

        return content

    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check for PII patterns in the input."""
        # Reset tokenize state per-call to prevent cross-request leakage
        if self.strategy == "tokenize":
            self.pii_mapping = {}
            self.token_counter = 0

        content = run_input.input_content_string()

        if self.pii_engine == "presidio":
            detected = self._detect_pii_presidio(content)
        else:
            detected = self._detect_pii_regex(content)

        if not detected:
            return

        detected_types = [pii_type for pii_type, _, _, _ in detected]

        if self.strategy == "block":
            error = InputCheckError(
                "Potential PII detected in input",
                additional_data={"detected_pii": detected_types},
                check_trigger=CheckTrigger.PII_DETECTED,
            )
            self._handle_violation(
                error, "PIIDetectionGuardrail", "pre_check", f"types={detected_types}", input_data=run_input
            )
            return

        content = self._apply_strategy(content, detected)
        run_input.input_content = content

    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Asynchronously check for PII patterns in the input."""
        # Reset tokenize state per-call to prevent cross-request leakage
        if self.strategy == "tokenize":
            self.pii_mapping = {}
            self.token_counter = 0

        content = run_input.input_content_string()

        if self.pii_engine == "presidio":
            detected = self._detect_pii_presidio(content)
        else:
            detected = self._detect_pii_regex(content)

        if not detected:
            return

        detected_types = [pii_type for pii_type, _, _, _ in detected]

        if self.strategy == "block":
            error = InputCheckError(
                "Potential PII detected in input",
                additional_data={"detected_pii": detected_types},
                check_trigger=CheckTrigger.PII_DETECTED,
            )
            self._handle_violation(
                error, "PIIDetectionGuardrail", "async_pre_check", f"types={detected_types}", input_data=run_input
            )
            return

        content = self._apply_strategy(content, detected)
        run_input.input_content = content

    def model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Check all messages for PII before model processes them."""
        content = extract_all_text_from_run_messages(run_messages)

        if self.pii_engine == "presidio":
            detected = self._detect_pii_presidio(content)
        else:
            detected = self._detect_pii_regex(content)

        if not detected:
            return

        detected_types = [pii_type for pii_type, _, _, _ in detected]

        # model_check always blocks on detection (can't modify RunMessages)
        error = InputCheckError(
            "Potential PII detected in messages",
            additional_data={"detected_pii": detected_types},
            check_trigger=CheckTrigger.PII_DETECTED,
        )
        self._handle_violation(
            error, "PIIDetectionGuardrail", "model_check", f"types={detected_types}", input_data=run_messages
        )

    async def async_model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Async check all messages for PII before model processes them."""
        self.model_check(run_messages, **kwargs)

    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Check for PII in output content."""
        content = str(run_output.content) if run_output.content else ""

        if self.pii_engine == "presidio":
            detected = self._detect_pii_presidio(content)
        else:
            detected = self._detect_pii_regex(content)

        if not detected:
            return

        if self.strategy == "block":
            detected_types = [pii_type for pii_type, _, _, _ in detected]
            error = OutputCheckError(
                "Potential PII detected in output",
                additional_data={"detected_pii": detected_types},
            )
            self._handle_violation(
                error, "PIIDetectionGuardrail", "post_check", f"types={detected_types}", input_data=run_output
            )

    async def async_post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Async check for PII in output content."""
        self.post_check(run_output)

    def restore(self, content: str) -> str:
        """Restore original PII from tokenized content.

        Args:
            content: The content with PII tokens to restore.

        Returns:
            Content with tokens replaced by original PII values.
        """
        for token, original in self.pii_mapping.items():
            content = content.replace(token, original)
        return content
