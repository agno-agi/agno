"""ATR (Agent Threat Rules) guardrail.

Agent Threat Rules (ATR) is an open, community-maintained detection standard for
AI-agent attacks -- like Sigma, but for prompt injection, tool poisoning, MCP
attacks, and skill compromise. This guardrail applies the rule set at the input
stage, so it is most effective against input-borne attacks such as prompt
injection and jailbreak attempts.

Requires the ``pyatr`` package, which bundles the rule set::

    pip install pyatr
"""

from typing import Optional, Sequence, Union

from agno.exceptions import CheckTrigger, InputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput
from agno.utils.log import log_debug

# ATR match severities that escalate to a blocking error by default. Lower
# severities ("medium", "low") are logged but allowed through, keeping false
# positives low and complementing -- rather than duplicating -- simpler keyword
# guardrails such as PromptInjectionGuardrail.
_DEFAULT_BLOCK_SEVERITIES = ("critical", "high")


class ATRGuardrail(BaseGuardrail):
    """Guardrail backed by Agent Threat Rules (ATR).

    Evaluates the run input against the ATR rule set bundled with the ``pyatr``
    package and raises :class:`~agno.exceptions.InputCheckError` when a rule at
    or above a configured severity matches. Where ``PromptInjectionGuardrail``
    uses a fixed keyword list, this evaluates input against a continuously
    updated, severity-rated community rule set, so it is best used alongside the
    other guardrails rather than as a replacement.

    Args:
        block_severities (Sequence[str]): ATR match severities that raise an
            error. Matches below these severities are logged but allowed
            through. Defaults to ``("critical", "high")``.
        rules_dir (Optional[str]): Path to a directory of ATR rule YAML files.
            When omitted, the rule set bundled with the installed ``pyatr``
            package is used (works after a plain ``pip install pyatr``).

    Raises:
        ImportError: If the ``pyatr`` package is not installed.
    """

    def __init__(
        self,
        block_severities: Sequence[str] = _DEFAULT_BLOCK_SEVERITIES,
        rules_dir: Optional[str] = None,
    ):
        try:
            from pyatr import ATREngine
        except ImportError:
            raise ImportError("`pyatr` not installed. Please install using `pip install pyatr`")

        self.block_severities = {severity.lower() for severity in block_severities}

        self._engine = ATREngine()
        if rules_dir is not None:
            self._engine.load_rules_from_directory(rules_dir)
        else:
            self._engine.load_default_rules()

    def _detect(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Evaluate the input against ATR rules and raise on a blocking match."""
        from pyatr import AgentEvent

        content = run_input.input_content_string()
        if not content:
            return

        matches = self._engine.evaluate(AgentEvent(content=content, event_type="llm_input"))
        if not matches:
            return

        blocking = [match for match in matches if match.severity.lower() in self.block_severities]
        if not blocking:
            log_debug(
                f"ATR matched {len(matches)} rule(s) below the block threshold: "
                f"{', '.join(match.rule_id for match in matches)}"
            )
            return

        raise InputCheckError(
            f"Input blocked by Agent Threat Rules: matched {len(blocking)} rule(s) "
            f"(max severity: {blocking[0].severity}).",
            additional_data={
                "matched_rules": [match.rule_id for match in blocking],
                "matched_titles": [match.title for match in blocking],
                "max_severity": blocking[0].severity,
            },
            check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
        )

    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check the input against ATR rules (synchronous)."""
        self._detect(run_input)

    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check the input against ATR rules (asynchronous)."""
        self._detect(run_input)
