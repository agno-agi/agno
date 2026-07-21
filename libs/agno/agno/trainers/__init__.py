"""agno.trainers: turn an exported dataset into a model you can run.

A peer to `agno.models` and `agno.scorer`, and dependency-free in the same way -- the
protocol references only `agno.models.Model`. Adapters live alongside it
(`agno.trainers.tinker`) and are imported directly, never from here: the Tinker adapter
needs the `agno[tinker]` extra, and importing it eagerly would make this package
unimportable without it.
"""

from agno.trainers.base import Checkpoint, Trainer, TrainOn, TrainResult, TrainStatus

__all__ = [
    "Checkpoint",
    "TrainOn",
    "TrainResult",
    "TrainStatus",
    "Trainer",
]
