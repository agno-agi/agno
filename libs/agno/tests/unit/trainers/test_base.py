"""The Trainer protocol: all six methods, and the result shapes the loop reads."""

from pathlib import Path

import pytest

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.scorer import CodeScorer
from agno.trainers import Checkpoint, Trainer, TrainOn, TrainResult, TrainStatus

from ..environments.stubs import ScriptedModel, StubTrainer


class SixMethodTrainer:
    def fit(self, dataset, *, train_on=TrainOn.LAST_ASSISTANT): ...
    async def afit(self, dataset, *, train_on=TrainOn.LAST_ASSISTANT): ...
    def as_model(self, checkpoint): ...
    async def aas_model(self, checkpoint): ...
    def base_as_model(self): ...
    async def abase_as_model(self): ...


class MissingAfitTrainer:
    def fit(self, dataset, *, train_on=TrainOn.LAST_ASSISTANT): ...
    def as_model(self, checkpoint): ...
    async def aas_model(self, checkpoint): ...
    def base_as_model(self): ...
    async def abase_as_model(self): ...


def test_trainer_protocol_runtime_checkable():
    # All six methods are protocol members, so a half-implemented adapter fails the
    # check here rather than at the first call site that needs the missing half.
    assert isinstance(SixMethodTrainer(), Trainer)
    assert not isinstance(MissingAfitTrainer(), Trainer)
    assert isinstance(StubTrainer(ScriptedModel("a"), [ScriptedModel("b", tag="t1")]), Trainer)


def _haiku_env(model):
    return Environment(
        name="stub-env",
        agent=Agent(model=model),
        tasks=(Task(input="the sea", expected="right"), Task(input="autumn", expected="right")),
        scorer=CodeScorer(lambda run, expected: run.content == expected),
    )


def test_stub_trainer_and_model_offline(tmp_path):
    # The doubles have to behave like the real thing on the two things the loop reads:
    # a checkpoint with a real dataset digest, and models that actually run rollouts.
    base = ScriptedModel({"the sea": "wrong", "autumn": "right"}, tag="base")
    tuned = ScriptedModel("right", tag="tuned-1")
    trainer = StubTrainer(base, [tuned])

    dataset = tmp_path / "round_1.jsonl"
    dataset.write_text('{"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]}\n')

    result = trainer.fit(dataset)
    assert isinstance(result, TrainResult)
    assert result.status == TrainStatus.COMPLETED
    assert isinstance(result.checkpoint, Checkpoint)
    assert result.checkpoint.dataset_digest  # a real sha256 of real bytes
    assert result.step_metrics and all("mean_nll" in step for step in result.step_metrics)

    assert trainer.base_as_model() is base
    assert trainer.as_model(result.checkpoint) is tuned

    # Both models run under the rollout engine with no network and produce scored
    # attempts -- the property every loop test depends on.
    base_run = run_rollouts(_haiku_env(trainer.base_as_model()), k=2)
    tuned_run = run_rollouts(_haiku_env(trainer.as_model(result.checkpoint)), k=2)
    assert base_run.n_scored == 4
    assert tuned_run.n_scored == 4
    assert base_run.pass_rate == 0.5
    assert tuned_run.pass_rate == 1.0


def test_train_result_partial_status(tmp_path):
    # A mid-run failure that already spent compute must not report FAILED with nothing:
    # the recovery checkpoint is the paid artifact, and the real Tinker path has to
    # match this shape.
    trainer = StubTrainer(
        ScriptedModel("wrong", tag="base"),
        [ScriptedModel("right", tag="tuned-1")],
        fail_on_round=1,
        recoverable=True,
    )
    dataset = tmp_path / "round_1.jsonl"
    dataset.write_text('{"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]}\n')

    result = trainer.fit(dataset)

    assert result.status == TrainStatus.PARTIAL
    assert result.checkpoint is not None
    assert "recovery" in result.checkpoint.ref
    assert result.error

    total_failure = StubTrainer(
        ScriptedModel("wrong", tag="base"),
        [ScriptedModel("right", tag="tuned-1")],
        fail_on_round=1,
        recoverable=False,
    )
    failed = total_failure.fit(dataset)
    assert failed.status == TrainStatus.FAILED
    assert failed.checkpoint is None


def test_checkpoint_is_unhashable_but_frozen():
    # eq=False keeps identity semantics; a frozen dataclass with eq=True would generate
    # a __hash__ that raises on the hyperparams mapping.
    checkpoint = Checkpoint(ref="stub://1", base_model="b", dataset_digest="d", hyperparams={"rank": 16})
    with pytest.raises(AttributeError):
        checkpoint.ref = "other"  # type: ignore[misc]
    assert {checkpoint}  # identity-hashable, does not raise


def test_stub_trainer_fit_rejects_missing_dataset(tmp_path):
    trainer = StubTrainer(ScriptedModel("a"), [ScriptedModel("b", tag="t1")])
    with pytest.raises(AssertionError):
        trainer.fit(Path(tmp_path / "nope.jsonl"))
