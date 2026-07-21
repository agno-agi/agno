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
    def __init__(self, weights=None):
        # Zeros for the prompt, positive for the target -- the real reduction="mean"
        # shape, where only the tokens that carry loss have weight.
        self.loss_fn_inputs = {"weights": FakeTensor(weights if weights is not None else [0.0, 0.0, 0.5, 0.5])}


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

    def save_weights_for_sampler(self, *, name, ttl_seconds=None):
        self.saved.append({"name": name, "ttl_seconds": ttl_seconds})
        if self._save_raises is not None:
            return FakeFuture(raises=self._save_raises)
        return FakeFuture(SimpleNamespace(path=f"tinker://checkpoint/{name}"))


def _tensor_len(datum):
    return datum.loss_fn_inputs["weights"].data


class FakeSamplingClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def get_tokenizer(self):
        return "fake-tokenizer"


class FakeServiceClient:
    def __init__(self, training_client=None):
        self.training_client = training_client or FakeTrainingClient()
        self.lora_kwargs = None
        self.sampling_kwargs = []

    def create_lora_training_client(self, **kwargs):
        self.lora_kwargs = kwargs
        return self.training_client

    def create_sampling_client(self, **kwargs):
        self.sampling_kwargs.append(kwargs)
        return FakeSamplingClient(**kwargs)


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
    # Each conversation renders twice: capped at MAX_LENGTH for training, uncapped to
    # detect rows the cap would silently shorten.
    max_lengths = [call["max_length"] for call in fake_sdk["datum_calls"]]
    assert set(max_lengths) == {1024, None}
    assert max_lengths.count(1024) == max_lengths.count(None)

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

    # Both are served through the trainer's OWN service client, so a trainer holding an
    # injected client does not hand back models that reach for the real SDK.
    service = trainer._service_client
    assert service.sampling_kwargs == [
        {"model_path": "tinker://checkpoint/run-1"},
        {"base_model": "Qwen/Qwen3.6-35B-A3B"},
    ]
    assert tuned._sampling_client is not None and base._sampling_client is not None
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


def test_tinker_trainer_rejects_untrainable_dataset(tmp_path, fake_sdk, monkeypatch):
    # Rendering truncates from the end, so a conversation longer than max_length loses
    # the assistant turn it was meant to teach and arrives with all-zero weights. It
    # would contribute no gradient while the loss curve still looked healthy -- a paid
    # run that trained on less than the caller believes. Refuse before the first step.
    import sys

    dead = SimpleNamespace(
        conversation_to_datum=lambda conversation, renderer, *, max_length, train_on_what: FakeDatum(
            weights=[0.0, 0.0, 0.0, 0.0]
        )
    )
    monkeypatch.setitem(sys.modules, "tinker_cookbook.supervised.data", dead)

    training = FakeTrainingClient()
    trainer = TinkerTrainer(
        base_model="Qwen/Qwen3.6-35B-A3B",
        epochs=1,
        service_client=FakeServiceClient(training),
    )

    result = trainer.fit(_dataset(tmp_path))

    assert result.status == TrainStatus.FAILED
    assert result.checkpoint is None
    assert "no trainable target" in result.error
    assert training.forward_backward_calls == []  # refused before the first paid step


def test_tinker_trainer_rejects_bad_hyperparams():
    # epochs=0 or batch_size=0 would run zero optimizer steps and save the PRISTINE
    # BASE as a COMPLETED checkpoint; temperature 0 makes all k measurement attempts
    # identical. All three are caller bugs the constructor refuses, before any spend.
    with pytest.raises(ValueError, match="epochs"):
        TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", epochs=0)
    with pytest.raises(ValueError, match="batch_size"):
        TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", batch_size=0)
    with pytest.raises(ValueError, match="sampling_temperature"):
        TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", sampling_temperature=0.0)
    with pytest.raises(ValueError, match="sampling_temperature"):
        TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", sampling_temperature=-0.5)


def test_tinker_trainer_skips_truncated_rows_and_trains_survivors(tmp_path, monkeypatch):
    # A row whose rendering is shortened by MAX_LENGTH either lost its whole target
    # (all-zero weights) or -- worse -- kept a positive-weight PREFIX and would train
    # the model to stop mid-answer. Both are skipped with a warning, mirroring the
    # exporter's skip-not-abort; the fit runs on the survivors.
    import sys

    def shaped_datum(conversation, renderer, *, max_length, train_on_what):
        marker = conversation[-1]["content"]
        if marker == "partial":  # capped render keeps a positive-weight prefix
            return FakeDatum([0.0, 0.0, 0.5, 0.5] if max_length is not None else [0.0, 0.0, 0.2, 0.2, 0.2, 0.2])
        if marker == "gone":  # capped render lost the whole target
            return FakeDatum([0.0, 0.0, 0.0, 0.0] if max_length is not None else [0.0, 0.0, 0.0, 0.0, 0.5, 0.5])
        return FakeDatum()  # "good": identical capped and uncapped

    monkeypatch.setitem(
        sys.modules, "tinker_cookbook.supervised.data", SimpleNamespace(conversation_to_datum=shaped_datum)
    )

    import agno.trainers.tinker as trainer_module

    warnings = []
    monkeypatch.setattr(trainer_module, "log_warning", warnings.append)

    def _write(path, markers):
        rows = [
            json.dumps({"messages": [{"role": "user", "content": "the sea"}, {"role": "assistant", "content": m}]})
            for m in markers
        ]
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return path

    training = FakeTrainingClient()
    trainer = TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", epochs=1, service_client=FakeServiceClient(training))

    result = trainer.fit(_write(tmp_path / "mixed.jsonl", ["partial", "gone", "good"]))

    assert result.status == TrainStatus.COMPLETED
    assert len([w for w in warnings if "skipped" in str(w)]) == 2
    assert len(training.forward_backward_calls) == 1
    batch, _ = training.forward_backward_calls[0]
    assert len(batch) == 1  # only the untruncated survivor trained

    # When NO trainable row remains the fit refuses, before the first paid step.
    doomed = FakeTrainingClient()
    doomed_trainer = TinkerTrainer(
        base_model="Qwen/Qwen3.6-35B-A3B", epochs=1, service_client=FakeServiceClient(doomed)
    )
    doomed_result = doomed_trainer.fit(_write(tmp_path / "empty.jsonl", ["partial", "gone"]))

    assert doomed_result.status == TrainStatus.FAILED
    assert doomed_result.checkpoint is None
    assert "no trainable conversation remains" in doomed_result.error
    assert doomed.forward_backward_calls == []


def test_tinker_trainer_step_one_optim_raise_keeps_the_paid_forward_backward(tmp_path):
    # forward_backward is submitted -- and paid for -- before optim_step runs. A
    # synchronous optim_step raise on step 1 must therefore still produce a PARTIAL
    # recovery checkpoint, not a FAILED result that discards the spent compute.
    class OptimRaisesClient(FakeTrainingClient):
        def optim_step(self, adam_params):
            raise RuntimeError("optimizer rejected the step")

    training = OptimRaisesClient()
    trainer = TinkerTrainer(
        base_model="Qwen/Qwen3.6-35B-A3B",
        epochs=1,
        batch_size=1,
        service_client=FakeServiceClient(training),
    )

    result = trainer.fit(_dataset(tmp_path, rows=1))

    assert len(training.forward_backward_calls) == 1  # the paid submission happened
    assert result.status == TrainStatus.PARTIAL
    assert result.checkpoint is not None
    assert "recovery" in result.checkpoint.ref
    assert "optimizer rejected" in result.error


def test_tinker_trainer_as_model_rejects_foreign_checkpoint():
    # A checkpoint from another base would be served with the wrong renderer and
    # stamped with a false policy id (this trainer's base_model in the fingerprint).
    trainer = TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", service_client=FakeServiceClient())
    foreign = Checkpoint(
        ref="tinker://checkpoint/other",
        base_model="Qwen/Qwen2-7B",
        dataset_digest="abc",
        hyperparams={},
    )

    with pytest.raises(ValueError, match="Qwen/Qwen2-7B"):
        trainer.as_model(foreign)

    async def async_door():
        with pytest.raises(ValueError, match="Qwen/Qwen2-7B"):
            await trainer.aas_model(foreign)

    import asyncio

    asyncio.run(async_door())


async def test_tinker_trainer_serving_doors_do_not_block_the_event_loop():
    # Serving builds a sampling client -- a network auth handshake. Dispatched inline
    # on the loop thread, a hanging handshake would freeze every concurrent rollout
    # coroutine before any engine timeout could fire.
    import asyncio
    import threading
    import time

    loop_thread = threading.current_thread()
    construction_threads = []

    class BlockingServiceClient(FakeServiceClient):
        def create_sampling_client(self, **kwargs):
            construction_threads.append(threading.current_thread())
            time.sleep(0.2)  # a slow auth handshake
            return super().create_sampling_client(**kwargs)

    trainer = TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", service_client=BlockingServiceClient())
    checkpoint = Checkpoint(
        ref="tinker://checkpoint/run-1",
        base_model="Qwen/Qwen3.6-35B-A3B",
        dataset_digest="abc",
        hyperparams={},
    )

    ticks = 0

    async def tick_while_serving():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    ticker = asyncio.ensure_future(tick_while_serving())
    try:
        await trainer.aas_model(checkpoint)
        await trainer.abase_as_model()
    finally:
        ticker.cancel()

    assert ticks >= 5  # the event loop kept turning through both constructions
    assert construction_threads and all(thread is not loop_thread for thread in construction_threads)


def test_tinker_trainer_checkpoints_carry_a_ttl(tmp_path):
    # The SDK treats ttl_seconds=None as "never expires", so an unset TTL would leave a
    # permanent checkpoint behind for every round of every loop.
    training = FakeTrainingClient()
    trainer = TinkerTrainer(
        base_model="Qwen/Qwen3.6-35B-A3B",
        epochs=1,
        service_client=FakeServiceClient(training),
    )

    trainer.fit(_dataset(tmp_path))

    assert training.saved[0]["ttl_seconds"] == 7 * 24 * 60 * 60


def test_tinker_trainer_telemetry_failure_keeps_the_checkpoint(tmp_path, monkeypatch):
    # A loss reading that cannot be computed is a telemetry failure, not a training
    # failure: the completed steps were paid for and must still yield a checkpoint.
    import agno.trainers.tinker as trainer_module

    def boom(loss_fn_outputs, batch):
        raise ValueError("Tinker response is missing per-token logprobs")

    monkeypatch.setattr(trainer_module, "_mean_nll", boom)

    training = FakeTrainingClient()
    trainer = TinkerTrainer(
        base_model="Qwen/Qwen3.6-35B-A3B",
        epochs=2,
        batch_size=1,
        service_client=FakeServiceClient(training),
    )

    result = trainer.fit(_dataset(tmp_path, rows=2))

    assert result.status == TrainStatus.PARTIAL
    assert result.checkpoint is not None
    assert "loss telemetry" in result.error
    assert result.step_metrics[0]["mean_nll"] is None
    assert len(training.forward_backward_calls) == 1  # stopped after the first failure


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
