from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel

from agno.run.agent import RunCompletedEvent, RunContentEvent, RunOutput
from agno.run.base import BaseRunOutputEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import TeamRunOutput


class StreamedContent:
    """Builds the content of a user-written generator from the items it yields.

    A generator that streams an agent or team run yields that run's content deltas. Once the
    run's result arrives, as its run output or its completed event, the result replaces the
    deltas streamed for that run and for the runs it started. Deltas are joined only for a run
    whose result never arrives.
    """

    def __init__(self) -> None:
        # Ordered pieces of content, each owned by a run id (None for items that are not run events)
        self._parts: List[List[Any]] = []
        self._parents: Dict[str, Optional[str]] = {}
        self._finished_runs: Set[str] = set()

    def add(self, item: Any) -> None:
        if isinstance(item, (RunOutput, TeamRunOutput)):
            self._set_result(item.run_id, item.content)
        elif isinstance(item, BaseRunOutputEvent):
            run_id = getattr(item, "run_id", None)
            if run_id is not None:
                self._parents.setdefault(run_id, getattr(item, "parent_run_id", None))
            if isinstance(item, (RunCompletedEvent, TeamRunCompletedEvent)):
                self._set_result(run_id, item.content)
            elif isinstance(item, (RunContentEvent, TeamRunContentEvent)) and item.content is not None:
                self._add_delta(run_id, item.content)
        elif isinstance(getattr(item, "content", None), str):
            self._parts.append([None, item.content])
        else:
            self._parts.append([None, str(item)])

    def get(self) -> Any:
        contents = [content for _, content in self._parts if content is not None]
        if len(contents) == 1:
            return contents[0]
        return "".join(content if isinstance(content, str) else str(content) for content in contents)

    def _belongs_to(self, run_id: Optional[str], ancestor_id: str) -> bool:
        seen: Set[str] = set()
        while run_id is not None and run_id not in seen:
            if run_id == ancestor_id:
                return True
            seen.add(run_id)
            run_id = self._parents.get(run_id)
        return False

    def _is_finished(self, run_id: Optional[str]) -> bool:
        return any(self._belongs_to(run_id, finished_id) for finished_id in self._finished_runs)

    def _add_delta(self, run_id: Optional[str], delta: Any) -> None:
        # A delta arriving after its run's result is already part of that result
        if self._is_finished(run_id):
            return
        if isinstance(delta, BaseModel):
            # Structured content arrives whole and replaces the text streamed before it
            self._parts = [part for part in self._parts if run_id is None or part[0] != run_id]
            self._parts.append([run_id, delta])
            return
        text = delta if isinstance(delta, str) else str(delta)
        last = self._parts[-1] if self._parts else None
        if last is not None and run_id is not None and last[0] == run_id and isinstance(last[1], str):
            last[1] += text
        else:
            self._parts.append([run_id, text])

    def _set_result(self, run_id: Optional[str], content: Any) -> None:
        if run_id is None:
            self._parts.append([None, content])
            return
        # The result stands where the run's first delta was streamed
        index = next((i for i, part in enumerate(self._parts) if self._belongs_to(part[0], run_id)), len(self._parts))
        self._parts = [part for part in self._parts if not self._belongs_to(part[0], run_id)]
        self._parts.insert(index, [run_id, content])
        self._finished_runs.add(run_id)
