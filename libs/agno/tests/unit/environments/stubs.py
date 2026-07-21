"""Offline doubles for the training loop: a scripted model and a stub trainer.

These exist so the whole improvement loop -- rollout, export, fit, re-measure, diff --
is testable with no GPU, no network, and no trainer SDK installed. Everything they
return is deterministic: the byte-stability test compares two identical runs, so no
uuid, no wall clock, no `id(self)` anywhere in what reaches a report.
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.trainers.base import Checkpoint, TrainOn, TrainResult, TrainStatus

Answer = Union[str, List[str]]


class ScriptedModel(Model):
    """A Model whose answer is decided by the test, not by a provider.

    Mirrors the shape the rollout engine actually drives -- all six abstract methods,
    with the stream variants as single-chunk generators. Two deliberate differences
    from the fake in `test_runner.py`: the content is a constructor parameter (so a
    "base" instance can answer some tasks wrong and a "tuned" one answer them right),
    and every recording attribute is underscore-prefixed. That second point is
    load-bearing: the policy fingerprint enumerates `vars(model)`, so a public
    recording list would make two otherwise identical policies hash differently.

    An answer may be a list, which cycles per attempt of that task. This is what makes
    a learning zone possible at all: the zone is tasks that pass *sometimes*, so a
    model that answers every attempt of a task identically produces an empty zone and
    the loop converges having trained nothing. The cycle is keyed per input and
    advanced once per call, so at k=2 a two-element cycle always yields exactly one
    pass -- the pass rate is deterministic even though attempts run concurrently and
    the order in which they claim cycle positions is not.
    """

    def __init__(
        self,
        content: Union[Answer, Dict[str, Answer]],
        *,
        tag: str = "scripted",
        default: Answer = "no answer",
    ):
        # The id separates policies: base and tuned must not fingerprint alike, exactly
        # as a real adapter's tuned checkpoint changes its id.
        super().__init__(id=f"scripted-{tag}", name=f"scripted-{tag}", provider="test")
        self._content = content
        self._default = default
        self._seen_inputs: List[str] = []
        self._counters: Dict[str, int] = {}

    def __deepcopy__(self, memo):
        # The runner deep-copies the agent per attempt; keep sharing the record and the
        # cycle positions, or every attempt would restart the script at position 0.
        clone = type(self)(self._content, tag=self.id.removeprefix("scripted-"), default=self._default)
        clone._seen_inputs = self._seen_inputs
        clone._counters = self._counters
        clone.cache_response = self.cache_response
        return clone

    def _answer_for(self, args, kwargs) -> str:
        """Look up this task's scripted answer from the last user message."""
        messages: List[Message] = []
        for value in list(args) + list(kwargs.values()):
            if isinstance(value, list) and value and all(isinstance(m, Message) for m in value):
                messages = value
                break
        user_text = ""
        for message in reversed(messages):
            if message.role == "user" and isinstance(message.content, str):
                user_text = message.content
                break
        self._seen_inputs.append(user_text)

        answer: Answer
        if isinstance(self._content, dict):
            answer = self._content.get(user_text, self._default)
        else:
            answer = self._content
        if isinstance(answer, str):
            return answer
        position = self._counters.get(user_text, 0)
        self._counters[user_text] = position + 1
        return answer[position % len(answer)]

    def _respond(self, args, kwargs) -> ModelResponse:
        return ModelResponse(role="assistant", content=self._answer_for(args, kwargs))

    def invoke(self, *args, **kwargs):
        return self._respond(args, kwargs)

    async def ainvoke(self, *args, **kwargs):
        return self._respond(args, kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self._respond(args, kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._respond(args, kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


class StubTrainer:
    """A Trainer that never trains: it reads the dataset and hands back the next
    scripted model.

    It still does the two things the loop depends on for real -- it asserts the dataset
    file exists and digests its actual bytes -- so provenance in a report is the same
    provenance a real trainer would produce.

    `fail_on_round` models the two failure shapes the protocol distinguishes: with
    `recoverable=True` the run spent compute and returns PARTIAL carrying a recovery
    checkpoint; with `recoverable=False` it returns FAILED with nothing.
    """

    def __init__(
        self,
        base: ScriptedModel,
        tuned: List[ScriptedModel],
        *,
        base_model: str = "stub-base",
        fail_on_round: Optional[int] = None,
        recoverable: bool = True,
    ):
        self.base = base
        self.tuned = list(tuned)
        self.base_model = base_model
        self.fail_on_round = fail_on_round
        self.recoverable = recoverable
        # Test-visible call log. Not a Model, so none of this reaches a fingerprint.
        self.fit_calls: List[Path] = []
        self.fit_train_on: List[TrainOn] = []
        self._round = 0

    def _checkpoint(self, round_number: int, digest: str, train_on: TrainOn, *, recovery: bool = False) -> Checkpoint:
        ref = f"stub://round-{round_number}-recovery" if recovery else f"stub://round-{round_number}"
        return Checkpoint(
            ref=ref,
            # Constant across rounds: every fit retrains the pristine base.
            base_model=self.base_model,
            dataset_digest=digest,
            hyperparams={
                "rank": 16,
                "learning_rate": 2e-4,
                "epochs": 2,
                "batch_size": 8,
                "train_on": train_on.value,
            },
        )

    def fit(self, dataset: Union[str, Path], *, train_on: TrainOn = TrainOn.LAST_ASSISTANT) -> TrainResult:
        path = Path(dataset)
        assert path.exists(), f"StubTrainer.fit was handed a dataset that does not exist: {path}"
        self.fit_calls.append(path)
        self.fit_train_on.append(train_on)
        self._round += 1
        digest = hashlib.sha256(path.read_bytes()).hexdigest()

        # Deterministic loss curve: a real one falls, and nothing here may vary between
        # two identical runs.
        step_metrics: List[Dict[str, Any]] = [
            {"step": step, "mean_nll": round(2.0 - 0.1 * step, 4)} for step in range(1, 4)
        ]

        if self.fail_on_round is not None and self._round == self.fail_on_round:
            if not self.recoverable:
                return TrainResult(
                    checkpoint=None,
                    step_metrics=[],
                    status=TrainStatus.FAILED,
                    error="stub trainer failed before any compute was spent",
                )
            return TrainResult(
                checkpoint=self._checkpoint(self._round, digest, train_on, recovery=True),
                step_metrics=step_metrics[:1],
                status=TrainStatus.PARTIAL,
                error="stub trainer failed mid-run; recovery checkpoint preserved",
            )

        return TrainResult(
            checkpoint=self._checkpoint(self._round, digest, train_on),
            step_metrics=step_metrics,
            status=TrainStatus.COMPLETED,
        )

    async def afit(self, dataset: Union[str, Path], *, train_on: TrainOn = TrainOn.LAST_ASSISTANT) -> TrainResult:
        return await asyncio.to_thread(self.fit, dataset, train_on=train_on)

    def _round_of(self, checkpoint: Checkpoint) -> int:
        digits = "".join(ch for ch in checkpoint.ref.removeprefix("stub://round-") if ch.isdigit())
        return int(digits)

    def as_model(self, checkpoint: Checkpoint) -> Model:
        index = self._round_of(checkpoint) - 1
        if index >= len(self.tuned):
            # Past the script, the policy stops improving rather than crashing: a
            # loop run for more rounds than the test scripted still terminates.
            return self.tuned[-1]
        return self.tuned[index]

    async def aas_model(self, checkpoint: Checkpoint) -> Model:
        return self.as_model(checkpoint)

    def base_as_model(self) -> Model:
        return self.base

    async def abase_as_model(self) -> Model:
        return self.base_as_model()
