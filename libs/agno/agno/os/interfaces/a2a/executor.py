from typing import Any, List, Optional, Set, Union

try:
    from a2a.helpers import get_data_parts, new_task, new_text_part
    from a2a.server.agent_execution import AgentExecutor, RequestContext
    from a2a.server.events import EventQueue
    from a2a.server.tasks import TaskUpdater
    from a2a.types import InternalError, InvalidParamsError, Task, TaskState
    from a2a.types import Message as A2AMessage
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e


from agno.agent import Agent, RemoteAgent
from agno.agent.protocol import AgentProtocol
from agno.agents.base import BaseExternalAgent
from agno.os.interfaces.a2a.auth import resolve_a2a_user_id
from agno.os.interfaces.a2a.streaming import map_background_stream_to_run_events, stream_run_events_to_task
from agno.os.interfaces.a2a.task_store import A2ATaskStore
from agno.os.interfaces.a2a.utils import (
    map_a2a_message_to_run_input,
    map_paused_run_to_parts,
    restore_integers,
    send_run_output_to_task,
)
from agno.os.utils import get_agent_by_id, get_team_by_id, get_workflow_by_id
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error
from agno.workflow import RemoteWorkflow, Workflow


def _get_requirement_ids(data_parts: List[Any]) -> Set[str]:
    """Get the ids of the requirements carried by the data parts of a pause or continue message."""
    requirement_ids: Set[str] = set()
    for data in data_parts:
        if not isinstance(data, dict):
            continue
        for requirement in (data.get("requirements") or []) + (data.get("step_requirements") or []):
            if not isinstance(requirement, dict):
                continue
            # A tool requirement is known by its tool call, as it is for the run routes: a
            # client that rebuilds the requirement from the tool gives it a new id
            tool_execution = requirement.get("tool_execution")
            tool_call_id = tool_execution.get("tool_call_id") if isinstance(tool_execution, dict) else None
            requirement_ids.add(str(tool_call_id or requirement.get("id") or requirement.get("step_id")))
    return requirement_ids


class A2AExecutor(AgentExecutor):
    """Runs one Agno Agent, Team or Workflow for the A2A server, turning its run events into A2A task events."""

    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        agents: Optional[List[Union[Agent, RemoteAgent, AgentProtocol]]] = None,
        teams: Optional[List[Union[Team, RemoteTeam]]] = None,
        workflows: Optional[List[Union[Workflow, RemoteWorkflow]]] = None,
        task_store: Optional[A2ATaskStore] = None,
    ):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.task_store = task_store
        self.agents = agents
        self.teams = teams
        self.workflows = workflows

    def _get_entity(self) -> Any:
        """Get a fresh copy of the entity to run, as the run routes do per request."""
        entity: Any = None
        if self.entity_type == "agent":
            entity = get_agent_by_id(self.entity_id, self.agents, create_fresh=True)
        elif self.entity_type == "team":
            entity = get_team_by_id(self.entity_id, self.teams, create_fresh=True)
        elif self.entity_type == "workflow":
            entity = get_workflow_by_id(self.entity_id, self.workflows, create_fresh=True)
        if not entity:
            raise InternalError(message=f"{self.entity_type.capitalize()} not found")
        return entity

    def _runs_in_background(self, entity: Any) -> bool:
        """Whether the entity is run as a background run, which stores the run before it starts."""
        # A workflow gives its background run an id of its own, so the run could not be found by the task id
        if not isinstance(entity, (Agent, Team, BaseExternalAgent)):
            return False
        return getattr(entity, "db", None) is not None

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None or context.task_id is None or context.context_id is None:
            raise InvalidParamsError(message="A message is required")
        request = context.call_context.state.get("request")

        # 1. Get the entity to run
        entity = self._get_entity()

        # 2. Map the request to our run_input and run variables
        try:
            run_input = map_a2a_message_to_run_input(context.message)
        except ValueError as e:
            raise InvalidParamsError(message=str(e))
        # A2A must not take run identity from the client: X-User-ID / metadata.userId is
        # honoured for attribution only when the caller is anonymous (see resolve_run_user_id).
        user_id = None
        if request is not None:
            client_uid = str(context.message.metadata["userId"]) if "userId" in context.message.metadata else None
            user_id = resolve_a2a_user_id(request, client_uid)

        # 3. Continue the paused run if the message names an existing task
        # The task keeps the context it was created with: a message that names only the task
        # gets a new context id from the A2A server, which is not the session of the run.
        current_task = context.current_task
        if current_task is not None:
            updater = TaskUpdater(event_queue, current_task.id, current_task.context_id)
            await self._continue_task(entity, context.message, updater, current_task, user_id)
            return

        # 4. Create the task
        # The task shares its id with the Agno run, and its context with the session
        task = new_task(context.task_id, context.context_id, TaskState.TASK_STATE_SUBMITTED, history=[context.message])
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        # A background run is stored as soon as it starts, before the A2A server has saved the task
        if self.task_store is not None:
            self.task_store.expect_task(context.task_id)
        await event_queue.enqueue_event(task)

        # 5. Run the entity and stream its events into the task
        try:
            # An entity that stores its runs is run as a background run. The run is stored before
            # it starts, so the task can be read from any replica, and it outlives the request.
            if self._runs_in_background(entity):
                event_stream = map_background_stream_to_run_events(
                    entity.arun(
                        input=run_input.input_content,
                        images=run_input.images,
                        videos=run_input.videos,
                        audio=run_input.audios,
                        files=run_input.files,
                        session_id=context.context_id,
                        user_id=user_id,
                        run_id=context.task_id,
                        stream=True,
                        stream_events=True,
                        background=True,
                    ),
                    entity,
                    run_id=context.task_id,
                    session_id=context.context_id,
                )
            elif self.entity_type == "workflow":
                event_stream = entity.arun(
                    input=run_input.input_content,
                    images=list(run_input.images) if run_input.images else None,
                    videos=list(run_input.videos) if run_input.videos else None,
                    audio=list(run_input.audios) if run_input.audios else None,
                    files=list(run_input.files) if run_input.files else None,
                    session_id=context.context_id,
                    user_id=user_id,
                    run_id=context.task_id,
                    stream=True,
                    stream_events=True,
                )
            elif isinstance(entity, (RemoteAgent, RemoteTeam)):
                # The run lives on the remote, which assigns its own run id
                event_stream = entity.arun(
                    input=run_input.input_content,
                    images=run_input.images,
                    videos=run_input.videos,
                    audio=run_input.audios,
                    files=run_input.files,
                    session_id=context.context_id,
                    user_id=user_id,
                    stream=True,
                    stream_events=True,
                )
            else:
                event_stream = entity.arun(
                    input=run_input.input_content,
                    images=run_input.images,
                    videos=run_input.videos,
                    audio=run_input.audios,
                    files=run_input.files,
                    session_id=context.context_id,
                    user_id=user_id,
                    run_id=context.task_id,
                    stream=True,
                    stream_events=True,
                )

            paused_event = await stream_run_events_to_task(event_stream, updater, user_id=user_id)

            # A paused run leaves the task waiting for input. The requirements are read from
            # the stored run, which holds them for every kind of pause.
            if paused_event is not None:
                paused_run = None
                if hasattr(entity, "aget_run_output"):
                    paused_run = await entity.aget_run_output(run_id=context.task_id, session_id=context.context_id)
                await updater.update_status(
                    TaskState.TASK_STATE_INPUT_REQUIRED,
                    message=updater.new_agent_message(parts=map_paused_run_to_parts(paused_run or paused_event)),
                    metadata={"agno_event_type": "run_paused"},
                )

        # Handle any critical error
        except Exception as e:
            log_error(f"Error running {self.entity_type} {self.entity_id} over A2A: {str(e)}")
            await updater.failed(message=updater.new_agent_message(parts=[new_text_part(f"Error: {str(e)}")]))

    async def _continue_task(
        self, entity: Any, message: A2AMessage, updater: TaskUpdater, current_task: Task, user_id: Optional[str]
    ) -> None:
        """Continue the paused run of a task with the requirements the client resolved."""

        # Only a task waiting for input takes another message. A run that is still going
        # must not be started a second time under the same run id.
        if current_task.status.state != TaskState.TASK_STATE_INPUT_REQUIRED:
            return

        # The client sends the requirements back the way the pause sent them
        requirements = None
        for data in get_data_parts(message.parts):
            if isinstance(data, dict):
                requirements = data.get("requirements") or data.get("step_requirements") or requirements
        pending_data = get_data_parts(current_task.status.message.parts)

        # Without resolved requirements there is nothing to continue with: the task keeps waiting
        if not requirements:
            await updater.update_status(
                TaskState.TASK_STATE_INPUT_REQUIRED,
                message=current_task.status.message if current_task.status.HasField("message") else None,
                metadata={"agno_event_type": "run_paused"},
            )
            return

        # Requirements that are malformed, or that the task does not wait on, are refused, so a
        # stray payload cannot settle the run
        is_valid = isinstance(requirements, list) and all(isinstance(requirement, dict) for requirement in requirements)
        if not is_valid or not _get_requirement_ids([{"requirements": requirements}]) <= _get_requirement_ids(
            pending_data
        ):
            parts = [new_text_part("Error: the requirements sent are not the ones this task waits on")]
            parts.extend(part for part in current_task.status.message.parts if part.HasField("data"))
            await updater.update_status(
                TaskState.TASK_STATE_INPUT_REQUIRED,
                message=updater.new_agent_message(parts=parts),
                metadata={"agno_event_type": "run_paused"},
            )
            return

        try:
            from agno.os.services.runs import continue_paused_run

            run_output = await continue_paused_run(
                entity,
                run_id=current_task.id,
                session_id=current_task.context_id,
                user_id=user_id,
                requirements=restore_integers(requirements),
            )
            await send_run_output_to_task(run_output, updater, user_id=user_id)

        # A continue that is refused leaves the run paused, so the task keeps waiting
        except Exception as e:
            log_error(f"Error continuing {self.entity_type} {self.entity_id} over A2A: {str(e)}")
            parts = [new_text_part(f"Error: {str(e)}")]
            if current_task.status.HasField("message"):
                parts.extend(part for part in current_task.status.message.parts if part.HasField("data"))
            await updater.update_status(
                TaskState.TASK_STATE_INPUT_REQUIRED,
                message=updater.new_agent_message(parts=parts),
                metadata={"agno_event_type": "run_paused"},
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id is None or context.context_id is None:
            raise InvalidParamsError(message="Task ID is required")

        entity = self._get_entity()

        # cancel_run always stores cancellation intent (even for not-yet-registered runs
        # in cancel-before-start scenarios). The shared service also tombstones a
        # still-queued durable ticket first (parity with the REST cancel routes) - intent
        # alone does not stop a job no task is executing yet.
        from agno.os.services.runs import cancel_component_run

        await cancel_component_run(entity, context.task_id)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel(message=updater.new_agent_message(parts=[new_text_part("Run was cancelled")]))
