"""Result offloading: big tool results become AgentFS files, not messages."""

from agno.offload.store import ResultStore, result_id_for
from agno.offload.types import ResultMatch, ResultPage, ResultRef

__all__ = [
    "ResultMatch",
    "ResultPage",
    "ResultRef",
    "ResultStore",
    "result_id_for",
]
