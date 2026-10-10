from typing import Any, AsyncGenerator, Optional

from fastapi import Request

try:
    from a2a.auth.user import User
    from a2a.server.agent_execution import RequestContext, SimpleRequestContextBuilder
    from a2a.server.context import ServerCallContext
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import DefaultServerCallContextBuilder
    from a2a.server.tasks import TaskStore
    from a2a.types import (
        ContentTypeNotSupportedError,
        InvalidParamsError,
        PushNotificationNotSupportedError,
        Role,
        SendMessageRequest,
        SubscribeToTaskRequest,
        Task,
        TaskState,
        UnsupportedOperationError,
    )
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e


from agno.os.interfaces.a2a.utils import FINISHED_TASK_STATES, map_a2a_message_to_run_input
from agno.os.middleware.user_scope import resolve_run_user_id


class A2AUser(User):
    """The AgentOS caller of an A2A request, as the A2A server sees it."""

    def __init__(self, user_id: Optional[str] = None, is_authenticated: bool = False):
        self._user_id = user_id
        self._is_authenticated = is_authenticated

    @property
    def is_authenticated(self) -> bool:
        return self._is_authenticated

    @property
    def user_name(self) -> str:
        return self._user_id or ""


class A2ACallContextBuilder(DefaultServerCallContextBuilder):
    """Builds the A2A call context from the identity AgentOS resolved for the request."""

    def build(self, request: Request) -> ServerCallContext:
        call_context = super().build(request)
        # The request rides along so the executor and task store can apply the AgentOS
        # isolation and authorization rules, which live on request.state.
        call_context.state["request"] = request
        # A2A must not take run identity from the client: the client-supplied X-User-ID
        # header is honoured only when the caller is anonymous (see resolve_run_user_id).
        call_context.user = A2AUser(
            user_id=resolve_run_user_id(request, request.headers.get("X-User-ID")),
            is_authenticated=bool(getattr(request.state, "authenticated", False)),
        )
        return call_context


class A2ARequestContextBuilder(SimpleRequestContextBuilder):
    """Refuses a message the entity cannot run, before a task is created for it."""

    def __init__(self, task_store: TaskStore):
        super().__init__(task_store=task_store)
        self.task_store = task_store

    async def build(
        self,
        context: ServerCallContext,
        params: Optional[SendMessageRequest] = None,
        task_id: Optional[str] = None,
        context_id: Optional[str] = None,
        task: Optional[Task] = None,
    ) -> RequestContext:
        if params is not None:
            if params.message.role != Role.ROLE_USER:
                raise InvalidParamsError(message="Only user messages are accepted")

            # Push notifications are not served: a config sent with the message would be dropped silently
            if params.configuration.HasField("task_push_notification_config"):
                raise PushNotificationNotSupportedError()

            # Content the entity cannot take is refused here, not after a task was created for it
            try:
                map_a2a_message_to_run_input(params.message)
            except Exception:
                raise ContentTypeNotSupportedError(message="The message carries content that is not supported")

            # Only a task waiting for input takes another message
            if params.message.task_id:
                current_task = await self.task_store.get(params.message.task_id, context)
                if current_task is not None and current_task.status.state in (
                    TaskState.TASK_STATE_SUBMITTED,
                    TaskState.TASK_STATE_WORKING,
                ):
                    raise UnsupportedOperationError(
                        message=f"Task {current_task.id} is still running and takes no new message"
                    )
                # The A2A server refuses a finished task it holds. One rebuilt from a stored run is refused here.
                if current_task is not None and current_task.status.state in FINISHED_TASK_STATES:
                    raise UnsupportedOperationError(
                        message=f"Task {current_task.id} is in terminal state: "
                        f"{TaskState.Name(current_task.status.state)}"
                    )
                # A message that names only the task continues it in the context of that task
                if current_task is not None and not context_id:
                    context_id = current_task.context_id
        return await super().build(context, params, task_id, context_id, task)


class A2ARequestHandler(DefaultRequestHandler):
    """Refuses a subscription this process cannot serve, where its stream would never end."""

    async def on_subscribe_to_task(
        self, params: SubscribeToTaskRequest, context: ServerCallContext
    ) -> AsyncGenerator[Any, None]:
        # The events of a task are streamed by the process running it. A finished or unknown
        # task is left to the A2A server to answer.
        task_store: Any = self.task_store
        task = await task_store.get(params.id, context)
        if task is not None and task.status.state not in FINISHED_TASK_STATES and not task_store.holds_task(params.id):
            raise UnsupportedOperationError(
                message=f"Task {params.id} is not running on this server and cannot be subscribed to here"
            )
        async for event in super().on_subscribe_to_task(params, context):
            yield event
