from functools import cached_property
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Literal, Optional, Union, overload

from fastapi import WebSocket
from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.remote.base import BaseRemote, RemoteDb
from agno.run.workflow import WorkflowRunOutput, WorkflowRunOutputEvent
from agno.utils.agent import validate_input
from agno.utils.remote import serialize_input

if TYPE_CHECKING:
    from agno.os.routers.workflows.schema import WorkflowResponse


class RemoteWorkflow(BaseRemote):
    def __init__(
        self,
        base_url: str,
        workflow_id: str,
        timeout: float = 300.0,
    ):
        """Initialize AgentOSRunner for local or remote execution.

        For remote execution, provide base_url and workflow_id.

        Args:
            base_url: Base URL for remote AgentOS instance (e.g., "http://localhost:7777")
            workflow_id: ID of remote workflow
            timeout: Request timeout in seconds (default: 300)
        """
        super().__init__(base_url, timeout)
        self.workflow_id = workflow_id

    @property
    def id(self) -> str:
        return self.workflow_id

    async def get_workflow_config(self) -> "WorkflowResponse":
        """Get the workflow config from remote, cached after first access."""
        return await self.client.aget_workflow(self.workflow_id)

    @cached_property
    def _workflow_config(self) -> Optional[Any]:
        """Get the workflow config from remote, cached after first access."""
        from agno.os.routers.workflows.schema import WorkflowResponse

        config: WorkflowResponse = self.client.get_workflow(self.workflow_id)
        return config

    @cached_property
    def name(self) -> str:
        if self._workflow_config is not None:
            return self._workflow_config.name
        return self.workflow_id

    @cached_property
    def description(self) -> str:
        if self._workflow_config is not None:
            return self._workflow_config.description
        return ""

    @cached_property
    def db(self) -> Optional[RemoteDb]:
        if self._workflow_config is not None and self._workflow_config.db_id is not None:
            config = self._config
            db_id = self._workflow_config.db_id
            session_table_name = None
            knowledge_table_name = None
            memory_table_name = None
            metrics_table_name = None
            eval_table_name = None
            traces_table_name = None
            if config and config.session:
                session_dbs = [db for db in config.session.dbs if db.db_id == db_id]
                session_table_name = session_dbs[0].tables[0] if session_dbs and session_dbs[0].tables else None
            if config and config.knowledge:
                knowledge_dbs = [db for db in config.knowledge.dbs if db.db_id == db_id]
                knowledge_table_name = knowledge_dbs[0].tables[0] if knowledge_dbs and knowledge_dbs[0].tables else None
            if config and config.memory:
                memory_dbs = [db for db in config.memory.dbs if db.db_id == db_id]
                memory_table_name = memory_dbs[0].tables[0] if memory_dbs and memory_dbs[0].tables else None
            if config and config.metrics:
                metrics_dbs = [db for db in config.metrics.dbs if db.db_id == db_id]
                metrics_table_name = metrics_dbs[0].tables[0] if metrics_dbs and metrics_dbs[0].tables else None
            if config and config.evals:
                eval_dbs = [db for db in config.evals.dbs if db.db_id == db_id]
                eval_table_name = eval_dbs[0].tables[0] if eval_dbs and eval_dbs[0].tables else None
            if config and config.traces:
                traces_dbs = [db for db in config.traces.dbs if db.db_id == db_id]
                traces_table_name = traces_dbs[0].tables[0] if traces_dbs and traces_dbs[0].tables else None
            return RemoteDb(
                id=db_id,
                client=self.client,
                session_table_name=session_table_name,
                knowledge_table_name=knowledge_table_name,
                memory_table_name=memory_table_name,
                metrics_table_name=metrics_table_name,
                eval_table_name=eval_table_name,
                traces_table_name=traces_table_name,
            )
        return None

    @overload
    async def arun(
        self,
        input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]]] = None,
        additional_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
        stream: Literal[False] = False,
        stream_events: Optional[bool] = None,
        stream_intermediate_steps: Optional[bool] = None,
        background: Optional[bool] = False,
        websocket: Optional[WebSocket] = None,
        background_tasks: Optional[Any] = None,
    ) -> WorkflowRunOutput: ...

    @overload
    def arun(
        self,
        input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]]] = None,
        additional_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
        stream: Literal[True] = True,
        stream_events: Optional[bool] = None,
        stream_intermediate_steps: Optional[bool] = None,
        background: Optional[bool] = False,
        websocket: Optional[WebSocket] = None,
        background_tasks: Optional[Any] = None,
    ) -> AsyncIterator[WorkflowRunOutputEvent]: ...

    def arun(  # type: ignore
        self,
        input: Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]],
        additional_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
        stream: bool = False,
        stream_events: Optional[bool] = None,
        background: Optional[bool] = False,
        websocket: Optional[WebSocket] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> Union[WorkflowRunOutput, AsyncIterator[WorkflowRunOutputEvent]]:
        # TODO: Deal with background
        validated_input = validate_input(input)
        serialized_input = serialize_input(validated_input)

        if stream:
            # Handle streaming response
            return self.get_client().run_workflow_stream(
                workflow_id=self.workflow_id,
                message=serialized_input,
                additional_data=additional_data,
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                audio=audio,
                images=images,
                videos=videos,
                files=files,
                session_state=session_state,
                stream_events=stream_events,
                **kwargs,
            )
        else:
            return self.get_client().run_workflow(
                workflow_id=self.workflow_id,
                message=serialized_input,
                additional_data=additional_data,
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                audio=audio,
                images=images,
                videos=videos,
                files=files,
                session_state=session_state,
                **kwargs,
            )

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel a running workflow execution.

        Args:
            run_id (str): The run_id to cancel.

        Returns:
            bool: True if the run was found and marked for cancellation, False otherwise.
        """
        return await self.get_client().cancel_workflow_run(
            workflow_id=self.workflow_id,
            run_id=run_id,
        )
