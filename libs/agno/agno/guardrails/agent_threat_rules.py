from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agno.exceptions import CheckTrigger, InputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput


_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


@dataclass
class _AgentThreatEvent:
    content: str = ""
    event_type: str = "llm_input"
    fields: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, str] = field(default_factory=dict)


class AgentThreatRulesGuardrail(BaseGuardrail):
    """Guardrail backed by Agent Threat Rules (ATR).

    Args:
        rules_dir: Optional directory of ATR YAML rules. When omitted, pyatr's bundled rules are used.
        block_severity: Minimum severity to block. Defaults to "medium".
        engine: Optional preconfigured ATR engine, primarily useful for tests.
        event_factory: Optional factory used to build ATR events for a custom engine.
    """

    def __init__(
        self,
        rules_dir: Optional[Union[str, Path]] = None,
        block_severity: str = "medium",
        engine: Optional[Any] = None,
        event_factory: Optional[Any] = None,
    ):
        if block_severity not in _SEVERITY_ORDER:
            raise ValueError(f"block_severity must be one of {', '.join(_SEVERITY_ORDER)}")

        self.rules_dir = Path(rules_dir) if rules_dir is not None else None
        self.block_severity = block_severity
        self.engine = engine
        self.event_factory = event_factory

        if self.engine is None:
            self.engine, self.event_factory = self._build_pyatr_engine()
        elif self.event_factory is None:
            self.event_factory = self._default_event_factory()

    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check the input against ATR rules."""
        matches = self._evaluate(run_input.input_content_string())
        blocking_matches = [match for match in matches if self._should_block(match)]
        if blocking_matches:
            raise InputCheckError(
                "Agent threat detected in input",
                check_trigger=CheckTrigger.AGENT_THREAT_DETECTED,
                additional_data={"matches": [self._serialize_match(match) for match in blocking_matches]},
            )

    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Asynchronously check the input against ATR rules."""
        self.check(run_input)

    def _build_pyatr_engine(self):
        try:
            from pyatr import ATREngine, AgentEvent
        except ImportError as exc:
            raise ImportError(
                "AgentThreatRulesGuardrail requires the optional 'pyatr' package. "
                "Install it with `pip install pyatr` or `pip install agno[guardrails]`."
            ) from exc

        engine = ATREngine()
        if self.rules_dir is not None:
            engine.load_rules_from_directory(self.rules_dir)
        else:
            engine.load_default_rules()
        return engine, AgentEvent

    @staticmethod
    def _default_event_factory():
        try:
            from pyatr import AgentEvent

            return AgentEvent
        except ImportError:
            return _AgentThreatEvent

    def _evaluate(self, content: str) -> List[Any]:
        event = self.event_factory(
            content=content,
            event_type="llm_input",
            fields={"user_input": content},
            metadata={"source": "agno.guardrails"},
        )
        return list(self.engine.evaluate(event))

    def _should_block(self, match: Any) -> bool:
        severity = str(getattr(match, "severity", "")).lower()
        return _SEVERITY_ORDER.get(severity, 99) <= _SEVERITY_ORDER[self.block_severity]

    @staticmethod
    def _serialize_match(match: Any) -> Dict[str, Any]:
        return {
            "rule_id": getattr(match, "rule_id", None),
            "title": getattr(match, "title", None),
            "severity": getattr(match, "severity", None),
            "confidence": getattr(match, "confidence", None),
            "matched_patterns": list(getattr(match, "matched_patterns", ())),
            "description": getattr(match, "description", None),
            "tags": getattr(match, "tags", {}),
        }
