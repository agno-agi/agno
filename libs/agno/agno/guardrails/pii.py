import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from agno.exceptions import CheckTrigger, InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail, OnFailCallback
from agno.run.agent import RunInput, RunOutput
from agno.run.messages import RunMessages
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.utils.guardrails import extract_all_text_from_run_messages
from agno.utils.log import log_warning


class PIIDetectionGuardrail(BaseGuardrail):
    """Guardrail for detecting Personally Identifiable Information (PII).

    Detects PII in text content using regex patterns or Presidio NER.
    Supports strategies: block, mask, replace, redact, tokenize.

    Note: This guardrail only inspects text content.
    """

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
        include_pii_in_callback: bool = False,
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
                    For strategy="block", content is redacted as a safety fallback.
            on_fail: Optional callback invoked when a check fails.
                     Receives (error, input_data, context). The context dict
                     includes "original_content" and "detected_pii_values" for
                     audit logging purposes.
        """
        super().__init__(dry_run=dry_run, on_fail=on_fail)

        self.mask_pii = mask_pii
        self.include_pii_in_callback = include_pii_in_callback

        # Explicit strategy parameter overrides mask_pii
        if strategy is not None:
            self.strategy = strategy
        else:
            self.strategy = "mask" if mask_pii else "block"

        self.pii_engine = pii_engine
        # Convenience access to last call's mapping (not thread-safe for concurrent use)
        self.pii_mapping: Dict[str, str] = {}
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

    def _apply_strategy(
        self,
        content: str,
        detected: List[Tuple[str, int, int, str]],
        strategy_override: Optional[str] = None,
        pii_mapping: Optional[Dict[str, str]] = None,
        token_counter_start: int = 0,
    ) -> Tuple[str, Dict[str, str], int]:
        """Apply the selected strategy to transform content based on detected PII.

        Args:
            content: The content to transform.
            detected: List of detected PII entries.
            strategy_override: Override the instance strategy (used for dry_run fallback).
            pii_mapping: Dict to store token->original mappings (for tokenize strategy).
            token_counter_start: Starting counter for token generation.

        Returns:
            Tuple of (transformed_content, pii_mapping, next_token_counter).
        """
        if not detected:
            return content, pii_mapping or {}, token_counter_start

        strategy = strategy_override or self.strategy
        if pii_mapping is None:
            pii_mapping = {}
        token_counter = token_counter_start

        # Process in reverse order to maintain indices
        for pii_type, start, end, matched_text in reversed(detected):
            if strategy == "mask":
                replacement = "*" * len(matched_text)
            elif strategy == "replace":
                replacement = f"[{pii_type.upper()}]"
            elif strategy == "redact":
                replacement = ""
            elif strategy == "tokenize":
                token = f"<PII_{token_counter}>"
                pii_mapping[token] = matched_text
                token_counter += 1
                replacement = token
            else:
                continue

            content = content[:start] + replacement + content[end:]

        return content, pii_mapping, token_counter

    def _notify_pii_detected(
        self,
        detected: List[Tuple[str, int, int, str]],
        original_content: str,
        check_type: str,
        input_data: Any,
    ) -> None:
        """Notify on_fail callback about detected PII (for non-block strategies)."""
        if self.on_fail is None:
            return

        detected_types = [pii_type for pii_type, _, _, _ in detected]
        context: Dict[str, Any] = {
            "guardrail_name": "PIIDetectionGuardrail",
            "check_type": check_type,
            "additional_info": f"types={detected_types}",
        }
        # Only include raw PII values when explicitly opted in
        if self.include_pii_in_callback:
            detected_values = [matched for _, _, _, matched in detected]
            context["original_content"] = original_content
            context["detected_pii_values"] = detected_values
        try:
            error = InputCheckError(
                "PII detected and transformed",
                additional_data={"detected_pii": detected_types},
                check_trigger=CheckTrigger.PII_DETECTED,
            )
            self.on_fail(error, input_data, context)
        except Exception as callback_error:
            log_warning(f"on_fail callback raised an exception: {callback_error}")

    def _store_pii_mapping(self, run_input: Union[RunInput, TeamRunInput], pii_mapping: Dict[str, str]) -> None:
        """Store the PII mapping on the RunInput/TeamRunInput for thread-safe access."""
        if run_input.extra_data is None:
            run_input.extra_data = {}
        run_input.extra_data["pii_mapping"] = pii_mapping

    def _run_pre_check(self, run_input: Union[RunInput, TeamRunInput], check_type: str) -> None:
        """Shared logic for pre_check and async_pre_check."""
        # Use local state per call for thread safety
        local_mapping: Dict[str, str] = {}
        local_counter = 0

        # Track original type to avoid converting dict/list to str
        original_input = run_input.input_content
        is_string_input = isinstance(original_input, str)
        content = run_input.input_content_string()
        original_content = content

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
                error, "PIIDetectionGuardrail", check_type, f"types={detected_types}", input_data=run_input
            )
            # dry_run mode: _handle_violation logged but didn't raise.
            # Fall back to redacting content so PII doesn't reach the model.
            if self.dry_run:
                if is_string_input:
                    content, local_mapping, local_counter = self._apply_strategy(
                        content, detected, strategy_override="redact"
                    )
                    run_input.input_content = content
                # Non-string input in dry_run: already logged by _handle_violation, continue
            return

        # Notify on_fail with original content before transformation
        self._notify_pii_detected(detected, original_content, check_type, run_input)

        if is_string_input:
            content, local_mapping, local_counter = self._apply_strategy(
                content, detected, pii_mapping=local_mapping, token_counter_start=local_counter
            )
            run_input.input_content = content
        else:
            # Non-string input (dict/list): can't apply strategy without losing type, block instead
            error = InputCheckError(
                "PII detected in structured input (cannot transform without losing type)",
                additional_data={"detected_pii": detected_types},
                check_trigger=CheckTrigger.PII_DETECTED,
            )
            self._handle_violation(
                error, "PIIDetectionGuardrail", check_type, f"types={detected_types}", input_data=run_input
            )
            return

        # Store mapping on RunInput for thread-safe access
        self._store_pii_mapping(run_input, local_mapping)

        # Update instance state as convenience (not thread-safe)
        self.pii_mapping = local_mapping
        self.token_counter = local_counter

    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check for PII patterns in the input."""
        self._run_pre_check(run_input, "pre_check")

    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Asynchronously check for PII patterns in the input."""
        self._run_pre_check(run_input, "async_pre_check")

    def model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Check all messages for PII before model processes them.

        Note: model_check can only block on detection since RunMessages should
        not be mutated by guardrails. Use pre_check for transformation strategies.
        """
        content = extract_all_text_from_run_messages(run_messages)

        if self.pii_engine == "presidio":
            detected = self._detect_pii_presidio(content)
        else:
            detected = self._detect_pii_regex(content)

        if not detected:
            return

        detected_types = [pii_type for pii_type, _, _, _ in detected]

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
        """Check for PII in output content.

        For strategy="block", raises OutputCheckError.
        For other strategies (mask/replace/redact/tokenize), transforms
        run_output.content in place so PII is scrubbed before reaching the user.
        """
        content = str(run_output.content) if run_output.content else ""

        if self.pii_engine == "presidio":
            detected = self._detect_pii_presidio(content)
        else:
            detected = self._detect_pii_regex(content)

        if not detected:
            return

        detected_types = [pii_type for pii_type, _, _, _ in detected]

        if self.strategy == "block":
            error = OutputCheckError(
                "Potential PII detected in output",
                additional_data={"detected_pii": detected_types},
            )
            self._handle_violation(
                error, "PIIDetectionGuardrail", "post_check", f"types={detected_types}", input_data=run_output
            )
            return

        # Non-block strategies: transform the output content
        self._notify_pii_detected(detected, content, "post_check", run_output)
        transformed, _, _ = self._apply_strategy(content, detected)
        run_output.content = transformed

    async def async_post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Async check for PII in output content."""
        self.post_check(run_output)

    def restore(self, content: str, pii_mapping: Optional[Dict[str, str]] = None) -> str:
        """Restore original PII from tokenized content.

        Args:
            content: The content with PII tokens to restore.
            pii_mapping: Optional mapping to use. If not provided, uses the
                        instance's last pii_mapping (not thread-safe).
                        For thread-safe usage, pass run_input.extra_data["pii_mapping"].

        Returns:
            Content with tokens replaced by original PII values.
        """
        mapping = pii_mapping if pii_mapping is not None else self.pii_mapping
        for token, original in mapping.items():
            content = content.replace(token, original)
        return content
