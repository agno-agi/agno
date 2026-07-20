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

# rl-tutor's MAX_STEPS=40 planning cap is deliberately NOT copied: the dataset
# validator's caps are the gate here, and at batch_size=8 / epochs=2 a full 320-row
# export is a legitimate fit that must not be refused.

_TRAIN_ON_WHAT = {
    TrainOn.LAST_ASSISTANT: "LAST_ASSISTANT_MESSAGE",
    TrainOn.ALL_ASSISTANT: "ALL_ASSISTANT_MESSAGES",
}


class TinkerTrainer:
    """A `Trainer` backed by the Tinker training and sampling APIs.

    Checkpoint refs are not durable -- Tinker expires them on the platform's retention
    schedule (days, not months). The reproducible provenance is the dataset file plus
    the `dataset_digest` and `hyperparams` on the returned `Checkpoint`; `ref` only
    re-samples while it lives.
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
        from tinker_cookbook.supervised.data import conversation_to_datum

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
            data = [
                conversation_to_datum(
                    conversation,
                    renderer,
                    max_length=MAX_LENGTH,
                    train_on_what=train_on_what,
                )
                for conversation in conversations
            ]

            for _ in range(self.epochs):
                for start in range(0, len(data), self.batch_size):
                    batch = data[start : start + self.batch_size]
                    forward_backward = training_client.forward_backward(batch, "cross_entropy")
                    optim = training_client.optim_step(types.AdamParams(learning_rate=self.learning_rate))
                    submitted_steps += 1
                    result = forward_backward.result()
                    optim.result()
                    step_metrics.append(
                        {
                            "step": len(step_metrics) + 1,
                            "mean_nll": _mean_nll(result.loss_fn_outputs, batch),
                        }
                    )

            ref = training_client.save_weights_for_sampler(name=f"agno-{dataset_digest[:12]}").result().path
            log_info(f"TinkerTrainer: saved checkpoint {ref}")
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
            error = f"{type(exc).__name__}: {str(exc).strip() or 'no details'}"
            # Compute was already spent, so try to keep something for it. A recovery
            # checkpoint turns a total loss into a PARTIAL the caller can still measure.
            if training_client is not None and submitted_steps > 0:
                try:
                    ref = (
                        training_client.save_weights_for_sampler(name=f"agno-{dataset_digest[:12]}-recovery")
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
        return TinkerModel(
            base_model=self.base_model,
            model_path=checkpoint.ref,
            temperature=self.sampling_temperature,
            max_tokens=self.sampling_max_tokens,
        )

    async def aas_model(self, checkpoint: Checkpoint) -> Model:
        return self.as_model(checkpoint)

    def base_as_model(self) -> Model:
        """Serve the untuned base -- the baseline a tuned checkpoint is measured against."""
        return TinkerModel(
            base_model=self.base_model,
            temperature=self.sampling_temperature,
            max_tokens=self.sampling_max_tokens,
        )

    async def abase_as_model(self) -> Model:
        return self.base_as_model()


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
