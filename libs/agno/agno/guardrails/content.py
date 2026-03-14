import re
from typing import Any, List, Literal, Optional, Union

from agno.exceptions import CheckTrigger, InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail, OnFailCallback
from agno.run.agent import RunInput, RunOutput
from agno.run.messages import RunMessages
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.utils.guardrails import extract_all_text_from_run_messages


class ContentGuardrail(BaseGuardrail):
    """Guardrail for detecting jailbreak, toxicity, and off-topic content."""

    def __init__(
        self,
        check_jailbreak: bool = True,
        check_toxicity: bool = False,
        check_off_topic: bool = False,
        jailbreak_patterns: Optional[List[str]] = None,
        toxicity_patterns: Optional[List[str]] = None,
        allowed_topics: Optional[List[str]] = None,
        check_output: bool = False,
        dry_run: bool = False,
        on_fail: Optional[OnFailCallback] = None,
    ):
        """Initialize a new ContentGuardrail.

        Args:
            check_jailbreak: Whether to check for jailbreak attempts.
            check_toxicity: Whether to check for toxic content.
            check_off_topic: Whether to check for off-topic content.
            jailbreak_patterns: Custom patterns to extend default jailbreak detection.
            toxicity_patterns: Custom patterns to extend default toxicity detection.
            allowed_topics: Allowed topics for off-topic detection. Required if check_off_topic=True.
            check_output: Whether to also check output in post_check.
            dry_run: If True, logs violations without raising errors.
            on_fail: Optional callback invoked when a check fails.
                     Receives (error, input_data, context).
        """
        super().__init__(dry_run=dry_run, on_fail=on_fail)
        self.check_jailbreak = check_jailbreak
        self.check_toxicity = check_toxicity
        self.check_off_topic = check_off_topic
        self.check_output = check_output
        self.allowed_topics = allowed_topics

        # Default jailbreak patterns
        self.jailbreak_patterns = [
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

        if jailbreak_patterns:
            self.jailbreak_patterns.extend(jailbreak_patterns)

        # Default toxicity patterns
        self.toxicity_patterns = [
            "hate speech",
            "profanity",
            "harassment",
            "abuse",
            "threat",
            "violence",
            "offensive",
        ]

        if toxicity_patterns:
            self.toxicity_patterns.extend(toxicity_patterns)

        if check_off_topic and not allowed_topics:
            raise ValueError("allowed_topics must be provided when check_off_topic=True")

    def _check_jailbreak(self, content: str) -> List[str]:
        """Check if content contains jailbreak patterns. Returns list of matched patterns."""
        content_lower = content.lower()
        return [pattern for pattern in self.jailbreak_patterns if pattern in content_lower]

    def _check_toxicity(self, content: str) -> List[str]:
        """Check if content contains toxic patterns. Returns list of matched patterns."""
        content_lower = content.lower()
        return [pattern for pattern in self.toxicity_patterns if pattern in content_lower]

    def _check_off_topic(self, content: str) -> bool:
        """Check if content is off-topic using word boundary matching."""
        if not self.allowed_topics:
            return False
        # Word boundary matching to avoid false positives (e.g. "AI" matching "failure")
        return not any(
            re.search(r"\b" + re.escape(topic) + r"\b", content, re.IGNORECASE) for topic in self.allowed_topics
        )

    def _validate_content(
        self, content: str, content_type: Literal["input", "output"], check_type: str, input_data: Any = None
    ) -> None:
        """Validate content against all enabled checks."""
        detected_issues = []
        matched_patterns: List[str] = []

        if self.check_jailbreak:
            jailbreak_matches = self._check_jailbreak(content)
            if jailbreak_matches:
                detected_issues.append("jailbreak_attempt")
                matched_patterns.extend(jailbreak_matches)

        if self.check_toxicity:
            toxicity_matches = self._check_toxicity(content)
            if toxicity_matches:
                detected_issues.append("toxic_content")
                matched_patterns.extend(toxicity_matches)

        if self.check_off_topic and self._check_off_topic(content):
            detected_issues.append("off_topic")

        if detected_issues:
            if "jailbreak_attempt" in detected_issues:
                check_trigger = CheckTrigger.PROMPT_INJECTION
                message = "Potential jailbreaking or prompt injection detected"
            elif "toxic_content" in detected_issues:
                check_trigger = CheckTrigger.INPUT_NOT_ALLOWED
                message = "Toxic content detected"
            else:
                check_trigger = CheckTrigger.INPUT_NOT_ALLOWED
                message = f"Content validation failed: {content_type}"

            additional_data = {
                "detected_issues": detected_issues,
                "matched_patterns": matched_patterns,
                "content_type": content_type,
            }

            if content_type == "output":
                check_trigger = CheckTrigger.OUTPUT_NOT_ALLOWED
                error: Exception = OutputCheckError(
                    message,
                    additional_data=additional_data,
                    check_trigger=check_trigger,
                )
            else:
                error = InputCheckError(
                    message,
                    additional_data=additional_data,
                    check_trigger=check_trigger,
                )
            self._handle_violation(
                error, "ContentGuardrail", check_type, f"issues={detected_issues}", input_data=input_data
            )

    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check input content for jailbreak, toxicity, and off-topic issues."""
        content = run_input.input_content_string()
        self._validate_content(content, "input", "pre_check", input_data=run_input)

    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Async check input content for jailbreak, toxicity, and off-topic issues."""
        content = run_input.input_content_string()
        self._validate_content(content, "input", "async_pre_check", input_data=run_input)

    def model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Check all messages for content issues before model processes them."""
        content = extract_all_text_from_run_messages(run_messages)
        self._validate_content(content, "input", "model_check", input_data=run_messages)

    async def async_model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Async check all messages for content issues before model processes them."""
        content = extract_all_text_from_run_messages(run_messages)
        self._validate_content(content, "input", "async_model_check", input_data=run_messages)

    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Check output content if check_output is enabled."""
        if not self.check_output:
            return

        content = str(run_output.content) if run_output.content else ""
        self._validate_content(content, "output", "post_check", input_data=run_output)

    async def async_post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Async check output content if check_output is enabled."""
        if not self.check_output:
            return

        content = str(run_output.content) if run_output.content else ""
        self._validate_content(content, "output", "async_post_check", input_data=run_output)
