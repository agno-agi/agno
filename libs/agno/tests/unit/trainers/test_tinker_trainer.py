"""TinkerTrainer against fake service, training and sampling clients.

The `tinker` SDK is not installed here and no TINKER_API_KEY is set. The fakes mirror
the real SDK's shapes -- futures with `.result()`, `loss_fn_outputs` carrying per-token
logprobs, a datum whose `loss_fn_inputs["weights"]` says which tokens carried loss --
so the training path is exercised without a paid call.
"""

import json
from types import SimpleNamespace

import pytest

from agno.models.tinker import TinkerModel
from agno.trainers.base import Checkpoint, TrainOn, TrainStatus
from agno.trainers.tinker import TinkerTrainer, _mean_nll

CONVERSATION = {
    "messages": [
        {"role": "user", "content": "the sea"},
        {"role": "assistant", "content": "an old silent pond"},
    ]
}


class FakeTensor:
    def __init__(self, data):
        self.data = data


class FakeDatum:
    def __init__(self, n_tokens=4):
        self.loss_fn_inputs = {"weights": FakeTensor([0.0, 0.0, 0.5, 0.5][:n_tokens])}


class FakeFuture:
    def __init__(self, value=None, raises=None):
        self._value = value
        self._raises = raises

    def result(self):
        if self._raises is not None:
            raise self._raises
        return self._value


class FakeTrainingClient:
    def __init__(self, *, fail_after=None, save_raises=None):
        self.forward_backward_calls = []
        self.optim_calls = []
        self.saved = []
        self._fail_after = fail_after
        self._save_raises = save_raises

    def get_tokenizer(self):
        return "fake-tokenizer"

    def forward_backward(self, batch, loss_fn):
        self.forward_backward_calls.append((batch, loss_fn))
        if self._fail_after is not None and len(self.forward_backward_calls) > self._fail_after:
            return FakeFuture(raises=RuntimeError("tinker exploded mid-run"))
        outputs = [{"logprobs": FakeTensor([-2.0] * len(_tensor_len(datum)))} for datum in batch]
        return FakeFuture(SimpleNamespace(loss_fn_outputs=outputs))

    def optim_step(self, adam_params):
        self.optim_calls.append(adam_params)
        return FakeFuture(SimpleNamespace(metrics={}))

    def save_weights_for_sampler(self, *, name):
        self.saved.append(name)
        if self._save_raises is not None:
            return FakeFuture(raises=self._save_raises)
        return FakeFuture(SimpleNamespace(path=f"tinker://checkpoint/{name}"))


def _tensor_len(datum):
    return datum.loss_fn_inputs["weights"].data


class FakeServiceClient:
    def __init__(self, training_client=None):
        self.training_client = training_client or FakeTrainingClient()
        self.lora_kwargs = None

    def create_lora_training_client(self, **kwargs):
        self.lora_kwargs = kwargs
        return self.training_client


@pytest.fixture(autouse=True)
def fake_sdk(monkeypatch):
    """Stand in for the SDK symbols `fit` imports lazily."""
    import agno.trainers.tinker as trainer_module

    captured = {"train_on_what": [], "datum_calls": []}

    class FakeTrainOnWhat:
        LAST_ASSISTANT_MESSAGE = "LAST_ASSISTANT_MESSAGE"
        ALL_ASSISTANT_MESSAGES = "ALL_ASSISTANT_MESSAGES"

    def fake_conversation_to_datum(conversation, renderer, *, max_length, train_on_what):
        captured["datum_calls"].append(
            {"conversation": conversation, "max_length": max_length, "train_on_what": train_on_what}
        )
        captured["train_on_what"].append(train_on_what)
        return FakeDatum()

    class FakeAdamParams:
        def __init__(self, *, learning_rate):
            self.learning_rate = learning_rate

    # The renderer needs a real tokenizer; the datum builder is faked below, so the
    # renderer only has to be an object the fake receives.
    monkeypatch.setattr(trainer_module.TinkerTrainer, "_build_renderer", lambda self, client: "fake-renderer")

    import sys

    tinker_stub = SimpleNamespace(types=SimpleNamespace(AdamParams=FakeAdamParams))
    cookbook_renderers = SimpleNamespace(TrainOnWhat=FakeTrainOnWhat)
    cookbook_data = SimpleNamespace(conversation_to_datum=fake_conversation_to_datum)
    monkeypatch.setitem(sys.modules, "tinker", tinker_stub)
    monkeypatch.setitem(sys.modules, "tinker_cookbook", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "tinker_cookbook.renderers", cookbook_renderers)
    monkeypatch.setitem(sys.modules, "tinker_cookbook.supervised", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "tinker_cookbook.supervised.data", cookbook_data)

    yield captured


def _dataset(tmp_path, rows=2):
    path = tmp_path / "train.jsonl"
    path.write_text("\n".join(json.dumps(CONVERSATION) for _ in range(rows)) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The vendored oracle
# ---------------------------------------------------------------------------


def test_trainer_validate_oracle_byte_identical():
    # Vendored twice on purpose -- agno.trainers must not import agno.environments --
    # so the two copies are pinned equal to stop them drifting.
    from pathlib import Path

    import agno

    root = Path(agno.__file__).parent
    exporter_copy = (root / "environments" / "exporters" / "_validate.py").read_bytes()
    trainer_copy = (root / "trainers" / "_validate.py").read_bytes()

    assert trainer_copy == exporter_copy


def test_tinker_trainer_fit_validates_dataset(tmp_path):
    # The oracle is the gate in front of a paid call: a malformed dataset is refused
    # before the training client is ever created.
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"messages": [{"role": "user", "content": "only a user turn"}]}\n', encoding="utf-8")

    service = FakeServiceClient()
    trainer = TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", service_client=service)

    with pytest.raises(ValueError):
        trainer.fit(bad)

    assert service.lora_kwargs is None  # no training client, so nothing was paid for


# ---------------------------------------------------------------------------
# The training path
# ---------------------------------------------------------------------------


def test_tinker_trainer_train_on_passthrough(tmp_path, fake_sdk):
    # The SDK's default is ALL_ASSISTANT_MESSAGES -- the inverse of ours -- so
    # train_on_what must be passed explicitly on EVERY call, including the default one.
    service = FakeServiceClient()
    trainer = TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", epochs=1, service_client=service)

    trainer.fit(_dataset(tmp_path))
    assert set(fake_sdk["train_on_what"]) == {"LAST_ASSISTANT_MESSAGE"}
    assert all(call["max_length"] == 1024 for call in fake_sdk["datum_calls"])

    fake_sdk["train_on_what"].clear()
    trainer.fit(_dataset(tmp_path), train_on=TrainOn.ALL_ASSISTANT)
    assert set(fake_sdk["train_on_what"]) == {"ALL_ASSISTANT_MESSAGES"}

    # The training seed is pinned, and the rank reaches the SDK.
    assert service.lora_kwargs["seed"] == 0
    assert service.lora_kwargs["rank"] == 16
    assert service.lora_kwargs["base_model"] == "Qwen/Qwen3.6-35B-A3B"


def test_tinker_trainer_result_carries_metrics(tmp_path):
    # The loss curve is a thin read on the result, not something the caller
    # re-implements by wrapping the loop.
    training = FakeTrainingClient()
    trainer = TinkerTrainer(
        base_model="Qwen/Qwen3.6-35B-A3B",
        epochs=2,
        batch_size=1,
        service_client=FakeServiceClient(training),
    )

    result = trainer.fit(_dataset(tmp_path, rows=2))

    assert result.status == TrainStatus.COMPLETED
    assert isinstance(result.checkpoint, Checkpoint)
    assert result.checkpoint.base_model == "Qwen/Qwen3.6-35B-A3B"
    assert result.checkpoint.dataset_digest
    # Exactly the five keys agno's own trainers record.
    assert set(result.checkpoint.hyperparams) == {"rank", "learning_rate", "epochs", "batch_size", "train_on"}

    # 2 rows / batch_size 1 * 2 epochs = 4 optimizer steps.
    assert len(result.step_metrics) == 4
    assert [step["step"] for step in result.step_metrics] == [1, 2, 3, 4]
    for step in result.step_metrics:
        assert step["mean_nll"] == pytest.approx(2.0)  # -(-2.0), weighted over the target tokens
    assert len(training.optim_calls) == 4
    assert training.optim_calls[0].learning_rate == 2e-4
    assert training.forward_backward_calls[0][1] == "cross_entropy"


def test_tinker_trainer_partial_failure_preserves_checkpoint(tmp_path):
    # Compute was already spent. A recovery checkpoint turns a total loss into a
    # PARTIAL the caller can still measure -- never losing paid compute.
    training = FakeTrainingClient(fail_after=1)
    trainer = TinkerTrainer(
        base_model="Qwen/Qwen3.6-35B-A3B",
        epochs=2,
        batch_size=1,
        service_client=FakeServiceClient(training),
    )

    result = trainer.fit(_dataset(tmp_path, rows=2))

    assert result.status == TrainStatus.PARTIAL
    assert result.checkpoint is not None
    assert "recovery" in result.checkpoint.ref
    assert result.error and "tinker exploded mid-run" in result.error
    assert result.step_metrics  # the steps that did complete are still reported

    # When the recovery save ALSO fails there is nothing to hand back, and the result
    # says so rather than pretending.
    doomed = FakeTrainingClient(fail_after=1, save_raises=RuntimeError("save failed too"))
    doomed_trainer = TinkerTrainer(
        base_model="Qwen/Qwen3.6-35B-A3B",
        epochs=1,
        batch_size=1,
        service_client=FakeServiceClient(doomed),
    )
    doomed_result = doomed_trainer.fit(_dataset(tmp_path, rows=2))
    assert doomed_result.status == TrainStatus.FAILED
    assert doomed_result.checkpoint is None
    assert "recovery checkpoint failed" in doomed_result.error


def test_tinker_trainer_as_model_returns_tinker_model(tmp_path):
    # Both faces of the protocol serve TinkerModels with IDENTICAL sampling params, so
    # the only difference between baseline and tuned is the weights.
    trainer = TinkerTrainer(
        base_model="Qwen/Qwen3.6-35B-A3B",
        sampling_temperature=0.9,
        sampling_max_tokens=1234,
        service_client=FakeServiceClient(),
    )
    checkpoint = Checkpoint(
        ref="tinker://checkpoint/run-1",
        base_model="Qwen/Qwen3.6-35B-A3B",
        dataset_digest="abc",
        hyperparams={},
    )

    tuned = trainer.as_model(checkpoint)
    base = trainer.base_as_model()

    assert isinstance(tuned, TinkerModel) and isinstance(base, TinkerModel)
    assert tuned.model_path == "tinker://checkpoint/run-1"
    assert base.model_path is None
    assert tuned.base_model == base.base_model == "Qwen/Qwen3.6-35B-A3B"
    for model in (tuned, base):
        assert model.temperature == 0.9
        assert model.max_tokens == 1234
        assert model.seed is None  # never a fixed seed across attempts

    # Different policies, and neither carries a model-level prompt (which would move
    # the ENV fingerprint and make the two runs incomparable).
    assert tuned.id != base.id
    assert tuned.system_prompt is None and base.system_prompt is None


async def test_tinker_trainer_async_twins(tmp_path):
    trainer = TinkerTrainer(
        base_model="Qwen/Qwen3.6-35B-A3B",
        epochs=1,
        batch_size=1,
        service_client=FakeServiceClient(),
    )

    result = await trainer.afit(_dataset(tmp_path))
    assert result.status == TrainStatus.COMPLETED

    checkpoint = result.checkpoint
    assert isinstance(await trainer.aas_model(checkpoint), TinkerModel)
    assert isinstance(await trainer.abase_as_model(), TinkerModel)


def test_mean_nll_uses_logprobs_and_weights():
    # Computed from the tokens that actually carried loss. A summed loss metric would
    # average the prompt in too.
    datum = FakeDatum()
    outputs = [{"logprobs": FakeTensor([-1.0, -1.0, -3.0, -5.0])}]

    # weights are [0, 0, 0.5, 0.5]: only the last two tokens count -> (3 + 5) / 2
    assert _mean_nll(outputs, [datum]) == pytest.approx(4.0)

    with pytest.raises(ValueError):
        _mean_nll([{"no_logprobs": 1}], [datum])
    with pytest.raises(ValueError):
        _mean_nll([], [datum])
