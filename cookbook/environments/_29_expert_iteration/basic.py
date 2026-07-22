"""
Expert Iteration - Basic
========================

Close the loop. The environment generates a dataset from what the base model
already gets right, a trainer fine-tunes on it, and the tuned checkpoint is run
back through the same environment so the gain is measured, not assumed.

The trainer is swappable -- that is the demo. The same ImprovementLoop runs
against three backends, selected by AGNO_TRAINER:

    stub       (default) the offline stand-in below; no GPU, no key, no spend
    tinker     TinkerTrainer -- agno drives the training loop step by step
    fireworks  FireworksTrainer -- a managed fine-tuning job plus an
               on-demand deployment for serving

The live paths spend real training compute, so they require an explicit opt-in
on top of the key: set AGNO_RUN_FINE_TUNE=1 as well as the provider's API key.
A key alone never triggers spend -- a key is capability, not consent.
(AGNO_RUN_TINKER_FINE_TUNE=1, the original Tinker-only spelling, still works
and implies AGNO_TRAINER=tinker.)
"""

import hashlib
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

BASE_MODEL = "Qwen/Qwen3.6-35B-A3B"  # the stub's checkpoint identity, and Tinker's base
FIREWORKS_BASE_MODEL = "accounts/fireworks/models/qwen3-4b-instruct-2507"


def is_three_lines(run, expected):
    """The verifier: a haiku is three non-empty lines. Fast, exact, no judge.

    It reads run.content directly: the engine never scores a truncated run, so a
    None guard here would only hide truncation inside the pass rate.
    """
    lines = [line for line in run.content.strip().split("\n") if line.strip()]
    return len(lines) == 3


# --- the offline stand-ins ---------------------------------------------------
# A real trainer serves a real model. These two exist so this file runs with no
# GPU and no network; the live branches at the bottom swap in TinkerTrainer
# (served as TinkerModel) or FireworksTrainer (served from an on-demand Fireworks
# deployment). Nothing here ships in agno.


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
        data = Path(dataset).read_bytes()
        rows = data.decode("utf-8").strip().split("\n")
        self._round += 1
        print(f"  stub fit: round {self._round} trained on {len(rows)} conversations")
        return TrainResult(
            checkpoint=Checkpoint(
                ref=f"stub://round-{self._round}",
                base_model=BASE_MODEL,
                # The real digest of the real bytes: the loop refuses to serve a
                # checkpoint whose provenance does not match the file it trained on.
                dataset_digest=hashlib.sha256(data).hexdigest(),
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
    """A paid trainer only on explicit opt-in. A key is capability, not consent:
    an API key alone selects the stub, so an environment where keys are always
    loaded (direnv) cannot spend a fine-tune by accident. AGNO_TRAINER picks the
    backend; AGNO_RUN_FINE_TUNE=1 is the consent to spend."""
    explicit = os.environ.get("AGNO_TRAINER")
    choice = (explicit or "stub").strip().lower() or "stub"
    consented = os.environ.get("AGNO_RUN_FINE_TUNE") == "1"
    if os.environ.get("AGNO_RUN_TINKER_FINE_TUNE") == "1":
        # The legacy flag implies tinker-with-consent, but an explicit different
        # AGNO_TRAINER must not be silently overridden into a paid Tinker run
        # (a stale export of the legacy flag would otherwise beat AGNO_TRAINER=stub).
        if explicit and choice != "tinker":
            raise RuntimeError(
                "AGNO_RUN_TINKER_FINE_TUNE=1 (legacy, implies tinker) conflicts with "
                f"AGNO_TRAINER={choice!r}; unset one, or use AGNO_TRAINER=tinker "
                "AGNO_RUN_FINE_TUNE=1."
            )
        choice, consented = "tinker", True

    if choice == "tinker":
        if not consented:
            raise RuntimeError(
                "AGNO_TRAINER=tinker selected but AGNO_RUN_FINE_TUNE=1 is not set; "
                "the live fine-tune needs the explicit consent flag."
            )
        if not os.environ.get("TINKER_API_KEY"):
            raise RuntimeError("The Tinker fine-tune needs TINKER_API_KEY.")
        from agno.trainers.tinker import TinkerTrainer

        print(f"Trainer: Tinker. Fine-tuning {BASE_MODEL} for real.")
        return TinkerTrainer(base_model=BASE_MODEL, epochs=1)

    if choice == "fireworks":
        if not consented:
            raise RuntimeError(
                "AGNO_TRAINER=fireworks selected but AGNO_RUN_FINE_TUNE=1 is not set; "
                "the live fine-tune needs the explicit consent flag."
            )
        if not os.environ.get("FIREWORKS_API_KEY"):
            raise RuntimeError("The Fireworks fine-tune needs FIREWORKS_API_KEY.")
        if not os.environ.get("FIREWORKS_ACCOUNT_ID"):
            print(
                "FIREWORKS_ACCOUNT_ID is not set; FireworksTrainer will refuse before "
                "any spend unless account_id is passed another way."
            )
        from agno.trainers.fireworks import FireworksTrainer

        print(f"Trainer: Fireworks. Fine-tuning {FIREWORKS_BASE_MODEL} for real.")
        print(
            "Serving both sides of the before/after uses one on-demand deployment; "
            "GPU time bills while it serves, and it is deleted at the end of the run."
        )
        # reasoning_effort="none" keeps this instruct model's answer in `content`;
        # otherwise Fireworks' reasoning parser routes the whole completion into the
        # reasoning channel and every attempt reads as empty.
        return FireworksTrainer(
            base_model=FIREWORKS_BASE_MODEL, epochs=1, sampling_reasoning_effort="none"
        )

    if choice != "stub":
        raise RuntimeError(
            f"Unknown AGNO_TRAINER {choice!r}: expected stub, tinker or fireworks."
        )

    keys_present = [
        name for name in ("TINKER_API_KEY", "FIREWORKS_API_KEY") if os.environ.get(name)
    ]
    if keys_present:
        print(
            f"{' and '.join(keys_present)} found but no live trainer was opted into: "
            "using the offline stub. Set AGNO_TRAINER=tinker or fireworks plus "
            "AGNO_RUN_FINE_TUNE=1 to spend a real fine-tune."
        )
    else:
        print("No trainer API key: running the loop against the offline stub trainer.")
    return StubTrainer(offline_base, [offline_tuned])


if __name__ == "__main__":
    trainer = build_trainer()
    loop = ImprovementLoop(env, trainer=trainer, k=4)

    try:
        report = loop.step()
    finally:
        # FireworksTrainer serves through an on-demand deployment that bills GPU
        # time; releasing it is part of the run. The other trainers have no
        # serving infrastructure to release.
        teardown = getattr(trainer, "teardown", None)
        if teardown is not None:
            teardown()

    if report.converged:
        print(f"nothing to train on: {report.converged_reason}")
        print(f"export counters: {report.export_report}")
    elif report.unmeasured_reason is not None:
        # A live-path shape: the baseline produced no scored attempts, or the
        # tuned side could not be measured. With a checkpoint present, the
        # fine-tune was paid for and is preserved on the report.
        print(f"round measured nothing: {report.unmeasured_reason}")
        print(f"baseline pass rate: {report.baseline_pass_rate}")
        if report.checkpoint is not None:
            print(
                f"checkpoint paid for but unmeasured, preserved: {report.checkpoint.ref}"
            )
            print(
                "re-measure it with run_rollouts(env, model=trainer.as_model(report.checkpoint))"
            )
    else:
        print(f"baseline pass rate: {report.baseline_pass_rate}")
        print(f"tuned pass rate:    {report.tuned_pass_rate}")
        print(report.diff)
        print(f"trained on: {report.dataset_path}")
        print(f"training metrics: {report.train_result.step_metrics}")
        print("Same environment, same agent design, different weights.")
        print(
            "At 3 tasks the numbers are noisy; measure held-out tasks before claiming a gain."
        )
