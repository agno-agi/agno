from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set, Tuple, Union

try:
    from a2a.server.context import ServerCallContext
    from a2a.server.tasks import TaskStore
    from a2a.types import InvalidParamsError, ListTasksRequest, ListTasksResponse, Task, TaskState
    from a2a.utils.constants import DEFAULT_LIST_TASKS_PAGE_SIZE
    from a2a.utils.task import ListTasksCursor, decode_list_tasks_cursor, encode_list_tasks_cursor
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e


from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.interfaces.a2a.utils import FINISHED_TASK_STATES, map_run_output_to_a2a_task
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.remote.base import RemoteDb
from agno.run.base import RunStatus

_MAX_FINISHED_TASKS = 1000


def _copy_task(task: Task) -> Task:
    """Copy a task, so the stored task is never the object a caller goes on changing."""
    task_copy = Task()
    task_copy.CopyFrom(task)
    return task_copy


def _get_sort_key(task: Task) -> Tuple[bool, int, str]:
    """Get the position of a task in a listing: newest status first, then by id."""
    has_timestamp = task.status.HasField("timestamp")
    return (has_timestamp, task.status.timestamp.ToNanoseconds() if has_timestamp else 0, task.id)


class A2ATaskStore(TaskStore):
    """A2A TaskStore for one Agno Agent, Team or Workflow.

    A task is the A2A view of an Agno run and shares its id. Tasks are kept in memory
    while they are live; a task this process does not hold is rebuilt from the run the
    entity persisted, so reading it works after a restart or on another replica. A run
    that is stored only when it ends (a workflow, an entity without a database) cannot
    be read elsewhere until then.
    """

    def __init__(self, entity_type: str, entity: Any):
        self.entity_type = entity_type
        self.entity = entity
        self.entity_id: Optional[str] = getattr(entity, "id", None)
        self.db: Optional[Union[BaseDb, AsyncBaseDb, RemoteDb]] = getattr(entity, "db", None)
        # Tasks by id, each with its owner
        self._live_tasks: Dict[str, Tuple[str, Task]] = {}
        self._finished_tasks: "OrderedDict[str, Tuple[str, Task]]" = OrderedDict()
        # Tasks a request is creating right now. Their run is stored before the A2A server
        # saves the task, and must not be taken for a task that already exists.
        self._new_task_ids: Set[str] = set()

    def holds_task(self, task_id: str) -> bool:
        """Whether this process holds the task while it runs or waits, and so streams its events."""
        return task_id in self._live_tasks

    def expect_task(self, task_id: str) -> None:
        """Announce a task that is about to be created, so its stored run is not taken for it."""
        self._new_task_ids.add(task_id)

    def _get_scoped_user_id(self, context: ServerCallContext) -> Optional[str]:
        """Get the user the caller is scoped to, or None when the caller reads unfiltered."""
        request = context.state.get("request")
        if request is None:
            return context.user.user_name or None
        return get_scoped_user_id(request)

    async def save(self, task: Task, context: ServerCallContext) -> None:
        task = _copy_task(task)
        self._new_task_ids.discard(task.id)
        # A task keeps the owner it was created with: an admin acting on it must not take it over
        stored = self._live_tasks.get(task.id) or self._finished_tasks.get(task.id)
        run_output = None
        if stored is not None:
            owner = stored[0]
        else:
            # A task this process does not hold yet belongs to the user of its stored run, if it has one
            run_output = await self._get_run(task.id)
            owner = getattr(run_output, "user_id", None) or context.user.user_name

        # The A2A server cancels a task it is not running itself (a paused one, one running on
        # another replica, a run started outside A2A) by saving it as canceled. Store the
        # cancellation intent for the run, so it stops wherever it is. A task running here
        # is cancelled through the executor, or ended cancelled on its own.
        if task.status.state == TaskState.TASK_STATE_CANCELED and task.id not in self._finished_tasks:
            live_task = self._live_tasks.get(task.id)
            if live_task is None or live_task[1].status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
                from agno.os.services.runs import cancel_component_run

                await cancel_component_run(self.entity, task.id)
                await self._cancel_paused_run(task.id)

                # A stored run is the same on every replica, and another replica may still move it on.
                # The canceled task is not kept here: it is read back from the stored run.
                if await self._get_run(task.id) is not None:
                    self._live_tasks.pop(task.id, None)
                    return

        if task.status.state in FINISHED_TASK_STATES:
            self._live_tasks.pop(task.id, None)
            self._finished_tasks[task.id] = (owner, task)
            self._finished_tasks.move_to_end(task.id)
            while len(self._finished_tasks) > _MAX_FINISHED_TASKS:
                self._finished_tasks.popitem(last=False)
        else:
            self._live_tasks[task.id] = (owner, task)

    async def get(self, task_id: str, context: ServerCallContext) -> Optional[Task]:
        # A scoped caller may only reach its own tasks; admins and unscoped callers
        # read unfiltered, matching the REST run-read route.
        scoped_user_id = self._get_scoped_user_id(context)

        stored = self._live_tasks.get(task_id) or self._finished_tasks.get(task_id)

        # A task waiting for input can be continued on another replica. Its stored run then
        # moves on while the copy kept here still waits, so the stored run is checked.
        if stored is not None and stored[1].status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
            run_output = await self._get_run(task_id)
            if run_output is not None and run_output.status != RunStatus.paused:
                self._live_tasks.pop(task_id, None)
                stored = None

        if stored is not None:
            owner, task = stored
            if scoped_user_id is not None and owner != scoped_user_id:
                return None
            return _copy_task(task)

        if task_id in self._new_task_ids:
            return None
        return await self._get_task_from_run(task_id, scoped_user_id)

    async def _get_run(self, task_id: str) -> Optional[Any]:
        """Get the run the entity persisted for a task, pinned to this entity."""
        # A remote entity's runs are stored by the AgentOS it runs on
        if self.db is None or isinstance(self.db, RemoteDb):
            return None
        run_output: Any
        if isinstance(self.db, AsyncBaseDb):
            run_output = await self.db.get_run(run_id=task_id)
        else:
            run_output = self.db.get_run(run_id=task_id)
        if run_output is None or isinstance(run_output, dict):
            return None
        if getattr(run_output, f"{self.entity_type}_id", None) != self.entity_id:
            return None
        return run_output

    async def _cancel_paused_run(self, task_id: str) -> None:
        """Mark the stored run of a paused task as cancelled, so every replica reads the task as canceled."""
        # A paused run is not running anywhere, so nothing else acts on the cancellation intent
        run_output = await self._get_run(task_id)
        if run_output is None or run_output.status != RunStatus.paused:
            return
        run_output.status = RunStatus.cancelled
        if isinstance(self.db, AsyncBaseDb):
            await self.db.upsert_run(run_output, session_id=run_output.session_id, user_id=run_output.user_id)
        elif isinstance(self.db, BaseDb):
            self.db.upsert_run(run_output, session_id=run_output.session_id, user_id=run_output.user_id)

    async def _get_runs(self, scoped_user_id: Optional[str], session_id: Optional[str]) -> List[Any]:
        """Get the runs the entity persisted, newest first, pinned to this entity and the caller."""
        if self.db is None or isinstance(self.db, RemoteDb):
            return []
        filters: Dict[str, Any] = {
            f"{self.entity_type}_id": self.entity_id,
            "user_id": scoped_user_id,
            "session_id": session_id,
            "limit": _MAX_FINISHED_TASKS,
            "sort_by": "created_at",
            "sort_order": "desc",
        }
        run_outputs: Any
        if isinstance(self.db, AsyncBaseDb):
            run_outputs = await self.db.get_runs(**filters)
        else:
            run_outputs = self.db.get_runs(**filters)
        # Checked again here: a run of another entity or user must never be listed, whatever the adapter returns
        return [
            run_output
            for run_output in run_outputs
            if not isinstance(run_output, dict)
            and getattr(run_output, f"{self.entity_type}_id", None) == self.entity_id
            and (scoped_user_id is None or getattr(run_output, "user_id", None) == scoped_user_id)
        ]

    async def _get_task_from_run(self, task_id: str, scoped_user_id: Optional[str]) -> Optional[Task]:
        """Rebuild a task from the run the entity persisted, pinned to this entity and the caller."""
        run_output = await self._get_run(task_id)
        if run_output is None:
            return None
        if scoped_user_id is not None and getattr(run_output, "user_id", None) != scoped_user_id:
            return None
        return map_run_output_to_a2a_task(run_output)

    async def list(self, params: ListTasksRequest, context: ServerCallContext) -> ListTasksResponse:
        scoped_user_id = self._get_scoped_user_id(context)

        # Stored runs are the same on every replica. A task held here is added when it has no stored run yet.
        candidate_tasks = [
            map_run_output_to_a2a_task(run_output)
            for run_output in await self._get_runs(scoped_user_id, params.context_id or None)
        ]
        stored_task_ids = {task.id for task in candidate_tasks}
        for owner, task in list(self._live_tasks.values()) + list(self._finished_tasks.values()):
            if task.id in stored_task_ids:
                continue
            if scoped_user_id is not None and owner != scoped_user_id:
                continue
            candidate_tasks.append(task)

        # Filter tasks
        tasks = []
        for task in candidate_tasks:
            if params.context_id and task.context_id != params.context_id:
                continue
            if params.status and task.status.state != params.status:
                continue
            if params.HasField("status_timestamp_after") and not (
                task.status.HasField("timestamp")
                and task.status.timestamp.ToNanoseconds() >= params.status_timestamp_after.ToNanoseconds()
            ):
                continue
            tasks.append(task)

        # Order tasks by last update time, newest first
        tasks.sort(key=_get_sort_key, reverse=True)

        # Paginate tasks. The page token carries the position of the last task returned.
        total_size = len(tasks)
        start_idx = 0
        if params.page_token:
            cursor = decode_list_tasks_cursor(params.page_token)
            if cursor is None:
                raise InvalidParamsError(message="Invalid page token")
            start_idx = next(
                (idx for idx, task in enumerate(tasks) if _get_sort_key(task) < cursor.sort_key()), total_size
            )
        page_size = params.page_size or DEFAULT_LIST_TASKS_PAGE_SIZE
        end_idx = start_idx + page_size
        next_page_token = None
        if end_idx < total_size:
            has_timestamp, timestamp_ns, task_id = _get_sort_key(tasks[end_idx - 1])
            next_page_token = encode_list_tasks_cursor(
                ListTasksCursor(timestamp_ns=timestamp_ns if has_timestamp else None, task_id=task_id)
            )

        return ListTasksResponse(
            tasks=[_copy_task(task) for task in tasks[start_idx:end_idx]],
            next_page_token=next_page_token,
            total_size=total_size,
            page_size=page_size,
        )

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        if await self.get(task_id, context) is None:
            return
        self._live_tasks.pop(task_id, None)
        self._finished_tasks.pop(task_id, None)
