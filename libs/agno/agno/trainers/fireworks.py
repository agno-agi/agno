"""Fine-tune an open-weights model on Fireworks, and serve the result as an agno Model.

Fireworks runs supervised fine-tuning as a managed job: upload the dataset, create the
job, poll it to a terminal state, and the platform hands back a LoRA model resource.
Serving is the part that differs from Tinker: Fireworks does not serve fine-tuned LoRAs
(or the small tunable base models) serverless, so measuring either side of the
before/after needs an on-demand deployment. This trainer keeps ONE such deployment --
the base model with PEFT addons enabled, BF16 -- and serves base and tuned from it, so
the comparison runs on identical hardware and precision and the only difference between
the two policies is the weights.

The deployment is the cost to know about. An on-demand deployment bills GPU time while
replicas run (order $7+/hour for a single-GPU shape); it is created with
min_replica_count=0 so it scales to zero when idle and Fireworks auto-deletes it after
seven idle days, and `teardown()` deletes it deterministically. Pass `deployment_id=`
to bring your own addons-enabled deployment instead; the trainer never deletes a
deployment it did not create. The first request after a scale-to-zero pays a cold-start
delay, so give the environment a generous `timeout_seconds`.

**Import style is a deliberate deviation.** The `fireworks` SDK is imported lazily,
inside methods, so this module imports cleanly with the SDK uninstalled and its tests
can inject a fake client. That is load-bearing for the offline test contract -- do not
"fix" it to the module-level try/except convention.

Consent is the caller's. `fit()` trains when called and the serving doors deploy when
called: they do not gate spend, ask for authorization, or retry a paid job. That policy
belongs to whoever holds the budget.
"""

import asyncio
import hashlib
import json
import math
import time
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from agno.models.base import Model
from agno.models.fireworks import Fireworks
from agno.trainers.base import Checkpoint, TrainOn, TrainResult, TrainStatus
from agno.utils.log import log_info, log_warning

# Fireworks' own dataset rules (docs.fireworks.ai, verified July 2026): at least 3
# examples, at most 3M, and the one-shot :upload path caps the file at 150 MB. The
# Tinker oracle's 320-conversation / 1 MiB caps deliberately do NOT apply here.
MIN_EXAMPLES = 3
MAX_EXAMPLES = 3_000_000
MAX_UPLOAD_BYTES = 150 * 1024 * 1024

_MESSAGE_ROLES = frozenset({"system", "user", "assistant"})

# fireworks.types.SupervisedFineTuningJob.state values, verified against the SDK.
_JOB_SUCCESS_STATES = frozenset({"JOB_STATE_COMPLETED", "JOB_STATE_EARLY_STOPPED"})
_JOB_FAILURE_STATES = frozenset(
    {
        "JOB_STATE_FAILED",
        "JOB_STATE_CANCELLED",
        "JOB_STATE_EXPIRED",
        "JOB_STATE_DELETING",
        "JOB_STATE_DELETING_CLEANING_UP",
        # Paused means account suspension or manual intervention; resuming it is a
        # billing decision, so it is surfaced as a failure rather than waited out.
        "JOB_STATE_PAUSED",
    }
)


def validate_fireworks_sft_jsonl(path: Union[str, Path]) -> int:
    """Validate a dataset against Fireworks' supervised fine-tuning rules.

    Returns the number of examples; raises ValueError on the first violation, so a
    malformed file is refused before any dataset or job resource is created.

    This is a THIRD validator next to the byte-identical pair in
    `agno/environments/exporters/_validate.py` / `agno/trainers/_validate.py`, and the
    divergence is deliberate: those two encode Tinker's consumer caps (320
    conversations, 1 MiB), Fireworks allows up to 3M examples with a 3-example
    minimum. Do not unify them.

    One rule is stricter than the platform's: each example must contain exactly one
    assistant message, in final position. Fireworks trains on every assistant message
    unless per-message weights say otherwise, so this is what keeps
    `TrainOn.LAST_ASSISTANT` exact without rewriting the uploaded file. `to_sft_jsonl`
    output satisfies it by construction; multi-assistant conversations are 2.9's
    flattened export and get per-message weights then.
    """
    text = Path(path).read_text(encoding="utf-8")
    size = len(text.encode("utf-8"))
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(f"dataset is {size} bytes; the one-shot upload path is capped at {MAX_UPLOAD_BYTES} bytes")
    if not text.strip():
        raise ValueError("dataset must contain at least one conversation")
    # Split on "\n" only, matching the canonical writer: splitlines() also breaks on
    # U+2028/U+2029/U+0085, which json.dumps(ensure_ascii=False) emits unescaped.
    lines = text.strip().split("\n")
    if len(lines) < MIN_EXAMPLES:
        raise ValueError(f"dataset has {len(lines)} examples; Fireworks requires at least {MIN_EXAMPLES}")
    if len(lines) > MAX_EXAMPLES:
        raise ValueError(f"dataset has {len(lines)} examples; the limit is {MAX_EXAMPLES}")
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ValueError(f"line {line_number} is blank; JSONL requires one object per line")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number} is not valid JSON: {exc.msg}") from exc
        if not isinstance(value, dict) or set(value) != {"messages"}:
            raise ValueError(f"line {line_number} must contain only a messages field")
        messages = value["messages"]
        if not isinstance(messages, list) or not messages:
            raise ValueError(f"line {line_number} must have a non-empty messages list")
        assistant_positions: List[int] = []
        for message_number, message in enumerate(messages, start=1):
            prefix = f"line {line_number}, message {message_number}"
            if not isinstance(message, dict) or set(message) != {"role", "content"}:
                raise ValueError(f"{prefix} must contain only role and content")
            role = message["role"]
            content = message["content"]
            if not isinstance(role, str) or role not in _MESSAGE_ROLES:
                raise ValueError(f"{prefix} has unsupported role {role!r}")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"{prefix} content must be a non-empty string")
            if role == "assistant":
                assistant_positions.append(message_number)
        if not any(message["role"] == "user" for message in messages):
            raise ValueError(f"line {line_number} must contain a user message")
        if messages[-1]["role"] != "assistant":
            raise ValueError(f"line {line_number} must end with an assistant message")
        if assistant_positions != [len(messages)]:
            raise ValueError(
                f"line {line_number} must contain exactly one assistant message, in final position: "
                "Fireworks trains on every assistant message, so an earlier assistant turn would be "
                "trained on too, silently changing what train_on=LAST_ASSISTANT means"
            )
    return len(lines)


class FireworksTrainer:
    """A `Trainer` backed by Fireworks' managed supervised fine-tuning and serving.

    The tuned artifact is a LoRA model resource (`accounts/<account>/models/<id>`)
    that persists until deleted, so unlike Tinker checkpoints the ref itself is
    durable; the dataset file plus `dataset_digest` and `hyperparams` remain the
    reproducible provenance.

    `TrainStatus.PARTIAL` is never produced: a managed job exposes no mid-run
    recoverable checkpoint, so a job that dies mid-run is `FAILED` with nothing to
    keep. This is a real difference from `TinkerTrainer`, which drives the training
    loop itself and can save what the completed steps paid for.

    Both `TrainOn` values are accepted and behave identically here: the dataset
    validator admits only single-assistant-final conversations (see
    `validate_fireworks_sft_jsonl`), on which training the last assistant message and
    training all of them are the same thing. Data that distinguishes them arrives
    with 2.9's multi-turn export.
    """

    def __init__(
        self,
        base_model: str,
        *,
        rank: int = 16,
        learning_rate: float = 1e-4,
        epochs: int = 1,
        sampling_temperature: float = 0.7,
        sampling_max_tokens: int = 2000,
        sampling_reasoning_effort: Optional[str] = None,
        account_id: Optional[str] = None,
        deployment_id: Optional[str] = None,
        accelerator_type: str = "NVIDIA_H100_80GB",
        poll_interval_seconds: float = 10.0,
        ready_timeout_seconds: float = 1800.0,
        train_timeout_seconds: Optional[float] = None,
        client: Optional[Any] = None,
    ) -> None:
        # Every hyperparameter is validated here, before any client call could
        # possibly be made -- a bad value that only fails inside fit() has already
        # created billable resources.
        if not isinstance(base_model, str) or not base_model.strip():
            raise ValueError(f"base_model must be a non-blank model name, got {base_model!r}")
        if not isinstance(accelerator_type, str) or not accelerator_type.strip():
            raise ValueError(f"accelerator_type must be a non-blank accelerator name, got {accelerator_type!r}")
        if isinstance(epochs, bool) or not isinstance(epochs, int) or epochs < 1:
            raise ValueError(f"epochs must be an int >= 1, got {epochs!r}")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise ValueError(f"rank must be an int >= 1, got {rank!r}")
        if isinstance(sampling_max_tokens, bool) or not isinstance(sampling_max_tokens, int) or sampling_max_tokens < 1:
            raise ValueError(f"sampling_max_tokens must be an int >= 1, got {sampling_max_tokens!r}")
        if (
            isinstance(learning_rate, bool)
            or not isinstance(learning_rate, (int, float))
            or not (math.isfinite(learning_rate) and learning_rate > 0)
        ):
            raise ValueError(f"learning_rate must be a finite value > 0, got {learning_rate!r}")
        if (
            isinstance(sampling_temperature, bool)
            or not isinstance(sampling_temperature, (int, float))
            or not (math.isfinite(sampling_temperature) and sampling_temperature > 0)
        ):
            # The negated form also rejects NaN, which passes every plain comparison.
            raise ValueError(
                f"sampling_temperature must be a finite value > 0, got {sampling_temperature!r}: at "
                "temperature 0 all k attempts are identical and the learning zone is empty by construction"
            )
        if not (
            isinstance(poll_interval_seconds, (int, float))
            and not isinstance(poll_interval_seconds, bool)
            and math.isfinite(poll_interval_seconds)
            and poll_interval_seconds >= 0
        ):
            raise ValueError(f"poll_interval_seconds must be a finite value >= 0, got {poll_interval_seconds!r}")
        if not (
            isinstance(ready_timeout_seconds, (int, float))
            and not isinstance(ready_timeout_seconds, bool)
            and math.isfinite(ready_timeout_seconds)
            and ready_timeout_seconds > 0
        ):
            raise ValueError(f"ready_timeout_seconds must be a finite value > 0, got {ready_timeout_seconds!r}")
        if train_timeout_seconds is not None and not (
            isinstance(train_timeout_seconds, (int, float))
            and not isinstance(train_timeout_seconds, bool)
            and math.isfinite(train_timeout_seconds)
            and train_timeout_seconds > 0
        ):
            raise ValueError(f"train_timeout_seconds must be None or a finite value > 0, got {train_timeout_seconds!r}")
        self.base_model = base_model
        self.rank = rank
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.sampling_temperature = sampling_temperature
        self.sampling_max_tokens = sampling_max_tokens
        self.sampling_reasoning_effort = sampling_reasoning_effort
        self.account_id = account_id
        self.deployment_id = deployment_id
        self.accelerator_type = accelerator_type
        self.poll_interval_seconds = poll_interval_seconds
        self.ready_timeout_seconds = ready_timeout_seconds
        self.train_timeout_seconds = train_timeout_seconds
        self._client = client
        self._deployment_name: Optional[str] = None
        self._created_deployment_id: Optional[str] = None
        self._loaded_addon_ids: List[str] = []

    # -- lazy SDK wiring ---------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            from fireworks import Fireworks as FireworksClient

            self._client = FireworksClient(account_id=self.account_id)
        return self._client

    def _resolve_account_id(self, client: Any) -> str:
        for candidate in (self.account_id, getattr(client, "account_id", None), getenv("FIREWORKS_ACCOUNT_ID")):
            if candidate:
                return str(candidate)
        raise ValueError(
            "Fireworks account id required: pass account_id= to FireworksTrainer, set the "
            "FIREWORKS_ACCOUNT_ID environment variable, or inject a client constructed with one."
        )

    def _wait_until_ready(self, what: str, fetch: Any, is_ready: Any, is_failed: Any) -> Any:
        deadline = time.monotonic() + self.ready_timeout_seconds
        while True:
            resource = fetch()
            failure = is_failed(resource)
            if failure:
                raise RuntimeError(f"{what} failed: {failure}")
            if is_ready(resource):
                return resource
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{what} not ready after {self.ready_timeout_seconds}s")
            time.sleep(self.poll_interval_seconds)

    # -- fit ---------------------------------------------------------------------

    def fit(self, dataset: Union[str, Path], *, train_on: TrainOn = TrainOn.LAST_ASSISTANT) -> TrainResult:
        """Upload `dataset`, run a managed supervised fine-tuning job, and poll it to
        a terminal state.

        The dataset is validated before any call is made: a file the gate rejects
        becomes a `FAILED` result, for free, with no dataset record and no job
        created. It is a result rather than a raise because the improvement loop
        legitimately produces datasets below Fireworks' 3-example minimum (its own
        floor is one exported row), and an exception out of `fit` would crash
        `run()` mid-loop where a `FAILED` result ends it with a clean terminal
        report. A poll timeout (`train_timeout_seconds`) returns `FAILED` but does
        NOT cancel the job -- it keeps running on Fireworks and may still complete;
        the error names it. A job is never retried.
        """
        path = Path(dataset)

        hyperparams: Dict[str, Any] = {
            "rank": self.rank,
            "learning_rate": self.learning_rate,
            "epochs": self.epochs,
            "train_on": train_on.value,
            # batch_size is deliberately absent: the managed job owns batching.
        }
        step_metrics: List[Dict[str, Any]] = []

        try:
            # The runtime gate, before anything is created server-side.
            n_examples = validate_fireworks_sft_jsonl(path)
            dataset_digest = hashlib.sha256(path.read_bytes()).hexdigest()

            client = self._get_client()
            account_id = self._resolve_account_id(client)

            dataset_id = f"agno-{dataset_digest[:16]}"
            self._upload_dataset(client, dataset_id, path, n_examples)

            output_model = f"accounts/{account_id}/models/agno-sft-{uuid4().hex[:10]}"
            job = client.supervised_fine_tuning_jobs.create(
                dataset=f"accounts/{account_id}/datasets/{dataset_id}",
                base_model=self.base_model,
                output_model=output_model,
                epochs=self.epochs,
                learning_rate=self.learning_rate,
                lora_rank=self.rank,
                display_name=f"agno sft {dataset_digest[:12]}",
            )
            job_name = getattr(job, "name", None) or ""
            job_id = job_name.rsplit("/", 1)[-1]
            if not job_id:
                return TrainResult(
                    checkpoint=None,
                    step_metrics=step_metrics,
                    status=TrainStatus.FAILED,
                    error="Fireworks did not return a job name; cannot poll the fine-tuning job",
                )
            log_info(f"FireworksTrainer: created fine-tuning job {job_name} -> {output_model}")

            deadline = None if self.train_timeout_seconds is None else time.monotonic() + self.train_timeout_seconds
            while True:
                state = getattr(job, "state", None) or "JOB_STATE_UNSPECIFIED"
                snapshot = self._progress_snapshot(job, state, step=len(step_metrics) + 1)
                if not step_metrics or {k: v for k, v in step_metrics[-1].items() if k != "step"} != {
                    k: v for k, v in snapshot.items() if k != "step"
                }:
                    step_metrics.append(snapshot)
                if state in _JOB_SUCCESS_STATES:
                    break
                if state in _JOB_FAILURE_STATES:
                    return TrainResult(
                        checkpoint=None,
                        step_metrics=step_metrics,
                        status=TrainStatus.FAILED,
                        error=f"fine-tuning job {job_name} ended {state}: {self._status_message(job)}",
                    )
                if deadline is not None and time.monotonic() >= deadline:
                    return TrainResult(
                        checkpoint=None,
                        step_metrics=step_metrics,
                        status=TrainStatus.FAILED,
                        error=(
                            f"timed out after {self.train_timeout_seconds}s waiting for {job_name}; the job "
                            "was NOT cancelled and may still complete -- check it on Fireworks and, if it "
                            "finishes, serve its output model directly rather than re-running fit"
                        ),
                    )
                time.sleep(self.poll_interval_seconds)
                job = client.supervised_fine_tuning_jobs.get(job_id)

            ref = getattr(job, "output_model", None) or output_model
            log_info(f"FireworksTrainer: job {job_name} completed; tuned model {ref}")
            return TrainResult(
                checkpoint=Checkpoint(
                    ref=ref,
                    base_model=self.base_model,
                    dataset_digest=dataset_digest,
                    hyperparams=hyperparams,
                ),
                step_metrics=step_metrics,
                status=TrainStatus.COMPLETED,
            )
        except Exception as exc:
            # No recovery path: a managed job that failed left nothing servable
            # behind, and retrying it is a billing decision that belongs to the
            # caller.
            error = f"{type(exc).__name__}: {str(exc).strip() or 'no details'}"
            return TrainResult(checkpoint=None, step_metrics=step_metrics, status=TrainStatus.FAILED, error=error)

    async def afit(self, dataset: Union[str, Path], *, train_on: TrainOn = TrainOn.LAST_ASSISTANT) -> TrainResult:
        """Async twin of `fit`. Upload and polling block, so they run off-thread."""
        return await asyncio.to_thread(self.fit, dataset, train_on=train_on)

    def _upload_dataset(self, client: Any, dataset_id: str, path: Path, n_examples: int) -> None:
        """Create the dataset record and upload the file, reusing an identical prior upload.

        The dataset id is derived from the file digest, so re-fitting the same bytes
        hits the same record: a conflict on create means the contents are already
        there and the upload is skipped once the record reports READY.
        """
        try:
            client.datasets.create(dataset_id=dataset_id, dataset={"exampleCount": str(n_examples)})
        except Exception as exc:
            if getattr(exc, "status_code", None) != 409:
                raise
            existing = client.datasets.get(dataset_id=dataset_id)
            if getattr(existing, "state", None) == "READY":
                log_info(f"FireworksTrainer: dataset {dataset_id} already uploaded; reusing it")
                return
        client.datasets.upload(dataset_id=dataset_id, file=path)
        self._wait_until_ready(
            f"dataset {dataset_id}",
            lambda: client.datasets.get(dataset_id=dataset_id),
            lambda resource: getattr(resource, "state", None) == "READY",
            lambda resource: (
                self._status_message(resource)
                if getattr(resource, "state", None) not in (None, "STATE_UNSPECIFIED", "UPLOADING", "READY")
                else None
            ),
        )

    @staticmethod
    def _progress_snapshot(job: Any, state: str, *, step: int) -> Dict[str, Any]:
        """Only what Fireworks actually reports. The loss curve is not surfaced as
        JSON by the job API (it lives behind `metrics_file_signed_url`), so no
        `mean_nll` is ever fabricated here."""
        snapshot: Dict[str, Any] = {"step": step, "state": state}
        progress = getattr(job, "job_progress", None)
        percent = getattr(progress, "percent", None)
        epoch = getattr(progress, "epoch", None)
        if percent is not None:
            snapshot["percent"] = percent
        if epoch is not None:
            snapshot["epoch"] = epoch
        return snapshot

    @staticmethod
    def _status_message(resource: Any) -> str:
        status = getattr(resource, "status", None)
        message = getattr(status, "message", None)
        return str(message) if message else "no details"

    # -- serving -----------------------------------------------------------------

    def _ensure_deployment(self) -> str:
        """The one on-demand deployment base and tuned are both measured on.

        Created on first use (BF16, PEFT addons enabled, min replicas 0 so idle time
        is free, max 1 so the spend is bounded to a single replica), or resolved from
        `deployment_id` when the caller brought their own. Billing runs while a
        replica serves; `teardown()` deletes a created deployment deterministically,
        and Fireworks auto-deletes a min-0 deployment after seven idle days.
        """
        if self._deployment_name is not None:
            return self._deployment_name
        client = self._get_client()
        account_id = self._resolve_account_id(client)
        if self.deployment_id:
            deployment = client.deployments.get(self.deployment_id)
            if getattr(deployment, "state", None) != "READY":
                deployment = self._wait_for_deployment(client, self.deployment_id)
            if getattr(deployment, "enable_addons", None) is False:
                log_warning(
                    f"FireworksTrainer: deployment {self.deployment_id} has addons disabled; "
                    "serving a tuned LoRA on it will fail. Create it with enable_addons=True."
                )
            self._deployment_name = f"accounts/{account_id}/deployments/{self.deployment_id}"
            return self._deployment_name
        if self._created_deployment_id is None:
            deployment_id = f"agno-{uuid4().hex[:10]}"
            # Tracked BEFORE the billable call: a create whose response is lost (or
            # whose readiness poll fails) must still leave teardown() a handle to
            # delete, not an orphaned deployment only the dashboard knows about.
            self._created_deployment_id = deployment_id
            client.deployments.create(
                base_model=self.base_model,
                deployment_id=deployment_id,
                display_name=f"agno improvement loop {deployment_id}",
                # The control plane requires an explicit accelerator for non-embeddings
                # engines. An H100 80GB is the default: it holds the small tunable bases
                # in BF16 with addons, and fresh accounts carry quota for it (the A100
                # pool can be zero-quota'd, which 429s the create).
                accelerator_type=self.accelerator_type,
                # Some bases carry a default speculative-decoding draft model whose
                # precision (FP8_MM) the cheaper accelerators reject; speculation is a
                # latency optimization, not a correctness one, and this deployment
                # exists to measure a before/after, so it is off.
                disable_speculative_decoding=True,
                # BF16 because FP8/FP4 deployment shapes reject PEFT addons; addons are
                # how the tuned LoRA is served next to its base on the same hardware.
                enable_addons=True,
                precision="BF16",
                min_replica_count=0,
                max_replica_count=1,
            )
        else:
            # A prior attempt created (or may have created) this deployment and then
            # failed before it was ready; resolve it rather than provisioning a
            # second one the teardown handle would no longer cover.
            deployment_id = self._created_deployment_id
        self._wait_for_deployment(client, deployment_id)
        self._deployment_name = f"accounts/{account_id}/deployments/{deployment_id}"
        log_warning(
            f"FireworksTrainer: created on-demand deployment {self._deployment_name}; GPU time bills "
            "while it serves (it scales to zero when idle). Call teardown() to delete it when done."
        )
        return self._deployment_name

    def _wait_for_deployment(self, client: Any, deployment_id: str) -> Any:
        return self._wait_until_ready(
            f"deployment {deployment_id}",
            lambda: client.deployments.get(deployment_id),
            lambda resource: getattr(resource, "state", None) == "READY",
            lambda resource: (
                self._status_message(resource)
                if getattr(resource, "state", None) in ("FAILED", "DELETING", "DELETED")
                else None
            ),
        )

    def _serve(self, model_id: str) -> Model:
        # system_prompt/instructions stay None so base and tuned share one env
        # fingerprint; the id is the only policy difference (scorer/_model.py
        # excludes credentials and clients from the identity payload).
        extra: Dict[str, Any] = {}
        if self.sampling_reasoning_effort is not None:
            # Fireworks routes reasoning to a separate response field, and its parser
            # can classify an ENTIRE completion as reasoning on some serving templates
            # (observed live: qwen3-4b-instruct-2507, a non-thinking instruct model,
            # returned every token in `reasoning` and none in `content`, so no attempt
            # could ever be scored). "none" turns the reasoning channel off. Both sides
            # of the before/after get the same value, so the comparison holds.
            extra["reasoning_effort"] = self.sampling_reasoning_effort
        return Fireworks(
            id=model_id,
            temperature=self.sampling_temperature,
            max_tokens=self.sampling_max_tokens,
            **extra,
        )

    def as_model(self, checkpoint: Checkpoint) -> Model:
        """Serve a tuned checkpoint: load its LoRA onto the shared deployment and
        point an agno `Fireworks` model at `<model>#<deployment>`. Sampling params
        match `base_as_model`'s, so the only difference between the two policies is
        the weights."""
        if checkpoint.base_model != self.base_model:
            raise ValueError(
                f"checkpoint was trained from base_model {checkpoint.base_model!r} but this trainer "
                f"serves {self.base_model!r}: its LoRA cannot load onto this base's deployment, and "
                "serving it here would stamp a false policy identity. Serve it from a trainer built "
                "on its own base model."
            )
        deployment_name = self._ensure_deployment()
        client = self._get_client()
        try:
            deployed = client.lora.load(model=checkpoint.ref, deployment=deployment_name)
        except Exception as exc:
            if getattr(exc, "status_code", None) != 409:
                raise
            # Already loaded on this deployment (a re-serve of the same checkpoint);
            # nothing new to track or wait for.
            log_info(f"FireworksTrainer: {checkpoint.ref} already loaded on {deployment_name}")
        else:
            deployed_name = getattr(deployed, "name", None) or ""
            deployed_id = deployed_name.rsplit("/", 1)[-1]
            if not deployed_id:
                # Without a name there is nothing to poll, and returning unwaited
                # would hand the caller an address the gateway still 404s while the
                # addon is DEPLOYING (observed live: a full rollout of instant
                # model-not-found errors against a checkpoint that was fine).
                raise RuntimeError(
                    f"Fireworks did not return a deployed-model name for LoRA {checkpoint.ref} on "
                    f"{deployment_name}; cannot wait for it to reach DEPLOYED, so serving it now would "
                    "race the load and fail with model-not-found"
                )
            self._loaded_addon_ids.append(deployed_id)
            self._wait_until_ready(
                f"LoRA {checkpoint.ref} on {deployment_name}",
                lambda: client.lora.get(deployed_id),
                lambda resource: getattr(resource, "state", None) == "DEPLOYED",
                lambda resource: (
                    self._status_message(resource) if getattr(resource, "state", None) == "UNDEPLOYING" else None
                ),
            )
        return self._serve(f"{checkpoint.ref}#{deployment_name}")

    async def aas_model(self, checkpoint: Checkpoint) -> Model:
        # Serving can create a deployment and poll it ready -- minutes of blocking
        # network -- so it runs off-thread: dispatched inline it would freeze every
        # concurrent rollout coroutine before any engine timeout could fire.
        return await asyncio.to_thread(self.as_model, checkpoint)

    def base_as_model(self) -> Model:
        """Serve the untuned base from the same deployment the tuned checkpoint will
        use -- the baseline a before/after can trust, measured on identical hardware
        and precision."""
        deployment_name = self._ensure_deployment()
        return self._serve(f"{self.base_model}#{deployment_name}")

    async def abase_as_model(self) -> Model:
        return await asyncio.to_thread(self.base_as_model)

    # -- cleanup -----------------------------------------------------------------

    def teardown(self) -> None:
        """Release the serving infrastructure this trainer created.

        Unloads every LoRA it loaded, then deletes the deployment IF this trainer
        created it -- a `deployment_id` the caller brought is never deleted. Datasets
        and tuned model resources are left in place: they are the provenance and the
        artifact, and they do not bill by the hour. Best-effort and idempotent.
        """
        if self._client is None and self._created_deployment_id is None and not self._loaded_addon_ids:
            return
        client = self._get_client()
        for deployed_id in self._loaded_addon_ids:
            try:
                client.lora.unload(deployed_id)
            except Exception as exc:
                log_warning(f"FireworksTrainer: failed to unload LoRA {deployed_id}: {exc}")
        self._loaded_addon_ids = []
        if self._created_deployment_id is not None:
            try:
                # ignore_checks: the control plane refuses to delete a deployment that
                # served inference in the last hour, and this deployment just measured
                # a rollout -- without the override every teardown would orphan it.
                client.deployments.delete(self._created_deployment_id, ignore_checks=True)
                log_info(f"FireworksTrainer: deleted deployment {self._created_deployment_id}")
            except Exception as exc:
                log_warning(
                    f"FireworksTrainer: failed to delete deployment {self._created_deployment_id}: {exc}; "
                    "delete it on Fireworks to stop it billing"
                )
                return
            self._created_deployment_id = None
            self._deployment_name = None

    async def ateardown(self) -> None:
        await asyncio.to_thread(self.teardown)
