"""The trainer abstraction: a dataset in, a servable model out.

`Trainer` is the bring-your-own-trainer seam. It is deliberately general -- a dataset
path and some hyperparameters go in, a `Checkpoint` comes back, and the trainer serves
both that checkpoint and its own untuned base as `agno.models.Model`s. Nothing here
knows about environments, rollouts or scoring; the dependency direction is one-way,
`agno.models` <- `agno.trainers` <- `agno.environments`, so a trainer adapter never
imports the layer that calls it.

Both faces matter. `fit` is the training half; `as_model` / `base_as_model` are the
sampling half, and without them a tuned checkpoint is a receipt rather than something
you can measure. `base_as_model` in particular exists so a caller can measure its
baseline against the model it is about to train -- comparing a tuned checkpoint against
some other model is not a before/after.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Union, runtime_checkable

from agno.models.base import Model


class TrainOn(str, Enum):
    """Which assistant turns carry loss."""

    LAST_ASSISTANT = "last_assistant"  # single-turn SFT: train on the final assistant turn only
    ALL_ASSISTANT = "all_assistant"  # multi-turn: train on every assistant turn


class TrainStatus(str, Enum):
    """How a training run ended."""

    COMPLETED = "completed"
    PARTIAL = "partial"  # failed mid-run, but a paid checkpoint was preserved
    FAILED = "failed"


@dataclass(frozen=True, eq=False)
class Checkpoint:
    """A trained artifact and the provenance that explains it.

    `eq=False` for the same reason `Task` documents it: `hyperparams` is a mapping, and
    the `__hash__` a frozen dataclass would generate raises the first time one of these
    sits in a set.

    Checkpoint refs are not durable. Training platforms expire them (Tinker's retention
    is days, not months), so the reproducible provenance is the dataset file plus
    `dataset_digest` and `hyperparams` -- `ref` only re-samples while it lives.
    """

    ref: str  # opaque handle, e.g. "tinker://..."
    base_model: str
    dataset_digest: str  # sha256 of the training file
    # What the adapter trained with. agno's own trainers write exactly
    # {"rank", "learning_rate", "epochs", "batch_size", "train_on"}; a third-party
    # trainer records its own knobs, so the keys are documented, not enforced.
    hyperparams: Dict[str, Any]


@dataclass
class TrainResult:
    """The outcome of one `fit`, including what it cost when it failed.

    `step_metrics` is the loss curve -- one `{"step": int, "mean_nll": float}` per
    optimizer step. It is on the result rather than behind a callback so a caller reads
    training telemetry without re-implementing the loop.

    A mid-run failure that had already spent compute returns `PARTIAL` with the
    recovery checkpoint rather than `FAILED` with nothing: paid compute is never
    silently discarded.
    """

    checkpoint: Optional[Checkpoint]  # None only if nothing was saved
    step_metrics: List[Dict[str, Any]]
    status: TrainStatus
    error: Optional[str] = None


@runtime_checkable
class Trainer(Protocol):
    """Train a dataset into a checkpoint, and serve checkpoints as models.

    All six methods are protocol members, so `isinstance(x, Trainer)` fails on a
    half-implemented adapter rather than at the first call site that needs the missing
    half.

    `fit` always trains from the pristine base -- there is no resume-from-checkpoint
    seam. Multi-round training stays sound by growing the dataset instead (see
    `agno.environments.ImprovementLoop`), which is what keeps a later round from
    forgetting what an earlier one taught.

    Consent is the caller's. `fit` trains when called; it does not gate spend,
    authorize, or retry a paid run. That policy belongs to whoever holds the budget.
    """

    def fit(self, dataset: Union[str, Path], *, train_on: TrainOn = TrainOn.LAST_ASSISTANT) -> TrainResult: ...

    async def afit(self, dataset: Union[str, Path], *, train_on: TrainOn = TrainOn.LAST_ASSISTANT) -> TrainResult: ...

    def as_model(self, checkpoint: Checkpoint) -> Model:
        """Serve a tuned checkpoint as a model."""
        ...

    async def aas_model(self, checkpoint: Checkpoint) -> Model: ...

    def base_as_model(self) -> Model:
        """Serve the untuned base as a model -- the baseline for a before/after."""
        ...

    async def abase_as_model(self) -> Model: ...
