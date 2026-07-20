"""
Expert Iteration - Basic
========================

Close the loop. The environment generates a dataset from what the base model
already gets right, a trainer fine-tunes on it, and the tuned checkpoint is run
back through the same environment so the gain is measured, not assumed.

This runs offline by default against a stub trainer defined below, so the shape
of the loop is visible without a GPU or an API key. Set TINKER_API_KEY to run it
against a real Tinker fine-tune instead.
"""

import os
from itertools import cycle
from pathlib import Path
from typing import Dict, List

from agno.agent import Agent
from agno.environments import Environment, ImprovementLoop, Task
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.scorer import CodeScorer
from agno.trainers import Checkpoint, TrainOn, TrainResult, TrainStatus

BASE_MODEL = "Qwen/Qwen3.6-35B-A3B"


def is_three_lines(run, expected):
    """The verifier: a haiku is three non-empty lines. Fast, exact, no judge."""
    if run.content is None:
        return False
    lines = [line for line in run.content.strip().split("\n") if line.strip()]
    return len(lines) == 3


# --- the offline stand-ins ---------------------------------------------------
# A real trainer serves a real model. These two exist so this file runs with no
# GPU and no network; the live branch at the bottom swaps in TinkerTrainer, whose
# checkpoints are served as TinkerModel. Nothing here ships in agno.


class ScriptedModel(Model):
    """Answers from a script, cycling per task so some attempts pass and some do not."""

    def __init__(self, answers: List[str], tag: str):
        super().__init__(
            id=f"scripted-{tag}", name=f"scripted-{tag}", provider="Offline"
        )
        self._answers: Dict[str, cycle] = {}
        self._script = answers

    def _answer(self) -> str:
        key = "all"
        if key not in self._answers:
            self._answers[key] = cycle(self._script)
        return next(self._answers[key])

    def _respond(self) -> ModelResponse:
        return ModelResponse(role="assistant", content=self._answer())

    def invoke(self, *args, **kwargs):
        return self._respond()

    async def ainvoke(self, *args, **kwargs):
        return self._respond()

    def invoke_stream(self, *args, **kwargs):
        yield self._respond()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._respond()

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


class StubTrainer:
    """A trainer that reads the dataset and returns the next scripted model."""

    def __init__(self, base: Model, tuned: List[Model]):
        self._base = base
        self._tuned = tuned
        self._round = 0

    def fit(
        self, dataset, *, train_on: TrainOn = TrainOn.LAST_ASSISTANT
    ) -> TrainResult:
        rows = Path(dataset).read_text(encoding="utf-8").strip().split("\n")
        self._round += 1
        print(f"  stub fit: round {self._round} trained on {len(rows)} conversations")
        return TrainResult(
            checkpoint=Checkpoint(
                ref=f"stub://round-{self._round}",
                base_model=BASE_MODEL,
                dataset_digest="offline",
                hyperparams={
                    "rank": 16,
                    "learning_rate": 2e-4,
                    "epochs": 2,
                    "batch_size": 8,
                    "train_on": "last",
                },
            ),
            step_metrics=[{"step": 1, "mean_nll": 1.9}, {"step": 2, "mean_nll": 1.7}],
            status=TrainStatus.COMPLETED,
        )

    async def afit(
        self, dataset, *, train_on: TrainOn = TrainOn.LAST_ASSISTANT
    ) -> TrainResult:
        return self.fit(dataset, train_on=train_on)

    def as_model(self, checkpoint: Checkpoint) -> Model:
        index = int(checkpoint.ref.rsplit("-", 1)[1]) - 1
        return self._tuned[min(index, len(self._tuned) - 1)]

    async def aas_model(self, checkpoint: Checkpoint) -> Model:
        return self.as_model(checkpoint)

    def base_as_model(self) -> Model:
        return self._base

    async def abase_as_model(self) -> Model:
        return self.base_as_model()


HAIKU = "an old silent pond\na frog jumps into the pond\nsplash, silence again"
NOT_HAIKU = "a frog jumps in"

# The base is in the learning zone: it writes a real haiku only some of the time.
# A base that always passes, or never does, exports nothing and the loop converges
# with nothing to train on.
offline_base = ScriptedModel([HAIKU, NOT_HAIKU], tag="base")
offline_tuned = ScriptedModel([HAIKU], tag="tuned-1")

# The agent design is the environment's; the model is the trainer's. The loop
# overrides the model per rollout, so the declared model here is a placeholder.
agent = Agent(
    model=offline_base,
    instructions="Write a haiku about the topic. Exactly three lines.",
)

env = Environment(
    name="haiku",
    agent=agent,
    tasks=(
        Task(id="sea", input="the sea"),
        Task(id="autumn", input="autumn"),
        Task(id="train", input="a train"),
    ),
    scorer=CodeScorer(is_three_lines),
    # The offline stub answers instantly, but a real thinking model spends minutes on a
    # 2000-token sample and the 120s default times out every attempt.
    timeout_seconds=900,
)


def build_trainer():
    """A real trainer when a key is present, the stub otherwise."""
    if os.environ.get("TINKER_API_KEY"):
        from agno.trainers.tinker import TinkerTrainer

        print(f"TINKER_API_KEY found: fine-tuning {BASE_MODEL} for real.")
        return TinkerTrainer(base_model=BASE_MODEL, epochs=1)
    print("No TINKER_API_KEY: running the loop against the offline stub trainer.")
    return StubTrainer(offline_base, [offline_tuned])


if __name__ == "__main__":
    loop = ImprovementLoop(env, trainer=build_trainer(), k=4)

    report = loop.step()

    if report.converged:
        print(f"nothing to train on: {report.converged_reason}")
        print(f"export counters: {report.export_report}")
    else:
        print(f"baseline pass rate: {report.baseline_pass_rate}")
        print(f"tuned pass rate:    {report.tuned_pass_rate}")
        print(report.diff)
        print(f"trained on: {report.dataset_path}")
        print(f"loss curve: {report.train_result.step_metrics}")
        print("Same environment, same agent design, different weights.")
        print(
            "At 3 tasks the numbers are noisy; measure held-out tasks before claiming a gain."
        )
