"""Fine-tune an open-weights model on Tinker, and serve the result as an agno Model.

Productionizes the training path that `rl-tutor/tutor/tinker_tools.py` already runs end
to end: validate the dataset, render each conversation to a training datum, run
forward/backward and an optimizer step per batch, collect the loss curve, and save
weights for the sampler.

**Import style is a deliberate deviation.** The `tinker` and `tinker_cookbook` SDKs are
imported lazily, *inside* methods, so this module imports cleanly with the SDK
uninstalled and its tests can inject fake clients. That is load-bearing for the offline
test contract -- do not "fix" it to the module-level try/except convention.

Consent is the caller's. `fit()` trains when called: it does not gate spend, ask for
authorization, or retry a paid run. That policy belongs to whoever holds the budget.
"""

import asyncio
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agno.models.base import Model
from agno.models.tinker import TinkerModel
from agno.trainers._validate import validate_sft_jsonl
from agno.trainers.base import Checkpoint, TrainOn, TrainResult, TrainStatus
from agno.utils.log import log_info, log_warning

# Copied from tinker_tools.py, where they are load-bearing for this exact path.
MAX_LENGTH = 1024
TRAINING_SEED = 0

# The SDK treats ttl_seconds=None as "never expires", so an unset TTL would leave a
# permanent LoRA checkpoint behind for every round of every loop. Mirrors rl-tutor.
CHECKPOINT_TTL_SECONDS = 7 * 24 * 60 * 60

# rl-tutor's MAX_STEPS=40 planning cap is deliberately NOT copied: the dataset
# validator's caps are the gate here, and at batch_size=8 / epochs=2 a full 320-row
# export is a legitimate fit that must not be refused.

_TRAIN_ON_WHAT = {
    TrainOn.LAST_ASSISTANT: "LAST_ASSISTANT_MESSAGE",
    TrainOn.ALL_ASSISTANT: "ALL_ASSISTANT_MESSAGES",
}


class TinkerTrainer:
    """A `Trainer` backed by the Tinker training and sampling APIs.

    Checkpoint refs are not durable: they are saved with a 7-day TTL, so `ref` only
    re-samples while it lives. The reproducible provenance is the dataset file plus the
    `dataset_digest` and `hyperparams` on the returned `Checkpoint`.
    """

    def __init__(
        self,
        base_model: str,
        *,
        rank: int = 16,
        learning_rate: float = 2e-4,
        epochs: int = 2,
        batch_size: int = 8,
        sampling_temperature: float = 0.7,
        sampling_max_tokens: int = 2000,
        service_client: Optional[Any] = None,
    ) -> None:
        if epochs < 1:
            raise ValueError(
                f"epochs must be >= 1, got {epochs}: zero epochs runs zero optimizer steps and "
                "saves the pristine base as a COMPLETED checkpoint"
            )
        if batch_size < 1:
            raise ValueError(f"batch_size must be >= 1, got {batch_size}")
        if not (math.isfinite(sampling_temperature) and sampling_temperature > 0):
            # The negated form also rejects NaN, which passes every plain comparison.
            raise ValueError(
                f"sampling_temperature must be a finite value > 0, got {sampling_temperature}: at "
                "temperature 0 all k attempts are identical and the learning zone is empty by construction"
            )
        self.base_model = base_model
        self.rank = rank
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.batch_size = batch_size
        self.sampling_temperature = sampling_temperature
        self.sampling_max_tokens = sampling_max_tokens
        self._service_client = service_client

    # -- lazy SDK wiring ---------------------------------------------------------

    def _get_service_client(self) -> Any:
        if self._service_client is None:
            import tinker

            self._service_client = tinker.ServiceClient()
        return self._service_client

    def _build_renderer(self, training_client: Any) -> Any:
        from tinker_cookbook.model_info import get_recommended_renderer_name
        from tinker_cookbook.renderers import get_renderer

        return get_renderer(get_recommended_renderer_name(self.base_model), training_client.get_tokenizer())

    # -- fit ---------------------------------------------------------------------

    def fit(self, dataset: Union[str, Path], *, train_on: TrainOn = TrainOn.LAST_ASSISTANT) -> TrainResult:
        """Train the pristine base on `dataset` and save weights for sampling.

        The dataset is validated before any paid call: a malformed file fails here, for
        free, rather than after the training client has been created.
        """
        from tinker import types
        from tinker_cookbook.renderers import TrainOnWhat

        path = Path(dataset)
        # The runtime gate, before anything is spent.
        validate_sft_jsonl(path)
        conversations = _read_conversations(path)
        dataset_digest = hashlib.sha256(path.read_bytes()).hexdigest()

        hyperparams: Dict[str, Any] = {
            "rank": self.rank,
            "learning_rate": self.learning_rate,
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "train_on": train_on.value,
        }

        training_client: Optional[Any] = None
        step_metrics: List[Dict[str, Any]] = []
        submitted_steps = 0

        try:
            service_client = self._get_service_client()
            training_client = service_client.create_lora_training_client(
                base_model=self.base_model,
                rank=self.rank,
                seed=TRAINING_SEED,
            )
            renderer = self._build_renderer(training_client)
            # The SDK's own default for train_on_what is ALL_ASSISTANT_MESSAGES -- the
            # inverse of ours -- so it is passed explicitly on every call, including
            # the default path.
            train_on_what = getattr(TrainOnWhat, _TRAIN_ON_WHAT[train_on])
            # Before the first paid step: skip rows truncation broke, refuse only an
            # empty batch.
            data = _trainable_data(conversations, renderer, train_on_what)

            telemetry_error: Optional[str] = None
            for _ in range(self.epochs):
                if telemetry_error:
                    break
                for start in range(0, len(data), self.batch_size):
                    batch = data[start : start + self.batch_size]
                    forward_backward = training_client.forward_backward(batch, "cross_entropy")
                    # Counted the moment paid work is submitted: a synchronous
                    # optim_step raise on step 1 must still leave a recovery save
                    # covering the forward/backward that was already paid for.
                    submitted_steps += 1
                    optim = training_client.optim_step(types.AdamParams(learning_rate=self.learning_rate))
                    result = forward_backward.result()
                    optim.result()
                    step: Dict[str, Any] = {"step": len(step_metrics) + 1, "mean_nll": None}
                    try:
                        step["mean_nll"] = _mean_nll(result.loss_fn_outputs, batch)
                    except Exception as exc:
                        # A loss reading that cannot be computed is a telemetry failure,
                        # not a training failure. Stop, but still checkpoint what the
                        # completed steps paid for rather than discarding them.
                        telemetry_error = (
                            f"loss telemetry after step {len(step_metrics) + 1}: {type(exc).__name__}: {exc}"
                        )
                    step_metrics.append(step)
                    if telemetry_error:
                        break

            ref = (
                training_client.save_weights_for_sampler(
                    name=f"agno-{dataset_digest[:12]}", ttl_seconds=CHECKPOINT_TTL_SECONDS
                )
                .result()
                .path
            )
            log_info(f"TinkerTrainer: saved checkpoint {ref}")
            if telemetry_error:
                log_warning(f"TinkerTrainer: {telemetry_error}")
            return TrainResult(
                checkpoint=Checkpoint(
                    ref=ref,
                    base_model=self.base_model,
                    dataset_digest=dataset_digest,
                    hyperparams=hyperparams,
                ),
                step_metrics=step_metrics,
                status=TrainStatus.PARTIAL if telemetry_error else TrainStatus.COMPLETED,
                error=telemetry_error,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc).strip() or 'no details'}"
            # Compute was already spent, so try to keep something for it. A recovery
            # checkpoint turns a total loss into a PARTIAL the caller can still measure.
            if training_client is not None and submitted_steps > 0:
                try:
                    ref = (
                        training_client.save_weights_for_sampler(
                            name=f"agno-{dataset_digest[:12]}-recovery", ttl_seconds=CHECKPOINT_TTL_SECONDS
                        )
                        .result()
                        .path
                    )
                    log_warning(f"TinkerTrainer: training failed ({error}); recovered checkpoint {ref}")
                    return TrainResult(
                        checkpoint=Checkpoint(
                            ref=ref,
                            base_model=self.base_model,
                            dataset_digest=dataset_digest,
                            hyperparams=hyperparams,
                        ),
                        step_metrics=step_metrics,
                        status=TrainStatus.PARTIAL,
                        error=error,
                    )
                except Exception as recovery_exc:
                    error = f"{error}; recovery checkpoint failed: {type(recovery_exc).__name__}: {recovery_exc}"
            return TrainResult(checkpoint=None, step_metrics=step_metrics, status=TrainStatus.FAILED, error=error)

    async def afit(self, dataset: Union[str, Path], *, train_on: TrainOn = TrainOn.LAST_ASSISTANT) -> TrainResult:
        """Async twin of `fit`. The training loop is blocking, so it runs off-thread."""
        return await asyncio.to_thread(self.fit, dataset, train_on=train_on)

    # -- serving -----------------------------------------------------------------

    def as_model(self, checkpoint: Checkpoint) -> Model:
        """Serve a tuned checkpoint. Sampling params match `base_as_model`'s, so the
        only difference between the two policies is the weights."""
        if checkpoint.base_model != self.base_model:
            raise ValueError(
                f"checkpoint was trained from base_model {checkpoint.base_model!r} but this trainer "
                f"serves {self.base_model!r}: serving it here would pick the wrong renderer and stamp "
                "a false policy identity. Serve it from a trainer built on its own base model."
            )
        return TinkerModel(
            base_model=self.base_model,
            model_path=checkpoint.ref,
            temperature=self.sampling_temperature,
            max_tokens=self.sampling_max_tokens,
            # Built here rather than lazily inside the model, so a trainer holding an
            # injected service client serves models that use it too.
            sampling_client=self._get_service_client().create_sampling_client(model_path=checkpoint.ref),
        )

    async def aas_model(self, checkpoint: Checkpoint) -> Model:
        # Serving builds a sampling client -- a network auth handshake -- so it runs
        # off-thread: dispatched inline it would freeze every concurrent rollout
        # coroutine for as long as that handshake hangs, before any engine timeout
        # can fire.
        return await asyncio.to_thread(self.as_model, checkpoint)

    def base_as_model(self) -> Model:
        """Serve the untuned base -- the baseline a tuned checkpoint is measured against."""
        return TinkerModel(
            base_model=self.base_model,
            temperature=self.sampling_temperature,
            max_tokens=self.sampling_max_tokens,
            sampling_client=self._get_service_client().create_sampling_client(base_model=self.base_model),
        )

    async def abase_as_model(self) -> Model:
        return await asyncio.to_thread(self.base_as_model)


def _read_conversations(path: Path) -> List[List[Dict[str, str]]]:
    """The validated file back into conversations.

    Split on "\\n" only, matching the canonical writer: splitlines() also breaks on
    U+2028/U+2029/U+0085, which json.dumps(ensure_ascii=False) emits unescaped.
    """
    conversations: List[List[Dict[str, str]]] = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        conversations.append(json.loads(line)["messages"])
    return conversations


def _trainable_data(conversations: List[List[Dict[str, str]]], renderer: Any, train_on_what: Any) -> List[Any]:
    """Render each conversation, skipping the rows truncation broke.

    Rendering truncates from the end at MAX_LENGTH, so a long conversation can lose
    part or all of the assistant turn it was supposed to teach: cut entirely, the row
    carries all-zero weights and no gradient; cut mid-answer, it keeps positive-weight
    prefix tokens and would train the model to stop mid-answer. Both are detected by
    rendering twice -- capped and uncapped -- and comparing lengths; a shortened row is
    skipped with a warning, mirroring the exporter's skip-not-abort. Only an empty
    surviving batch refuses the run, before the first paid step.
    """
    from tinker_cookbook.supervised.data import conversation_to_datum

    data: List[Any] = []
    skipped = 0
    for index, conversation in enumerate(conversations, start=1):
        capped = conversation_to_datum(conversation, renderer, max_length=MAX_LENGTH, train_on_what=train_on_what)
        weights = _tensor_values(capped.loss_fn_inputs.get("weights"))
        if not weights or any(not math.isfinite(weight) or weight < 0 for weight in weights):
            raise ValueError(f"conversation {index} produced invalid training weights")
        full = conversation_to_datum(conversation, renderer, max_length=None, train_on_what=train_on_what)
        full_weights = _tensor_values(full.loss_fn_inputs.get("weights"))
        if len(weights) < len(full_weights):
            skipped += 1
            log_warning(
                f"TinkerTrainer: conversation {index} renders past max_length={MAX_LENGTH}; "
                "its training target is cut or gone, so the row is skipped."
            )
            continue
        if not any(weight > 0 for weight in weights):
            raise ValueError(
                f"conversation {index} has no trainable target after rendering: "
                "its assistant turn carries no positive training weight"
            )
        data.append(capped)
    if not data:
        raise ValueError(
            f"no trainable conversation remains: all {skipped} of {len(conversations)} were cut by "
            f"max_length={MAX_LENGTH} rendering, so there is nothing to train on"
        )
    return data


def _tensor_values(tensor: Any) -> List[float]:
    """Unwrap a tinker TensorData, a numpy/torch tensor, or a plain sequence."""
    if tensor is None:
        return []
    values = tensor.data if hasattr(tensor, "data") else tensor
    if callable(values):
        values = values()
    if hasattr(values, "tolist"):
        values = values.tolist()
    return [float(value) for value in values]


def _mean_nll(loss_fn_outputs: List[Any], batch: List[Any]) -> float:
    """Weighted mean negative log-likelihood over a batch.

    Computed from per-token logprobs and the datum's own training weights rather than
    read off a summed loss metric: only the weights say which tokens carried loss, so a
    sum would silently average over the prompt as well as the target.
    """
    if len(loss_fn_outputs) != len(batch):
        raise ValueError("Tinker returned the wrong number of loss outputs")
    weighted_logprobs = 0.0
    total_weight = 0.0
    for output, datum in zip(loss_fn_outputs, batch):
        if "logprobs" not in output:
            raise ValueError("Tinker response is missing per-token logprobs")
        logprobs = _tensor_values(output["logprobs"])
        weights = _tensor_values(datum.loss_fn_inputs.get("weights"))
        if len(logprobs) != len(weights):
            raise ValueError("Tinker logprobs and training weights have different lengths")
        for logprob, weight in zip(logprobs, weights):
            if not math.isfinite(logprob) or not math.isfinite(weight):
                raise ValueError("Tinker returned non-finite loss data")
            weighted_logprobs += logprob * weight
            total_weight += weight
    if total_weight <= 0:
        raise ValueError("Cannot compute mean NLL without positive training weights")
    nll = -weighted_logprobs / total_weight
    if not math.isfinite(nll):
        raise ValueError("Tinker returned a non-finite mean NLL")
    return nll
