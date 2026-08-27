"""Media ordering under the verification gate, and the truncation/record contract.

Two behaviors are pinned here:

- Verifiers judge the media of the attempt they are judging: every non-stream loop stores
  generated media INSIDE the attempt loop (before the gate opens), so media appends per
  attempt and accumulates across gate attempts exactly like the transcript does. The async
  and continue loops used to store once after the loop — verifiers saw zero images and
  earlier attempts' media was dropped from the final run.
- Time-travel truncation drops the verification record: attempts index into the transcript,
  so a record kept across a cut points at the wrong messages. `continue_from="end"` performs
  no truncation and keeps the record (and its budget_baseline semantics).
"""

import asyncio
from typing import Any, AsyncIterator, Iterator, List

from agno.agent import Agent
from agno.agent._run import _truncate_run_to_checkpoint
from agno.media import Image
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.verifiers import VerificationConfig
from agno.verifiers.types import Verification


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


def _text(content: str) -> ModelResponse:
    return ModelResponse(role="assistant", content=content)


def _image_response(content: str, url: str) -> ModelResponse:
    return ModelResponse(role="assistant", content=content, images=[Image(url=url)])


def image_counting_verifier(pass_from_attempt: int):
    """Records len(run_output.images) per attempt; passes from ``pass_from_attempt`` on."""
    seen: List[int] = []

    def check(run_output):
        seen.append(len(run_output.images or []))
        return True if len(seen) >= pass_from_attempt else "not yet"

    return check, seen


def _image_urls(out: RunOutput) -> List[str]:
    return [image.url for image in (out.images or [])]


# ---------------------------------------------------------------------------
# Media ordering: the verifier sees the media of its own attempt
# ---------------------------------------------------------------------------


def test_arun_verifier_sees_each_attempts_media():
    """Fail-then-pass on arun with one image per attempt: the verifier must see the
    first attempt's image on attempt 1 and both on attempt 2 (media accumulates like
    the transcript), and the final run carries both images."""
    model = ScriptedModel(
        [
            _image_response("attempt 1", "http://x/img1.png"),
            _image_response("attempt 2", "http://x/img2.png"),
        ]
    )
    check, seen = image_counting_verifier(pass_from_attempt=2)
    agent = Agent(model=model, verifiers=[check])

    out = asyncio.run(agent.arun("go"))

    assert model.calls == 2
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert seen == [1, 2]
    assert _image_urls(out) == ["http://x/img1.png", "http://x/img2.png"]


def test_run_verifier_sees_each_attempts_media():
    """Sync parity: the sync run loop already stored media per attempt — pin it."""
    model = ScriptedModel(
        [
            _image_response("attempt 1", "http://x/img1.png"),
            _image_response("attempt 2", "http://x/img2.png"),
        ]
    )
    check, seen = image_counting_verifier(pass_from_attempt=2)
    agent = Agent(model=model, verifiers=[check])

    out = agent.run("go")

    assert model.calls == 2
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert seen == [1, 2]
    assert _image_urls(out) == ["http://x/img1.png", "http://x/img2.png"]


def _unverified_run_then_image_continuation():
    """First run ends unverified with no media; the continuation's single attempt
    produces one image. Returns the agent, the recorded per-attempt image counts,
    the switch that releases the verifier, and the unverified run."""
    model = ScriptedModel([_text("try 1")])
    seen: List[int] = []
    state = {"pass": False}

    def check(run_output):
        seen.append(len(run_output.images or []))
        return True if state["pass"] else "not good enough"

    agent = Agent(model=model, verifiers=[check], verification=VerificationConfig(max_attempts=1))
    out = agent.run("go")
    assert out.status == RunStatus.unverified
    assert seen == [0]

    model.script = [_image_response("with chart", "http://x/chart.png")]
    model.calls = 0
    state["pass"] = True
    return agent, seen, out


def test_acontinue_run_verifier_sees_the_attempts_media():
    """Continuing an unverified run through acontinue_run: the gate must judge the
    continuation attempt WITH the image that attempt produced."""
    agent, seen, out = _unverified_run_then_image_continuation()

    continued = asyncio.run(agent.acontinue_run(run_response=out, input="add the chart"))

    assert continued.status == RunStatus.completed
    assert continued.verification.status == "verified"
    assert seen == [0, 1]
    assert _image_urls(continued) == ["http://x/chart.png"]


def test_continue_run_verifier_sees_the_attempts_media():
    """Sync twin: continue_run stores the attempt's media before the gate opens."""
    agent, seen, out = _unverified_run_then_image_continuation()

    continued = agent.continue_run(run_response=out, input="add the chart")

    assert continued.status == RunStatus.completed
    assert continued.verification.status == "verified"
    assert seen == [0, 1]
    assert _image_urls(continued) == ["http://x/chart.png"]


# ---------------------------------------------------------------------------
# Time-travel truncation and the verification record
# ---------------------------------------------------------------------------


def _unverified_first_run(max_attempts: int = 2):
    """An agent whose first run ends unverified after ``max_attempts`` failed attempts."""
    model = ScriptedModel([_text("try 1"), _text("try 2"), _text("try 3")])
    state = {"pass": False}

    def check(run_output):
        return True if state["pass"] else "not good enough"

    agent = Agent(model=model, verifiers=[check], verification=VerificationConfig(max_attempts=max_attempts))
    out = agent.run("go")
    assert out.status == RunStatus.unverified
    assert len(out.verification.attempts) == max_attempts
    return agent, model, state, out


def test_time_travel_continue_builds_a_fresh_record():
    """continue_from=<mid index> truncates the transcript, so the parent record (whose
    attempts index the pre-cut transcript) is dropped and the new gate builds a fresh
    one: only the continuation's attempts, budget_baseline restarts at zero, and every
    surviving message_index points inside the new transcript."""
    agent, model, state, out = _unverified_first_run(max_attempts=2)
    # Transcript: [system, user go, assistant, verification report, assistant].
    assert len(out.messages) == 5
    parent_record = out.verification

    model.script = [_text("fresh answer")]
    model.calls = 0
    state["pass"] = True
    continued = agent.continue_run(run_response=out, continue_from=2, input="start over")

    # Unverified source: continues in place, truncated to [system, user go] plus the new turn.
    assert continued.run_id == out.run_id
    assert continued.forked_from_run_id is None
    assert continued.status == RunStatus.completed
    record = continued.verification
    assert record is not parent_record
    assert record.status == "verified"
    assert record.stop_reason == "passed"
    assert record.budget_baseline == 0
    assert len(record.attempts) == 1
    assert record.attempts[0].verdicts[0].passed is True
    assert all(a.message_index <= len(continued.messages) for a in record.attempts)


def test_continue_from_end_keeps_the_record_and_budget_baseline():
    """continue_from='end' performs no truncation: the record survives, the attempt
    history is kept, and the budget window restarts at the continuation boundary."""
    agent, model, state, out = _unverified_first_run(max_attempts=2)
    parent_record = out.verification

    state["pass"] = True
    continued = agent.continue_run(run_response=out, continue_from="end", input="try harder")

    assert continued.run_id == out.run_id
    assert continued.status == RunStatus.completed
    record = continued.verification
    assert record is parent_record
    assert record.status == "verified"
    assert record.budget_baseline == 2
    assert len(record.attempts) == 3
    assert record.attempts[0].verdicts[0].passed is False
    assert record.attempts[2].verdicts[0].passed is True


def test_truncate_helper_clears_the_record_only_on_a_real_cut():
    """Unit contract of _truncate_run_to_checkpoint: a real truncation drops the
    verification record; both no-op guards (index past the end, negative index)
    leave it untouched."""

    def _run_with_record() -> RunOutput:
        return RunOutput(
            run_id="r-cut",
            messages=[
                Message(role="system", content="sys"),
                Message(role="user", content="go"),
                Message(role="assistant", content="answer"),
            ],
            verification=Verification(status="unverified"),
        )

    cut = _run_with_record()
    record = cut.verification
    _truncate_run_to_checkpoint(cut, 1)
    assert len(cut.messages) == 1
    assert cut.verification is None

    past_end = _run_with_record()
    record = past_end.verification
    _truncate_run_to_checkpoint(past_end, 3)
    assert len(past_end.messages) == 3
    assert past_end.verification is record

    negative = _run_with_record()
    record = negative.verification
    _truncate_run_to_checkpoint(negative, -1)
    assert len(negative.messages) == 3
    assert negative.verification is record
