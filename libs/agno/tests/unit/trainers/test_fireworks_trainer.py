"""FireworksTrainer against a fake Fireworks SDK client.

The `fireworks` SDK is not installed here and no FIREWORKS_API_KEY is needed. The
fakes mirror the real SDK's resource layout -- `client.datasets`,
`client.supervised_fine_tuning_jobs`, `client.deployments`, `client.lora` -- and its
response shapes (`state` enums, `job_progress`, resource `name`s), so the managed-job
path is exercised without a paid call.
"""

import json
import sys
from types import SimpleNamespace

import pytest

from agno.agent import Agent
from agno.environments import Environment, Task
from agno.environments.environment import _env_fingerprint_of, _policy_fingerprint_of
from agno.models.fireworks import Fireworks
from agno.scorer import CodeScorer
from agno.trainers.base import Checkpoint, TrainOn, TrainStatus
from agno.trainers.fireworks import FireworksTrainer, validate_fireworks_sft_jsonl

BASE_MODEL = "accounts/fireworks/models/qwen3-8b"

CONVERSATION = {
    "messages": [
        {"role": "user", "content": "the sea"},
        {"role": "assistant", "content": "an old silent pond"},
    ]
}


def _dataset(tmp_path, rows=3, name="train.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(CONVERSATION) for _ in range(rows)) + "\n", encoding="utf-8")
    return path


class FakeAPIError(Exception):
    def __init__(self, status_code, message="api error"):
        super().__init__(message)
        self.status_code = status_code


class FakeDatasetsResource:
    def __init__(self, *, create_raises=None, states=None):
        self.create_calls = []
        self.upload_calls = []
        self.get_calls = []
        self._create_raises = create_raises
        self._states = list(states or ["READY"])

    def create(self, *, dataset_id, dataset):
        self.create_calls.append({"dataset_id": dataset_id, "dataset": dataset})
        if self._create_raises is not None:
            raise self._create_raises

    def upload(self, *, dataset_id, file):
        self.upload_calls.append({"dataset_id": dataset_id, "file": file})

    def get(self, dataset_id):
        self.get_calls.append(dataset_id)
        state = self._states.pop(0) if len(self._states) > 1 else self._states[0]
        return SimpleNamespace(state=state, status=None)


class FakeJobsResource:
    """Scripted job lifecycle: `create` returns the first snapshot, each `get` the next."""

    def __init__(self, snapshots=None):
        self.create_calls = []
        self.get_calls = []
        self.snapshots = snapshots

    def _job(self, snapshot, output_model):
        progress = snapshot.get("progress")
        return SimpleNamespace(
            name="accounts/test-account/supervisedFineTuningJobs/job-1",
            state=snapshot["state"],
            output_model=output_model,
            job_progress=SimpleNamespace(**progress) if progress else None,
            status=SimpleNamespace(message=snapshot.get("message")) if snapshot.get("message") else None,
        )

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        snapshots = self.snapshots if self.snapshots is not None else [{"state": "JOB_STATE_COMPLETED"}]
        self._pending = list(snapshots)
        return self._advance()

    def _advance(self):
        # Consume the script, then repeat the last snapshot forever.
        snapshot = self._pending.pop(0) if len(self._pending) > 1 else self._pending[0]
        return self._job(snapshot, self.create_calls[-1].get("output_model"))

    def get(self, job_id):
        self.get_calls.append(job_id)
        return self._advance()


class FakeDeploymentsResource:
    def __init__(self, *, states=None, enable_addons=True):
        self.create_calls = []
        self.get_calls = []
        self.delete_calls = []
        self._states = list(states or ["READY"])
        self._enable_addons = enable_addons

    def create(self, **kwargs):
        self.create_calls.append(kwargs)

    def get(self, deployment_id):
        self.get_calls.append(deployment_id)
        state = self._states.pop(0) if len(self._states) > 1 else self._states[0]
        return SimpleNamespace(state=state, status=None, enable_addons=self._enable_addons)

    def delete(self, deployment_id):
        self.delete_calls.append(deployment_id)


class FakeLoraResource:
    def __init__(self, *, load_raises=None):
        self.load_calls = []
        self.get_calls = []
        self.unload_calls = []
        self._load_raises = load_raises

    def load(self, *, model, deployment):
        self.load_calls.append({"model": model, "deployment": deployment})
        if self._load_raises is not None:
            raise self._load_raises
        return SimpleNamespace(
            name=f"accounts/test-account/deployedModels/dm-{len(self.load_calls)}", state="DEPLOYING"
        )

    def get(self, deployed_model_id):
        self.get_calls.append(deployed_model_id)
        return SimpleNamespace(state="DEPLOYED", status=None)

    def unload(self, deployed_model_id):
        self.unload_calls.append(deployed_model_id)


class FakeFireworksClient:
    def __init__(self, **overrides):
        self.account_id = overrides.pop("account_id", "test-account")
        self.datasets = overrides.pop("datasets", FakeDatasetsResource())
        self.supervised_fine_tuning_jobs = overrides.pop("jobs", FakeJobsResource())
        self.deployments = overrides.pop("deployments", FakeDeploymentsResource())
        self.lora = overrides.pop("lora", FakeLoraResource())
        assert not overrides, f"unknown fake overrides: {sorted(overrides)}"


def _trainer(client=None, **kwargs):
    kwargs.setdefault("poll_interval_seconds", 0.0)
    return FireworksTrainer(BASE_MODEL, client=client or FakeFireworksClient(), **kwargs)


def _checkpoint(ref="accounts/test-account/models/agno-sft-abc", base_model=BASE_MODEL):
    return Checkpoint(ref=ref, base_model=base_model, dataset_digest="abc", hyperparams={})


# ---------------------------------------------------------------------------
# The dataset gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "match"),
    [
        (['{"messages": [{"role": "user", "content": "only a user turn"}]}'] * 3, "assistant"),
        ([json.dumps(CONVERSATION)] * 2, "at least 3"),
        (["not json"] * 3, "not valid JSON"),
        (['{"messages": []}'] * 3, "non-empty messages"),
        (['{"messages": [{"role": "tool", "content": "x"}, {"role": "assistant", "content": "y"}]}'] * 3, "role"),
        (['{"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": " "}]}'] * 3, "content"),
        (
            [
                '{"messages": [{"role": "assistant", "content": "a"}, {"role": "user", "content": "x"}, '
                '{"role": "assistant", "content": "b"}]}'
            ]
            * 3,
            "exactly one assistant",
        ),
        (['{"messages": [{"role": "user", "content": "x", "weight": 0}]}'] * 3, "only role and content"),
        (['{"messages": [{"role": "user", "content": "x"}], "weight": 1}'] * 3, "only a messages field"),
    ],
)
def test_fireworks_trainer_fit_validates_dataset(tmp_path, rows, match):
    # The gate in front of a paid call: a malformed dataset is refused before any
    # dataset record or job is created server-side.
    bad = tmp_path / "bad.jsonl"
    bad.write_text("\n".join(rows) + "\n", encoding="utf-8")

    client = FakeFireworksClient()
    trainer = _trainer(client)

    with pytest.raises(ValueError, match=match):
        trainer.fit(bad)

    assert client.datasets.create_calls == []
    assert client.supervised_fine_tuning_jobs.create_calls == []


def test_fireworks_validator_accepts_the_exporter_shape(tmp_path):
    # to_sft_jsonl output -- system/user/assistant, one assistant, final -- passes,
    # and Tinker's 320-conversation cap deliberately does not apply.
    row = {
        "messages": [
            {"role": "system", "content": "Write a haiku."},
            {"role": "user", "content": "the sea"},
            {"role": "assistant", "content": "an old silent pond"},
        ]
    }
    path = tmp_path / "ok.jsonl"
    path.write_text("\n".join(json.dumps(row) for _ in range(400)) + "\n", encoding="utf-8")

    assert validate_fireworks_sft_jsonl(path) == 400


# ---------------------------------------------------------------------------
# The managed-job lifecycle
# ---------------------------------------------------------------------------


def test_fireworks_trainer_fit_maps_job_lifecycle(tmp_path):
    # COMPLETED becomes a completed TrainResult whose checkpoint points at the tuned
    # model resource; the poll snapshots carry only what Fireworks reported.
    jobs = FakeJobsResource(
        snapshots=[
            {"state": "JOB_STATE_PENDING"},
            {"state": "JOB_STATE_RUNNING", "progress": {"percent": 50, "epoch": 0}},
            {"state": "JOB_STATE_COMPLETED"},
        ]
    )
    client = FakeFireworksClient(jobs=jobs)
    trainer = _trainer(client, rank=8, learning_rate=2e-4, epochs=2)

    result = trainer.fit(_dataset(tmp_path))

    assert result.status == TrainStatus.COMPLETED
    assert result.error is None
    assert isinstance(result.checkpoint, Checkpoint)
    assert result.checkpoint.base_model == BASE_MODEL
    assert result.checkpoint.ref.startswith("accounts/test-account/models/agno-sft-")
    assert result.checkpoint.dataset_digest
    # batch_size is deliberately absent: the managed job owns batching.
    assert set(result.checkpoint.hyperparams) == {"rank", "learning_rate", "epochs", "train_on"}

    create = jobs.create_calls[0]
    assert create["base_model"] == BASE_MODEL
    assert create["dataset"] == f"accounts/test-account/datasets/agno-{result.checkpoint.dataset_digest[:16]}"
    assert create["output_model"] == result.checkpoint.ref
    assert create["lora_rank"] == 8
    assert create["learning_rate"] == 2e-4
    assert create["epochs"] == 2

    # The dataset really went up first, and was polled to READY.
    assert client.datasets.create_calls[0]["dataset"] == {"exampleCount": "3"}
    assert client.datasets.upload_calls[0]["file"] == _dataset(tmp_path)
    assert client.datasets.get_calls

    # Snapshots record state transitions with only Fireworks-reported fields; no
    # fabricated loss curve.
    assert [snapshot["state"] for snapshot in result.step_metrics] == [
        "JOB_STATE_PENDING",
        "JOB_STATE_RUNNING",
        "JOB_STATE_COMPLETED",
    ]
    assert result.step_metrics[1]["percent"] == 50
    assert result.step_metrics[1]["epoch"] == 0
    assert all("mean_nll" not in snapshot for snapshot in result.step_metrics)

    # fit never touches serving: no deployment exists until a serving door is opened.
    assert client.deployments.create_calls == []
    assert client.lora.load_calls == []


def test_fireworks_trainer_fit_failed_job(tmp_path):
    jobs = FakeJobsResource(
        snapshots=[
            {"state": "JOB_STATE_RUNNING"},
            {"state": "JOB_STATE_FAILED", "message": "dataset schema rejected"},
        ]
    )
    trainer = _trainer(FakeFireworksClient(jobs=jobs))

    result = trainer.fit(_dataset(tmp_path))

    assert result.status == TrainStatus.FAILED
    assert result.checkpoint is None
    assert "JOB_STATE_FAILED" in result.error
    assert "dataset schema rejected" in result.error
    # There is no recovery path on a managed job: FAILED means nothing was kept.
    assert result.step_metrics  # the observed states are still reported


def test_fireworks_trainer_fit_timeout_does_not_cancel(tmp_path):
    # A poll timeout gives up WAITING, not the job: no cancel, no retry, and the
    # error says the job may still complete.
    jobs = FakeJobsResource(snapshots=[{"state": "JOB_STATE_RUNNING"}])
    client = FakeFireworksClient(jobs=jobs)
    trainer = _trainer(client, train_timeout_seconds=0.01)

    result = trainer.fit(_dataset(tmp_path))

    assert result.status == TrainStatus.FAILED
    assert result.checkpoint is None
    assert "NOT cancelled" in result.error
    assert "job-1" in result.error
    assert len(jobs.create_calls) == 1  # never re-created / retried


def test_fireworks_trainer_fit_reuses_identical_dataset(tmp_path):
    # The dataset id derives from the file digest, so re-fitting the same bytes hits
    # a 409 on create and skips the upload instead of failing.
    datasets = FakeDatasetsResource(create_raises=FakeAPIError(409, "already exists"))
    client = FakeFireworksClient(datasets=datasets)
    trainer = _trainer(client)

    result = trainer.fit(_dataset(tmp_path))

    assert result.status == TrainStatus.COMPLETED
    assert datasets.upload_calls == []
    assert client.supervised_fine_tuning_jobs.create_calls


def test_fireworks_trainer_train_on_values_coincide(tmp_path):
    # The validator admits only single-assistant-final conversations, on which
    # LAST_ASSISTANT and ALL_ASSISTANT train the same tokens; both are accepted and
    # recorded, and the job request is identical either way.
    client = FakeFireworksClient()
    trainer = _trainer(client)

    last = trainer.fit(_dataset(tmp_path))
    everything = trainer.fit(_dataset(tmp_path), train_on=TrainOn.ALL_ASSISTANT)

    assert last.checkpoint.hyperparams["train_on"] == "last_assistant"
    assert everything.checkpoint.hyperparams["train_on"] == "all_assistant"
    first, second = client.supervised_fine_tuning_jobs.create_calls
    assert {k: v for k, v in first.items() if k != "output_model"} == {
        k: v for k, v in second.items() if k != "output_model"
    }


def test_fireworks_trainer_guards_every_hyperparameter_before_any_client_call():
    calls = []

    class Guarded(FireworksTrainer):
        def _get_client(self):
            calls.append(1)
            raise AssertionError("client reached")

    for kwargs, match in [
        ({"base_model": ""}, "base_model"),
        ({"base_model": "   "}, "base_model"),
        ({"epochs": 0}, "epochs"),
        ({"epochs": True}, "epochs"),
        ({"rank": 0}, "rank"),
        ({"rank": True}, "rank"),
        ({"learning_rate": 0.0}, "learning_rate"),
        ({"learning_rate": float("nan")}, "learning_rate"),
        ({"learning_rate": float("inf")}, "learning_rate"),
        ({"sampling_temperature": 0.0}, "sampling_temperature"),
        ({"sampling_temperature": float("nan")}, "sampling_temperature"),
        ({"sampling_max_tokens": 0}, "sampling_max_tokens"),
        ({"poll_interval_seconds": -1}, "poll_interval_seconds"),
        ({"ready_timeout_seconds": 0}, "ready_timeout_seconds"),
        ({"train_timeout_seconds": 0}, "train_timeout_seconds"),
    ]:
        with pytest.raises(ValueError, match=match):
            Guarded(**{"base_model": BASE_MODEL, **kwargs})

    assert calls == []


# ---------------------------------------------------------------------------
# Serving -- one deployment, two policies
# ---------------------------------------------------------------------------


def test_fireworks_trainer_as_model_returns_fireworks_model():
    client = FakeFireworksClient()
    trainer = _trainer(client, sampling_temperature=0.9, sampling_max_tokens=1234)
    checkpoint = _checkpoint()

    base = trainer.base_as_model()
    tuned = trainer.as_model(checkpoint)

    assert isinstance(base, Fireworks) and isinstance(tuned, Fireworks)

    # ONE deployment serves both sides, so the before/after runs on identical
    # hardware and precision.
    assert len(client.deployments.create_calls) == 1
    create = client.deployments.create_calls[0]
    assert create["base_model"] == BASE_MODEL
    assert create["enable_addons"] is True
    assert create["precision"] == "BF16"
    assert create["min_replica_count"] == 0
    assert create["max_replica_count"] == 1
    deployment_name = f"accounts/test-account/deployments/{create['deployment_id']}"

    assert base.id == f"{BASE_MODEL}#{deployment_name}"
    assert tuned.id == f"{checkpoint.ref}#{deployment_name}"

    # The tuned LoRA was loaded onto that deployment and polled to DEPLOYED.
    assert client.lora.load_calls == [{"model": checkpoint.ref, "deployment": deployment_name}]
    assert client.lora.get_calls

    for model in (base, tuned):
        assert model.temperature == 0.9
        assert model.max_tokens == 1234
        assert model.system_prompt is None and model.instructions is None

    # Serving never trains.
    assert client.supervised_fine_tuning_jobs.create_calls == []


def test_fireworks_trainer_as_model_rejects_foreign_checkpoint():
    trainer = _trainer()
    foreign = _checkpoint(base_model="accounts/fireworks/models/qwen3-4b")

    with pytest.raises(ValueError, match="qwen3-4b"):
        trainer.as_model(foreign)


def test_fireworks_trainer_byo_deployment_is_used_and_never_deleted():
    client = FakeFireworksClient()
    trainer = _trainer(client, deployment_id="my-deployment")

    base = trainer.base_as_model()
    trainer.as_model(_checkpoint())
    trainer.teardown()

    assert client.deployments.create_calls == []  # brought, not created
    assert base.id == f"{BASE_MODEL}#accounts/test-account/deployments/my-deployment"
    assert client.deployments.delete_calls == []  # never deleted
    assert client.lora.unload_calls == ["dm-1"]  # but our addon is unloaded


def test_fireworks_trainer_teardown_deletes_created_deployment():
    client = FakeFireworksClient()
    trainer = _trainer(client)

    trainer.base_as_model()
    trainer.as_model(_checkpoint())
    trainer.teardown()
    trainer.teardown()  # idempotent

    created_id = client.deployments.create_calls[0]["deployment_id"]
    assert client.deployments.delete_calls == [created_id]
    assert client.lora.unload_calls == ["dm-1"]


def test_fireworks_trainer_already_loaded_lora_is_reused():
    lora = FakeLoraResource(load_raises=FakeAPIError(409, "already loaded"))
    client = FakeFireworksClient(lora=lora)
    trainer = _trainer(client)
    checkpoint = _checkpoint()

    tuned = trainer.as_model(checkpoint)

    assert isinstance(tuned, Fireworks)
    assert tuned.id.startswith(f"{checkpoint.ref}#")
    assert lora.get_calls == []  # nothing new to wait for


# ---------------------------------------------------------------------------
# Fingerprints -- the identity the whole before/after rests on
# ---------------------------------------------------------------------------


def three_lines(run, expected):
    return len([line for line in run.content.strip().split("\n") if line.strip()]) == 3


def test_fireworks_trainer_policy_diverges_env_matches():
    # Base and tuned must differ in POLICY and agree on ENVIRONMENT. Get the first
    # wrong and diff.policy_changed reads False while the pass rate rises; get the
    # second wrong and diff() raises MismatchError instead of measuring.
    trainer = _trainer()

    base = trainer.base_as_model()
    tuned = trainer.as_model(_checkpoint())

    assert base.id != tuned.id
    assert base.provider == tuned.provider == "Fireworks"

    base_policy = _policy_fingerprint_of(base)
    tuned_policy = _policy_fingerprint_of(tuned)
    assert base_policy is not None and tuned_policy is not None
    assert base_policy != tuned_policy

    # Model-level prompt fields stay None, so the env fingerprint is unmoved by the
    # model swap.
    agent = Agent(model=base)
    env = Environment(
        name="fp",
        agent=agent,
        tasks=(Task(id="sea", input="the sea"),),
        scorer=CodeScorer(three_lines),
    )
    base_env = _env_fingerprint_of(env, agent, model=base)
    tuned_env = _env_fingerprint_of(env, agent, model=tuned)
    assert base_env is not None
    assert base_env == tuned_env


# ---------------------------------------------------------------------------
# Async twins, and the offline contract
# ---------------------------------------------------------------------------


async def test_fireworks_trainer_afit_matches_fit(tmp_path):
    sync_trainer = _trainer()
    async_trainer = _trainer()

    sync_result = sync_trainer.fit(_dataset(tmp_path))
    async_result = await async_trainer.afit(_dataset(tmp_path))

    assert async_result.status == sync_result.status == TrainStatus.COMPLETED
    assert async_result.checkpoint.dataset_digest == sync_result.checkpoint.dataset_digest
    assert async_result.checkpoint.hyperparams == sync_result.checkpoint.hyperparams
    assert [s["state"] for s in async_result.step_metrics] == [s["state"] for s in sync_result.step_metrics]

    assert isinstance(await async_trainer.aas_model(async_result.checkpoint), Fireworks)
    assert isinstance(await async_trainer.abase_as_model(), Fireworks)
    await async_trainer.ateardown()


async def test_fireworks_trainer_serving_doors_do_not_block_the_event_loop():
    # Serving can create a deployment and poll it ready -- blocking network calls.
    # Dispatched inline they would freeze every concurrent rollout coroutine.
    import asyncio
    import threading
    import time

    loop_thread = threading.current_thread()
    serving_threads = []

    class BlockingDeployments(FakeDeploymentsResource):
        def create(self, **kwargs):
            serving_threads.append(threading.current_thread())
            time.sleep(0.2)  # a slow control-plane call
            super().create(**kwargs)

    trainer = _trainer(FakeFireworksClient(deployments=BlockingDeployments()))

    ticks = 0

    async def tick_while_serving():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    ticker = asyncio.ensure_future(tick_while_serving())
    try:
        await trainer.abase_as_model()
        await trainer.aas_model(_checkpoint())
    finally:
        ticker.cancel()

    assert ticks >= 5  # the event loop kept turning
    assert serving_threads and all(thread is not loop_thread for thread in serving_threads)


def test_fireworks_trainer_never_imports_the_sdk_with_an_injected_client(tmp_path):
    # The offline contract, stated literally: a full train-and-serve pass through an
    # injected fake never imports the fireworks SDK (which is not installed here).
    trainer = _trainer()

    result = trainer.fit(_dataset(tmp_path))
    trainer.base_as_model()
    trainer.as_model(result.checkpoint)
    trainer.teardown()

    assert "fireworks" not in sys.modules
