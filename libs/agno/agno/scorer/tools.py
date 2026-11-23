"""ToolCallScorer: deterministic tool-call checking against executions."""

import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Union

from agno.models.response import ToolExecution
from agno.run.team import TeamRunOutput
from agno.scorer.base import AnyRunOutput, FingerprintError, Score


def _members_carry_tools(response: Any) -> bool:
    """True when any member -- at any nesting depth -- carries tool executions.

    A member can itself be a TeamRunOutput whose leader ran no tools while its own
    members did; the limitation note must fire for that shape too.
    """
    for member in getattr(response, "member_responses", None) or []:
        if getattr(member, "tools", None):
            return True
        if _members_carry_tools(member):
            return True
    return False


class ToolCallScorer:
    """Check tool calls against `RunOutput.tools` -- the executions, not the requests.

    Request-side matching counts a call that was refused, errored, or given junk
    arguments, which makes it satisfiable without the tool ever doing work. An
    expectation here is satisfied only by an execution whose `tool_call_error` is not
    true (`None` counts as clean: rehydrated runs carry `None` for success).

    Matching semantics: order-insensitive; an expectation is satisfied by at least one
    clean execution of that name; duplicate expected names are satisfied by a single
    call (set semantics). Argument specs match by subset -- every expected key present
    with an equal value in `ToolExecution.tool_args`, extra actual keys allowed, no
    type coercion. `value` is the fraction of checks satisfied (name expectations plus
    argument specs, equally weighted); `passed` requires every check satisfied and,
    under `allow_additional=False`, no additional clean calls.

    The per-task `expected` argument of `score`/`ascore` is not consulted: tool
    expectations live on the constructor as `expected_tools`. A task suite whose
    per-task expectations are answers can still use this scorer; they simply don't
    reach it.

    For a `TeamRunOutput` only the top-level `tools` -- the leader's executions -- are
    inspected. Member tool matching is out of scope for 2.8.0; when member responses
    carry tools the `Score.reason` names the limitation.

    Name-only matching remains satisfiable by a successful call with junk arguments.
    For a strict check, set `arguments`.
    """

    def __init__(
        self,
        expected_tools: Sequence[str],
        *,
        arguments: Optional[Dict[str, Union[Dict[str, Any], List[Dict[str, Any]]]]] = None,
        allow_additional: bool = True,
    ) -> None:
        if isinstance(expected_tools, str):
            raise TypeError(f"expected_tools must be a sequence of tool names, not the bare string {expected_tools!r}")
        # Dedupe preserving declaration order: duplicate expected names are one check.
        self.expected_tools = list(dict.fromkeys(expected_tools))
        self.arguments = arguments
        self.allow_additional = allow_additional
        # A scorer with zero checks would vacuously green every run. Count the checks
        # exactly as score() will: an arguments entry whose spec list is empty
        # contributes none, so it is rejected too.
        n_spec_checks = 0
        for tool_name, raw_specs in (arguments or {}).items():
            specs = raw_specs if isinstance(raw_specs, list) else [raw_specs]
            if not specs:
                raise ValueError(f"argument specs for {tool_name!r} are empty; an empty list checks nothing")
            n_spec_checks += len(specs)
        if not self.expected_tools and n_spec_checks == 0:
            raise ValueError("ToolCallScorer needs expected_tools and/or arguments; with neither there is no check")

    def score(self, run: AnyRunOutput, expected: Any = None) -> Score:
        executions: List[ToolExecution] = list(run.tools or [])
        # A clean execution actually ran. Exclude rejected/errored calls
        # (tool_call_error) and still-paused calls that never executed (is_paused, true
        # only while awaiting confirmation/input/external-execution; cleared on resume).
        # A refused call never enters run.tools at all.
        clean = [t for t in executions if not t.tool_call_error and not t.is_paused]
        clean_names = {t.tool_name for t in clean if t.tool_name}

        notes: List[str] = []
        n_checks = 0
        n_satisfied = 0

        for name in self.expected_tools:
            n_checks += 1
            if name in clean_names:
                n_satisfied += 1
            else:
                notes.append(f"expected tool {name!r} has no clean execution")

        if self.arguments:
            for tool_name, raw_specs in self.arguments.items():
                specs = raw_specs if isinstance(raw_specs, list) else [raw_specs]
                candidates = [dict(t.tool_args or {}) for t in clean if t.tool_name == tool_name]
                for spec in specs:
                    n_checks += 1
                    if any(
                        all(key in args and args[key] == value for key, value in spec.items()) for args in candidates
                    ):
                        n_satisfied += 1
                    else:
                        notes.append(f"no clean {tool_name!r} execution matches arguments {spec!r}")

        # A call the scorer itself expects -- by name or through an argument spec --
        # is never "additional": an arguments-only strict scorer must be satisfiable.
        allowed_names = set(self.expected_tools) | set(self.arguments or {})
        additional = [name for name in sorted(clean_names) if name not in allowed_names]
        all_satisfied = n_satisfied == n_checks
        passed = all_satisfied
        if not self.allow_additional and additional:
            passed = False
            notes.append(f"additional tool calls not allowed: {additional}")

        if not executions:
            notes.insert(0, "run has no tool executions")
        if isinstance(run, TeamRunOutput) and _members_carry_tools(run):
            notes.append("member tool executions were not inspected (member matching is out of scope for 2.8.0)")

        # The constructor guarantees at least one check.
        value = n_satisfied / n_checks
        return Score(value=value, passed=passed, reason="; ".join(notes) if notes else None)

    async def ascore(self, run: AnyRunOutput, expected: Any = None) -> Score:
        return self.score(run, expected)

    def digest(self) -> str:
        """sha256 hex over the scorer's expectations, for `env_fingerprint`."""
        payload = {
            "expected_tools": sorted(self.expected_tools),
            "arguments": self.arguments,
            "allow_additional": self.allow_additional,
        }
        try:
            canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise FingerprintError(f"ToolCallScorer expectations are not JSON-serializable: {exc}") from exc
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
