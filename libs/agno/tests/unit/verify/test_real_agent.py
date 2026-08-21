"""Runner tests against a REAL Agent with a scripted offline Model.

The StubAgent hides core behaviour these regressions live in: real continue_run forking,
session-state loading, and the HITL pause machinery.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Iterator, List, Optional

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunContext
from agno.tools.decorator import tool
from agno.verify import VerifierLimits, arun_verified, run_verified


class ScriptedModel(Model):
    """Returns one scripted ModelResponse per provider call, in order."""

    def __init__(self, script: List[ModelResponse]) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0

    def __deepcopy__(self, memo: Any) -> "ScriptedModel":
        return self  # one shared call counter, whatever the agent copies

    def _next(self) -> ModelResponse:
        response = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _tool_call(name: str, call_id: str, arguments: Optional[dict] = None) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments or {})},
            }
        ],
    )


def _text(content: str) -> ModelResponse:
    return ModelResponse(role="assistant", content=content)


# ---------------------------------------------------------------------------
# F3: session_state carried across continuations on a db-less agent
# ---------------------------------------------------------------------------


def _state_probe(seen: List[dict]):
    def probe_state(run_context: Optional[RunContext] = None) -> str:
        """Record the session state this call can see."""
        seen.append(dict(run_context.session_state or {}) if run_context else {})
        return "probed"

    return probe_state


def _probe_script() -> List[ModelResponse]:
    return [
        _tool_call("probe_state", "call-1"),
        _text("attempt 0 done"),
        _tool_call("probe_state", "call-2"),
        _text("attempt 1 done"),
    ]


def _fail_once():
    calls = {"n": 0}

    def check(run):
        calls["n"] += 1
        return True if calls["n"] > 1 else "not yet"

    return check


def test_session_state_carries_to_continuation_without_a_db():
    seen: List[dict] = []
    agent = Agent(model=ScriptedModel(_probe_script()), tools=[_state_probe(seen)])
    result = run_verified(
        agent,
        "probe twice",
        [_fail_once()],
        limits=VerifierLimits(max_continuations=1),
        session_state={"k": "CALLER_STATE"},
    )
    assert result.status == "verified"
    assert len(seen) == 2
    assert seen[0].get("k") == "CALLER_STATE"
    assert seen[1].get("k") == "CALLER_STATE", f"continuation lost the caller state: {seen[1]}"


@pytest.mark.asyncio
async def test_session_state_carries_to_continuation_without_a_db_async():
    seen: List[dict] = []
    agent = Agent(model=ScriptedModel(_probe_script()), tools=[_state_probe(seen)])
    result = await arun_verified(
        agent,
        "probe twice",
        [_fail_once()],
        limits=VerifierLimits(max_continuations=1),
        session_state={"k": "CALLER_STATE"},
    )
    assert result.status == "verified"
    assert seen[1].get("k") == "CALLER_STATE"


def _clearing_probe(seen: List[dict]):
    def probe_state(run_context: Optional[RunContext] = None) -> str:
        """Record the session state this call can see, then empty it."""
        state = run_context.session_state if run_context else None
        seen.append(dict(state or {}))
        if state is not None:
            state.clear()
        return "cleared"

    return probe_state


@pytest.mark.parametrize(
    "mode",
    [
        "sync",
        pytest.param(
            "async",
            marks=pytest.mark.xfail(
                strict=True,
                reason=(
                    "core divergence: _acontinue_run reloads session_state through "
                    "load_session_state, which MERGES the stored state back over the carried "
                    "one, so a deletion cannot survive. The sync _continue_run does not reload "
                    "at all. Six call sites share that reload, so straightening it out belongs "
                    "in a core change, not here."
                ),
            ),
        ),
    ],
)
def test_a_cleared_session_state_stays_cleared_across_continuations(mode):
    """An attempt that empties session_state must not have the agent's declared state
    resurrected under it. Carrying state forward on a truthiness check skips the empty dict,
    and the continuation reloads the seed — silently undoing deliberate work."""
    seen: List[dict] = []
    # The seed lives on the Agent: that is what a continuation reloads when no run_context is
    # threaded through, and therefore what resurrects over the cleared state.
    agent = Agent(
        model=ScriptedModel(_probe_script()),
        tools=[_clearing_probe(seen)],
        session_state={"cart": ["seed"]},
    )
    kwargs = dict(limits=VerifierLimits(max_continuations=1))
    if mode == "sync":
        run_verified(agent, "probe twice", [_fail_once()], **kwargs)
    else:
        asyncio.run(arun_verified(agent, "probe twice", [_fail_once()], **kwargs))
    assert len(seen) == 2
    assert seen[0].get("cart") == ["seed"]
    assert "cart" not in seen[1], f"the continuation resurrected cleared state: {seen[1]}"


def test_run_context_in_run_kwargs_is_rejected():
    agent = Agent(model=ScriptedModel([_text("x")]))
    with pytest.raises(ValueError, match="run_context"):
        run_verified(agent, "task", [lambda run: True], run_context=RunContext(run_id="r", session_id="s"))


# ---------------------------------------------------------------------------
# F9: a paused continuation carries no stale pending stamp
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def deploy() -> str:
    """Deploy the change."""
    return "deployed"


def test_paused_continuation_output_is_unstamped(tmp_path):
    agent = Agent(
        model=ScriptedModel(
            [
                _text("claimed done"),  # attempt 0 completes; verifier fails
                _tool_call("deploy", "call-deploy"),  # continuation pauses on confirmation
            ]
        ),
        tools=[deploy],
        db=SqliteDb(db_file=str(tmp_path / "verify.db")),
    )
    result = run_verified(
        agent,
        "do the deploy",
        [lambda run: "nothing deployed yet"],
        limits=VerifierLimits(max_continuations=2),
        session_id="pause-1",
    )
    assert result.stop_reason == "paused"
    assert result.status == "unverified"
    assert len(result.attempts) == 2
    assert result.attempts[1].status == "PAUSED"
    metadata = result.output.metadata or {}
    assert "verification" not in metadata, f"stale pending stamp returned to the HITL caller: {metadata}"
    # The parent attempt's own record is intact on the returned VerifiedRun.
    assert result.attempts[0].verdicts and result.attempts[0].verdicts[0].passed is False


def test_verified_run_on_db_agent_keeps_final_stamp(tmp_path):
    agent = Agent(
        model=ScriptedModel([_text("first"), _text("second")]),
        db=SqliteDb(db_file=str(tmp_path / "verify.db")),
    )
    result = run_verified(
        agent,
        "task",
        [_fail_once()],
        limits=VerifierLimits(max_continuations=1),
        session_id="stamp-1",
    )
    assert result.status == "verified"
    assert result.output.metadata["verification"]["status"] == "verified"


def _run_id_probe(seen: List[dict]):
    def probe_state(run_context: Optional[RunContext] = None) -> str:
        """Record which run this call believes it belongs to."""
        state = (run_context.session_state or {}) if run_context else {}
        seen.append(
            {
                "context": run_context.run_id if run_context else None,
                "state": state.get("current_run_id"),
            }
        )
        return "probed"

    return probe_state


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_each_attempt_reports_its_own_run_id_not_the_parents(mode, tmp_path):
    """Continuing a completed run forks a sibling with a fresh run_id, but the RunContext is
    built before the fork. Left unbound, every attempt after the first files its tool calls,
    hooks and reasoning steps under the PREVIOUS run, and session_state carries a stale
    current_run_id — so the per-attempt audit trail run_verified advertises is wrong.
    """
    seen: List[dict] = []
    agent = Agent(
        model=ScriptedModel(_probe_script()),
        tools=[_run_id_probe(seen)],
        db=SqliteDb(db_file=str(tmp_path / "runid.db")),
    )
    kwargs = dict(limits=VerifierLimits(max_continuations=1), session_id=f"runid-{mode}")
    if mode == "sync":
        result = run_verified(agent, "probe twice", [_fail_once()], **kwargs)
    else:
        result = asyncio.run(arun_verified(agent, "probe twice", [_fail_once()], **kwargs))

    assert len(result.attempts) == 2
    first, second = result.attempts[0].run_id, result.attempts[1].run_id
    assert first != second, "the continuation did not fork a sibling run"
    assert len(seen) == 2
    assert seen[0]["context"] == first
    assert seen[1]["context"] == second, f"the continuation's tool saw the parent run_id: {seen[1]}"
    assert seen[1]["state"] == second, f"session_state carried a stale current_run_id: {seen[1]}"
