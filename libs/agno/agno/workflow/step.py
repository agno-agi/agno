from __future__ import annotations

import contextvars
import inspect
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union, cast
from uuid import uuid4

from pydantic import BaseModel
from typing_extensions import TypeGuard

from agno.agent import Agent
from agno.db.base import BaseDb
from agno.media import Audio, Image, Video
from agno.models.message import Message
from agno.models.metrics import RunMetrics
from agno.registry import Registry
from agno.run import RunContext
from agno.run.agent import RunContentEvent, RunOutput
from agno.run.base import BaseRunOutputEvent, RunStatus
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import TeamRunOutput
from agno.run.workflow import (
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
)
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession
from agno.team import Team
from agno.utils.log import log_debug, log_warning, logger, use_agent_logger, use_team_logger, use_workflow_logger
from agno.utils.merge_dict import merge_dictionaries
from agno.workflow.types import (
    ErrorRequirement,
    ExecutorType,
    HumanReview,
    OnError,
    OnReject,
    OnTimeout,
    StepInput,
    StepOutput,
    StepRequirement,
    StepType,
    UserInputField,
)

if TYPE_CHECKING:
    from agno.workflow.workflow import Workflow

# Maximum nesting depth for nested workflow execution to prevent circular references or stack overflow.
_MAX_NESTED_WORKFLOW_DEPTH = 10
# Use ContextVar instead of threading.local so depth is isolated per coroutine/task,
# not per thread. This prevents concurrent async workflows from interfering with each other.
_nested_workflow_depth: contextvars.ContextVar[int] = contextvars.ContextVar("_nested_workflow_depth", default=0)

StepExecutor = Callable[
    [StepInput],
    Union[
        StepOutput,
        Iterator[StepOutput],
        Iterator[Any],
        Awaitable[StepOutput],
        Awaitable[Any],
        AsyncIterator[StepOutput],
        AsyncIterator[Any],
    ],
]


@dataclass
class Step:
    """A single unit of work in a workflow pipeline"""

    name: Optional[str] = None

    # Executor options - only one should be provided
    agent: Optional[Agent] = None
    team: Optional[Team] = None
    executor: Optional[StepExecutor] = None
    workflow: Optional["Workflow"] = None  # Nested workflow support

    step_id: Optional[str] = None
    description: Optional[str] = None

    # Step configuration
    max_retries: int = 3

    skip_on_failure: bool = False

    # Input validation mode
    # If False, only warn about missing inputs
    strict_input_validation: bool = False

    add_workflow_history: Optional[bool] = None
    num_history_runs: int = 3

    # Human-in-the-loop (HITL) configuration
    # If True, the step will pause before execution and require user confirmation
    requires_confirmation: bool = False
    # Message to display to the user when requesting confirmation
    confirmation_message: Optional[str] = None
    # What to do when step is rejected: OnReject.skip (skip step, continue workflow) or OnReject.cancel (cancel workflow)
    on_reject: Union[OnReject, str] = OnReject.skip
    # If True, the step will pause before execution and require user input
    requires_user_input: bool = False
    # Message to display to the user when requesting input
    user_input_message: Optional[str] = None
    # Schema for user input fields (list of dicts with name, field_type, description, required)
    user_input_schema: Optional[List[Dict[str, Any]]] = None
    # What to do when step encounters an error: OnError.fail (default), OnError.skip, OnError.pause (HITL)
    # OnError.pause triggers HITL allowing user to retry or skip the failed step
    on_error: Union[OnError, str] = OnError.skip

    # Post-execution output review: pause after the step runs so a human can review the output
    # Can be a bool or a callable that receives StepOutput and returns bool (conditional review)
    requires_output_review: Union[bool, Callable[["StepOutput"], bool]] = False
    # Message to display to the reviewer when output review is requested
    output_review_message: Optional[str] = None

    # Maximum number of HITL retry attempts (applies when on_reject=OnReject.retry)
    hitl_max_retries: int = 3

    # Timeout for HITL responses in seconds (None = wait indefinitely)
    hitl_timeout: Optional[int] = None
    # Action when timeout expires: "cancel", "skip", or "approve"
    on_timeout: Union[OnTimeout, str] = OnTimeout.cancel

    _retry_count: int = 0

    def __init__(
        self,
        name: Optional[str] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
        executor: Optional[StepExecutor] = None,
        workflow: Optional["Workflow"] = None,
        step_id: Optional[str] = None,
        description: Optional[str] = None,
        max_retries: int = 3,
        skip_on_failure: bool = False,
        strict_input_validation: bool = False,
        add_workflow_history: Optional[bool] = None,
        num_history_runs: int = 3,
        requires_confirmation: bool = False,
        confirmation_message: Optional[str] = None,
        on_reject: Union[OnReject, str] = OnReject.skip,
        requires_user_input: bool = False,
        user_input_message: Optional[str] = None,
        user_input_schema: Optional[List[Dict[str, Any]]] = None,
        on_error: Union[OnError, str] = OnError.skip,
        requires_output_review: Union[bool, Callable[["StepOutput"], bool]] = False,
        output_review_message: Optional[str] = None,
        hitl_max_retries: int = 3,
        hitl_timeout: Optional[int] = None,
        on_timeout: Union[OnTimeout, str] = OnTimeout.cancel,
        human_review: Optional[HumanReview] = None,
    ):
        # Auto-detect HITL metadata from @hitl decorator on executor function
        if executor is not None:
            from agno.workflow.decorators import get_pause_metadata

            hitl_metadata = get_pause_metadata(executor)
            if hitl_metadata:
                # Use decorator values as defaults, but allow explicit params to override
                if name is None and hitl_metadata.get("name"):
                    name = hitl_metadata["name"]
                if not requires_confirmation and hitl_metadata.get("requires_confirmation"):
                    requires_confirmation = hitl_metadata["requires_confirmation"]
                if confirmation_message is None and hitl_metadata.get("confirmation_message"):
                    confirmation_message = hitl_metadata["confirmation_message"]
                if not requires_user_input and hitl_metadata.get("requires_user_input"):
                    requires_user_input = hitl_metadata["requires_user_input"]
                if user_input_message is None and hitl_metadata.get("user_input_message"):
                    user_input_message = hitl_metadata["user_input_message"]
                if user_input_schema is None and hitl_metadata.get("user_input_schema"):
                    user_input_schema = hitl_metadata["user_input_schema"]

        # Auto-detect name for function executors if not provided
        if name is None and executor is not None:
            name = getattr(executor, "__name__", None)

        self.name = name
        self.agent = agent
        self.team = team
        self.executor = executor
        self.workflow = workflow

        # Validate executor configuration
        self._validate_executor_config()

        self.step_id = step_id
        self.description = description
        self.max_retries = max_retries
        self.skip_on_failure = skip_on_failure
        self.strict_input_validation = strict_input_validation
        self.add_workflow_history = add_workflow_history
        self.num_history_runs = num_history_runs
        # Build HITL config - explicit hitl= takes priority over flat params
        if human_review is not None:
            self.human_review = human_review
        else:
            self.human_review = HumanReview(
                requires_confirmation=requires_confirmation,
                confirmation_message=confirmation_message,
                requires_user_input=requires_user_input,
                user_input_message=user_input_message,
                user_input_schema=user_input_schema,
                requires_output_review=requires_output_review,
                output_review_message=output_review_message,
                on_reject=on_reject,
                on_error=on_error,
                max_retries=hitl_max_retries,
                timeout=hitl_timeout,
                on_timeout=on_timeout,
            )

        # Validate HumanReview config for Step
        from agno.workflow.types import validate_human_review_for_step

        validate_human_review_for_step(self.human_review)

        # Store HITL fields as attributes for backward compatibility
        # These read from self.human_review so there's one source of truth
        self.requires_confirmation = self.human_review.requires_confirmation
        self.confirmation_message = self.human_review.confirmation_message
        self.on_reject = self.human_review.on_reject
        self.requires_user_input = self.human_review.requires_user_input
        self.user_input_message = self.human_review.user_input_message
        self.user_input_schema = self.human_review.user_input_schema
        self.on_error = self.human_review.on_error
        self.requires_output_review = self.human_review.requires_output_review
        self.output_review_message = self.human_review.output_review_message
        self.hitl_max_retries = self.human_review.max_retries
        self.hitl_timeout = self.human_review.timeout
        self.on_timeout = self.human_review.on_timeout
        self.step_id = step_id

        if step_id is None:
            self.step_id = str(uuid4())

        # Set the active executor
        self._set_active_executor()

    def to_dict(self) -> Dict[str, Any]:
        """Convert step to a dictionary representation."""
        result = {
            "type": "Step",
            "name": self.name,
            "step_id": self.step_id,
            "description": self.description,
            "max_retries": self.max_retries,
            "skip_on_failure": self.skip_on_failure,
            "strict_input_validation": self.strict_input_validation,
            "add_workflow_history": self.add_workflow_history,
            "num_history_runs": self.num_history_runs,
            "human_review": self.human_review.to_dict(),
        }

        if self.agent is not None:
            result["agent_id"] = self.agent.id
        if self.team is not None:
            result["team_id"] = self.team.id
        if self.workflow is not None:
            result["workflow_id"] = self.workflow.id
        if self.executor is not None:
            result["executor_ref"] = self.executor.__name__

        return result

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        registry: Optional[Registry] = None,
        db: Optional["BaseDb"] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> "Step":
        """
        Create a Step from a dictionary.

        Args:
            data: Dictionary containing step configuration
            registry: Optional registry for rehydrating non-serializable objects
            db: Optional database for loading agents/teams in steps
            links: Optional links for this step version

        Returns:
            Step: Reconstructed step instance
        """
        config = data.copy()

        agent = None
        team = None
        executor = None
        workflow = None

        # --- Handle Agent reconstruction ---
        if "agent_id" in config and config["agent_id"]:
            agent_id = config.get("agent_id")

            # First try registry (code-defined agents)
            if registry and agent_id:
                registry_agent = registry.get_agent(agent_id)
                if registry_agent is not None:
                    try:
                        # Deep copy to isolate mutable state between concurrent requests
                        agent = registry_agent.deep_copy()
                    except Exception as e:
                        log_warning(
                            f"deep_copy() failed for registry agent '{agent_id}', using shared instance: {e}",
                        )

                        agent = registry_agent

            # Fall back to database
            if agent is None and db is not None and agent_id is not None:
                from agno.agent.agent import get_agent_by_id

                agent = get_agent_by_id(db=db, id=agent_id, registry=registry)

            if agent is None and agent_id:
                log_warning(
                    f"Could not resolve agent_id='{agent_id}' from registry or DB for step '{config.get('name')}'"
                )

        # --- Handle Team reconstruction ---
        if "team_id" in config and config["team_id"]:
            team_id = config.get("team_id")

            # First try registry (code-defined teams)
            if registry and team_id:
                registry_team = registry.get_team(team_id)
                if registry_team is not None:
                    try:
                        # Deep copy to isolate mutable state between concurrent requests
                        team = registry_team.deep_copy()
                    except Exception as e:
                        log_warning(
                            f"deep_copy() failed for registry team '{team_id}', using shared instance: {e}",
                        )

                        team = registry_team

            # Fall back to database
            if team is None and db is not None and team_id is not None:
                from agno.team.team import get_team_by_id

                team = get_team_by_id(db=db, id=team_id, registry=registry)

            if team is None and team_id:
                log_warning(
                    f"Could not resolve team_id='{team_id}' from registry or DB for step '{config.get('name')}'"
                )

        # --- Handle Workflow reconstruction ---
        # TODO: Add workflow support to Registry (get_workflow method) for full reconstruction.
        # Currently, nested workflow steps cannot be fully reconstructed from serialized form
        # because the Registry does not track workflows. This only affects resumption of
        # paused workflows that contain nested workflow steps.
        if "workflow_id" in config and config["workflow_id"]:
            workflow_id = config.get("workflow_id")
            log_warning(
                f"Cannot reconstruct nested workflow '{workflow_id}' for step '{config.get('name')}' "
                f"(workflow registry support not yet implemented). "
                f"Using placeholder executor."
            )

            # Create a placeholder executor so validation doesn't crash.
            # The step won't be re-executable until Registry supports workflows.
            def _placeholder(step_input: StepInput) -> StepOutput:
                return StepOutput(
                    content=f"Nested workflow '{workflow_id}' cannot be re-executed (not yet reconstructable)",
                    success=False,
                )

            executor = _placeholder

        # --- Handle Executor reconstruction ---
        if "executor_ref" in config and config["executor_ref"] and registry:
            executor = registry.get_function(config["executor_ref"])

        # HITL config
        if config.get("human_review"):
            human_review = HumanReview.from_dict(config["human_review"])
        else:
            # Backward compat: build HITL from flat keys
            human_review = HumanReview(
                requires_confirmation=config.get("requires_confirmation", False),
                confirmation_message=config.get("confirmation_message"),
                on_reject=config.get("on_reject", "skip"),
                requires_user_input=config.get("requires_user_input", False),
                user_input_message=config.get("user_input_message"),
                user_input_schema=config.get("user_input_schema"),
                on_error=config.get("on_error", "skip"),
                requires_output_review=config.get("requires_output_review", False),
                output_review_message=config.get("output_review_message"),
                max_retries=config.get("hitl_max_retries", 3),
                timeout=config.get("hitl_timeout"),
                on_timeout=config.get("on_timeout", "cancel"),
            )

        return cls(
            name=config.get("name"),
            step_id=config.get("step_id"),
            description=config.get("description"),
            max_retries=config.get("max_retries", 3),
            skip_on_failure=config.get("skip_on_failure", False),
            strict_input_validation=config.get("strict_input_validation", False),
            add_workflow_history=config.get("add_workflow_history"),
            num_history_runs=config.get("num_history_runs", 3),
            human_review=human_review,
            agent=agent,
            team=team,
            executor=executor,
            workflow=workflow,
        )

    def get_links(self, position: int = 0) -> List[Dict[str, Any]]:
        """Get links for this step's agent/team/workflow.

        Args:
            position: Position of this step in the workflow.

        Returns:
            List of link dictionaries for the links table.
        """
        links = []
        link_key = self.step_id or self.name

        if self.agent is not None:
            links.append(
                {
                    "link_kind": "step_agent",
                    "link_key": link_key,
                    "child_component_id": self.agent.id,
                    "child_version": None,
                    "position": position,
                }
            )

        if self.team is not None:
            links.append(
                {
                    "link_kind": "step_team",
                    "link_key": link_key,
                    "child_component_id": self.team.id,
                    "child_version": None,
                    "position": position,
                }
            )

        if self.workflow is not None:
            links.append(
                {
                    "link_kind": "step_workflow",
                    "link_key": link_key,
                    "child_component_id": self.workflow.id,
                    "child_version": None,
                    "position": position,
                }
            )

        return links

    def create_step_requirement(
        self,
        step_index: int,
        step_input: StepInput,
    ) -> StepRequirement:
        """Create a StepRequirement for HITL pause (confirmation or user input).

        Args:
            step_index: Index of the step in the workflow.
            step_input: The prepared input for the step.

        Returns:
            StepRequirement configured for this step's HITL needs.
        """
        from datetime import datetime, timedelta, timezone

        user_input_schema = self._normalize_user_input_schema() if self.requires_user_input else None

        timeout_at = None
        if self.hitl_timeout is not None:
            timeout_at = datetime.now(timezone.utc) + timedelta(seconds=self.hitl_timeout)

        return StepRequirement(
            step_id=self.step_id or str(uuid4()),
            step_name=self.name or f"step_{step_index + 1}",
            step_index=step_index,
            step_type="Step",
            requires_confirmation=self.requires_confirmation,
            confirmation_message=self.confirmation_message,
            on_reject=self.on_reject.value if isinstance(self.on_reject, OnReject) else str(self.on_reject),
            requires_user_input=self.requires_user_input,
            user_input_message=self.user_input_message,
            user_input_schema=user_input_schema,
            step_input=step_input,
            max_retries=self.hitl_max_retries,
            timeout_at=timeout_at,
            on_timeout=self.on_timeout,
        )

    def create_error_requirement(
        self,
        step_index: int,
        error: Exception,
    ) -> ErrorRequirement:
        """Create an ErrorRequirement for HITL pause on error.

        Args:
            step_index: Index of the step in the workflow.
            error: The exception that was raised.

        Returns:
            ErrorRequirement configured for error handling.
        """
        return ErrorRequirement(
            step_id=self.step_id or str(uuid4()),
            step_name=self.name or f"step_{step_index + 1}",
            step_index=step_index,
            error_message=str(error),
            error_type=type(error).__name__,
            retry_count=self._retry_count,
        )

    def create_output_review_requirement(
        self,
        step_index: int,
        step_input: StepInput,
        step_output: "StepOutput",
        retry_count: int = 0,
    ) -> StepRequirement:
        """Create a StepRequirement for post-execution output review.

        Args:
            step_index: Index of the step in the workflow.
            step_input: The input that was used for the step.
            step_output: The output produced by the step (for review).
            retry_count: Number of times this step has been retried.

        Returns:
            StepRequirement configured for post-execution output review.
        """
        from datetime import datetime, timedelta, timezone

        timeout_at = None
        if self.hitl_timeout is not None:
            timeout_at = datetime.now(timezone.utc) + timedelta(seconds=self.hitl_timeout)

        message = self.output_review_message or f"Review output of step '{self.name or 'step'}'?"

        return StepRequirement(
            step_id=self.step_id or str(uuid4()),
            step_name=self.name or f"step_{step_index + 1}",
            step_index=step_index,
            step_type="Step",
            requires_output_review=True,
            output_review_message=message,
            requires_confirmation=True,
            confirmation_message=message,
            on_reject=self.on_reject.value if isinstance(self.on_reject, OnReject) else str(self.on_reject),
            step_input=step_input,
            step_output=step_output,
            is_post_execution=True,
            retry_count=retry_count,
            max_retries=self.hitl_max_retries,
            timeout_at=timeout_at,
            on_timeout=self.on_timeout,
        )

    def _normalize_user_input_schema(self) -> Optional[List[UserInputField]]:
        """Normalize user_input_schema to a list of UserInputField objects."""
        if not self.user_input_schema:
            return None

        result: List[UserInputField] = []
        for f in self.user_input_schema:
            if isinstance(f, UserInputField):
                result.append(f)
            elif isinstance(f, dict):
                result.append(
                    UserInputField(
                        name=f["name"],
                        field_type=f.get("field_type", "str"),
                        description=f.get("description"),
                        required=f.get("required", True),
                        allowed_values=f.get("allowed_values"),
                    )
                )
        return result

    @property
    def executor_name(self) -> str:
        """Get the name of the current executor"""
        if hasattr(self.active_executor, "name"):
            return self.active_executor.name or "unnamed_executor"
        elif self._executor_type == "function":
            return getattr(self.active_executor, "__name__", "anonymous_function")
        else:
            return f"{self._executor_type}_executor"

    @property
    def executor_type(self) -> str:
        """Get the type of the current executor"""
        return self._executor_type

    def _validate_executor_config(self):
        """Validate that only one executor type is provided"""
        executor_count = sum(
            [
                self.agent is not None,
                self.team is not None,
                self.executor is not None,
                self.workflow is not None,
            ]
        )

        if executor_count == 0:
            raise ValueError(f"Step '{self.name}' must have one executor: agent=, team=, executor=, or workflow=")

        if executor_count > 1:
            provided_executors = []
            if self.agent is not None:
                provided_executors.append("agent")
            if self.team is not None:
                provided_executors.append("team")
            if self.executor is not None:
                provided_executors.append("executor")
            if self.workflow is not None:
                provided_executors.append("workflow")

            raise ValueError(
                f"Step '{self.name}' can only have one executor type. "
                f"Provided: {', '.join(provided_executors)}. "
                f"Please use only one of: agent=, team=, executor=, or workflow="
            )

    def _set_active_executor(self) -> None:
        """Set the active executor based on what was provided"""
        if self.agent is not None:
            self.active_executor = self.agent  # type: ignore[assignment]
            self._executor_type = "agent"
        elif self.team is not None:
            self.active_executor = self.team  # type: ignore[assignment]
            self._executor_type = "team"
        elif self.workflow is not None:
            self.active_executor = self.workflow  # type: ignore[assignment]
            self._executor_type = "workflow"
        elif self.executor is not None:
            self.active_executor = self.executor  # type: ignore[assignment]
            self._executor_type = "function"
        else:
            raise ValueError("No executor configured")

    def _extract_metrics_from_response(self, response: Union[RunOutput, TeamRunOutput]) -> Optional[RunMetrics]:
        """Extract metrics from agent or team response"""
        if hasattr(response, "metrics") and response.metrics:
            return response.metrics
        return None

    def _call_custom_function(
        self,
        func: Callable,
        step_input: StepInput,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
    ) -> Any:
        """Call custom function with session_state support if the function accepts it"""

        kwargs: Dict[str, Any] = {}
        if run_context is not None and self._function_has_run_context_param():
            kwargs["run_context"] = run_context
        if session_state is not None and self._function_has_session_state_param():
            kwargs["session_state"] = session_state

        return func(step_input, **kwargs)

    async def _acall_custom_function(
        self,
        func: Callable,
        step_input: StepInput,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
    ) -> Any:
        """Call custom async function with session_state support if the function accepts it"""

        kwargs: Dict[str, Any] = {}
        if run_context is not None and self._function_has_run_context_param():
            kwargs["run_context"] = run_context
        if session_state is not None and self._function_has_session_state_param():
            kwargs["session_state"] = session_state

        if _is_async_generator_function(func):
            return func(step_input, **kwargs)
        else:
            return await func(step_input, **kwargs)

    def execute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
    ) -> StepOutput:
        """Execute the step with StepInput, returning final StepOutput (non-streaming)"""
        log_debug(f"Executing step: {self.name}")

        if step_input.previous_step_outputs:
            step_input.previous_step_content = step_input.get_last_step_content()

        if workflow_session:
            step_input.workflow_session = workflow_session

        # Create session_state copy once to avoid duplication.
        # run_context.session_state is shared intentionally across steps in the same workflow,
        # so we use a direct reference. The session_state parameter (used for nested workflows)
        # is deepcopied to prevent cross-workflow mutation.
        if run_context is not None and run_context.session_state is not None:
            session_state_copy = run_context.session_state
        else:
            session_state_copy = deepcopy(session_state) if session_state is not None else {}

        # Execute with retries
        for attempt in range(self.max_retries + 1):
            try:
                response: Union[RunOutput, TeamRunOutput, StepOutput]
                if self._executor_type == "function":
                    if _is_async_callable(self.active_executor) or _is_async_generator_function(self.active_executor):
                        raise ValueError("Cannot use async function with synchronous execution")
                    if _is_generator_function(self.active_executor):
                        content = ""
                        final_response = None
                        try:
                            for chunk in self._call_custom_function(
                                self.active_executor,
                                step_input,
                                session_state_copy,  # type: ignore[arg-type]
                                run_context,
                            ):  # type: ignore
                                if isinstance(chunk, (BaseRunOutputEvent)):
                                    if (
                                        isinstance(chunk, (RunContentEvent, TeamRunContentEvent))
                                        and chunk.content is not None
                                    ):
                                        # Its a regular chunk of content
                                        if isinstance(chunk.content, str):
                                            content += chunk.content
                                        # Its the BaseModel object, set it as the content. Replace any previous content.
                                        # There should be no previous str content at this point
                                        elif isinstance(chunk.content, BaseModel):
                                            content = chunk.content  # type: ignore[assignment]
                                        else:
                                            # Case when parse_response is False and the content is a dict
                                            content += str(chunk.content)
                                elif isinstance(chunk, (RunOutput, TeamRunOutput)):
                                    # This is the final response from the agent/team
                                    content = chunk.content  # type: ignore[assignment]
                                # If the chunk is a StepOutput, use it as the final response
                                elif isinstance(chunk, StepOutput):
                                    final_response = chunk
                                    break
                                # Non Agent/Team data structure that was yielded
                                else:
                                    content += str(chunk)

                        except StopIteration as e:
                            if hasattr(e, "value") and isinstance(e.value, StepOutput):
                                final_response = e.value

                        # Merge session_state changes back
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        if final_response is not None:
                            response = final_response
                        else:
                            response = StepOutput(content=content)
                    else:
                        # Execute function with signature inspection for session_state support
                        result = self._call_custom_function(
                            self.active_executor,  # type: ignore[arg-type]
                            step_input,
                            session_state_copy,
                            run_context,
                        )

                        # Merge session_state changes back
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        # If function returns StepOutput, use it directly
                        if isinstance(result, StepOutput):
                            response = result
                        elif isinstance(result, (RunOutput, TeamRunOutput)):
                            response = StepOutput(content=result.content)
                        else:
                            response = StepOutput(content=str(result))
                else:
                    # For agents and teams, prepare message with context
                    message = self._prepare_message(
                        step_input.input,
                        step_input.previous_step_outputs,
                    )

                    # Execute agent or team with media
                    if self._executor_type in ["agent", "team"]:
                        # Switch to appropriate logger based on executor type
                        if self._executor_type == "agent":
                            use_agent_logger()
                        elif self._executor_type == "team":
                            use_team_logger()

                        images = (
                            self._convert_image_artifacts_to_images(step_input.images) if step_input.images else None
                        )
                        videos = (
                            self._convert_video_artifacts_to_videos(step_input.videos) if step_input.videos else None
                        )
                        audios = self._convert_audio_artifacts_to_audio(step_input.audio) if step_input.audio else None

                        kwargs: Dict[str, Any] = {}
                        if isinstance(self.active_executor, Team):
                            kwargs["store_member_responses"] = True

                        # Forward background_tasks if provided
                        if background_tasks is not None:
                            kwargs["background_tasks"] = background_tasks

                        num_history_runs = self.num_history_runs if self.num_history_runs else num_history_runs

                        use_history = (
                            self.add_workflow_history
                            if self.add_workflow_history is not None
                            else add_workflow_history_to_steps
                        )

                        final_message = message
                        if use_history and workflow_session:
                            history_messages = workflow_session.get_workflow_history_context(num_runs=num_history_runs)
                            if history_messages:
                                final_message = f"{history_messages}{message}"

                        # Append user input context if available (from HITL)
                        if step_input.additional_data and step_input.additional_data.get("user_input"):
                            user_input = step_input.additional_data["user_input"]
                            user_input_str = "\n".join(f"- {k}: {v}" for k, v in user_input.items())
                            if final_message:
                                final_message = f"{final_message}\n\nUser preferences:\n{user_input_str}"
                            else:
                                final_message = f"User preferences:\n{user_input_str}"

                        # Append previous output and rejection feedback if available (from HITL retry)
                        if step_input.additional_data and step_input.additional_data.get("previous_output"):
                            prev_output = step_input.additional_data["previous_output"]
                            if final_message:
                                final_message = f"{final_message}\n\nYour previous output:\n{prev_output}"
                            else:
                                final_message = f"Your previous output:\n{prev_output}"
                        if step_input.additional_data and step_input.additional_data.get("rejection_feedback"):
                            feedback = step_input.additional_data["rejection_feedback"]
                            final_message = f"{final_message}\n\nFeedback from reviewer:\n{feedback}"

                        response = self.active_executor.run(  # type: ignore
                            input=final_message,  # type: ignore
                            images=images,
                            videos=videos,
                            audio=audios,
                            files=step_input.files,
                            session_id=session_id,
                            user_id=user_id,
                            session_state=session_state_copy,  # Send a copy to the executor
                            run_context=run_context,
                            add_dependencies_to_context=add_dependencies_to_context,
                            add_session_state_to_context=add_session_state_to_context,
                            **kwargs,
                        )

                        # Update workflow session state
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        if store_executor_outputs and workflow_run_response is not None:
                            self._store_executor_response(workflow_run_response, response)  # type: ignore

                        # Check if agent/team response is paused (e.g., due to tool HITL)
                        # Propagate the pause to the workflow level
                        if hasattr(response, "is_paused") and response.is_paused:
                            use_workflow_logger()
                            step_output = self._process_step_output(response)
                            step_output.is_paused = True
                            return step_output

                        # Switch back to workflow logger after execution
                        use_workflow_logger()
                    elif self._executor_type == "workflow":
                        # Execute nested workflow
                        response = self._execute_nested_workflow(
                            step_input=step_input,
                            session_id=session_id,
                            user_id=user_id,
                            workflow_run_response=workflow_run_response,
                            session_state=session_state_copy,
                            store_executor_outputs=store_executor_outputs,
                            background_tasks=background_tasks,
                        )

                        # Merge session_state changes back
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)
                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # Create StepOutput from response
                step_output = self._process_step_output(response)  # type: ignore

                return step_output

            except Exception as e:
                self.retry_count = attempt + 1
                log_warning(f"Step {self.name} failed (attempt {attempt + 1}): {str(e)}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        log_debug(f"Step {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty StepOutput for skipped step
                        return StepOutput(content=f"Step {self.name} failed but skipped", success=False, error=str(e))
                    else:
                        raise e

        return StepOutput(content=f"Step {self.name} failed but skipped", success=False)

    def _function_has_run_context_param(self) -> bool:
        """Check if the custom function has a run_context parameter"""
        if self._executor_type != "function":
            return False

        try:
            sig = inspect.signature(self.active_executor)  # type: ignore
            return "run_context" in sig.parameters
        except Exception:
            return False

    def _function_has_session_state_param(self) -> bool:
        """Check if the custom function has a session_state parameter"""
        if self._executor_type != "function":
            return False

        try:
            sig = inspect.signature(self.active_executor)  # type: ignore
            return "session_state" in sig.parameters
        except Exception:
            return False

    def _enrich_event_with_context(
        self,
        event: Any,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> Any:
        """Enrich event with step and workflow context information"""
        if workflow_run_response is None:
            return event

        # For events from nested workflows (workflow_id already set to a different workflow),
        # preserve the original workflow_id/workflow_run_id so consumers can correctly
        # attribute events to the originating workflow.
        is_nested_event = (
            hasattr(event, "workflow_id")
            and event.workflow_id is not None
            and event.workflow_id != workflow_run_response.workflow_id
        )

        if not is_nested_event:
            if hasattr(event, "workflow_id"):
                event.workflow_id = workflow_run_response.workflow_id
            if hasattr(event, "workflow_run_id"):
                event.workflow_run_id = workflow_run_response.run_id

        # Set session_id to match workflow's session_id for consistent event tracking
        if hasattr(event, "session_id") and workflow_run_response.session_id:
            event.session_id = workflow_run_response.session_id
        # For nested events, preserve the inner workflow's step_id/step_name
        if not is_nested_event:
            if hasattr(event, "step_id"):
                event.step_id = self.step_id
            if hasattr(event, "step_name") and self.name is not None:
                if getattr(event, "step_name", None) is None:
                    event.step_name = self.name
        else:
            # For nested events, set parent_step_id so consumers know which outer step contains them.
            # Only set if not already set — the innermost enclosing step is the true host;
            # outer layers must not overwrite it (breaks depth-2+ nesting).
            if hasattr(event, "parent_step_id") and event.parent_step_id is None:
                event.parent_step_id = self.step_id
        # Only set step_index if it's not already set (preserve parallel.py's tuples)
        if hasattr(event, "step_index") and step_index is not None:
            if event.step_index is None:
                event.step_index = step_index

        return event

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional["WorkflowSession"] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
    ) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Execute the step with event-driven streaming support"""

        if step_input.previous_step_outputs:
            step_input.previous_step_content = step_input.get_last_step_content()

        if workflow_session:
            step_input.workflow_session = workflow_session

        # Create session_state copy once to avoid duplication.
        # run_context.session_state is shared intentionally across steps in the same workflow,
        # so we use a direct reference. The session_state parameter (used for nested workflows)
        # is deepcopied to prevent cross-workflow mutation.
        if run_context is not None and run_context.session_state is not None:
            session_state_copy = run_context.session_state
        else:
            session_state_copy = deepcopy(session_state) if session_state is not None else {}

        # Emit StepStartedEvent
        if stream_events and workflow_run_response:
            yield StepStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                step_id=self.step_id,
                parent_step_id=parent_step_id,
            )

        # Execute with retries and streaming
        for attempt in range(self.max_retries + 1):
            try:
                log_debug(f"Step {self.name} streaming attempt {attempt + 1}/{self.max_retries + 1}")
                final_response = None

                if self._executor_type == "function":
                    log_debug(f"Executing function executor for step: {self.name}")
                    if _is_async_callable(self.active_executor) or _is_async_generator_function(self.active_executor):
                        raise ValueError("Cannot use async function with synchronous execution")
                    if _is_generator_function(self.active_executor):
                        log_debug("Function returned iterable, streaming events")
                        content = ""
                        try:
                            iterator = self._call_custom_function(
                                self.active_executor,
                                step_input,
                                session_state_copy,
                                run_context,
                            )
                            for event in iterator:  # type: ignore
                                if isinstance(event, (BaseRunOutputEvent)):
                                    if (
                                        isinstance(event, (RunContentEvent, TeamRunContentEvent))
                                        and event.content is not None
                                    ):
                                        if isinstance(event.content, str):
                                            content += event.content
                                        elif isinstance(event.content, BaseModel):
                                            content = event.content  # type: ignore[assignment]
                                        else:
                                            content = str(event.content)
                                    # Only yield executor events if stream_executor_events is True
                                    if stream_executor_events:
                                        enriched_event = self._enrich_event_with_context(
                                            event, workflow_run_response, step_index
                                        )
                                        yield enriched_event  # type: ignore[misc]
                                elif isinstance(event, (RunOutput, TeamRunOutput)):
                                    content = event.content  # type: ignore[assignment]
                                elif isinstance(event, StepOutput):
                                    final_response = event
                                    break
                                else:
                                    content += str(event)

                            # Merge session_state changes back
                            if run_context is None and session_state is not None:
                                merge_dictionaries(session_state, session_state_copy)

                            if not final_response:
                                final_response = StepOutput(content=content)
                        except StopIteration as e:
                            if hasattr(e, "value") and isinstance(e.value, StepOutput):
                                final_response = e.value

                    else:
                        result = self._call_custom_function(
                            self.active_executor,  # type: ignore[arg-type]
                            step_input,
                            session_state_copy,
                            run_context,
                        )

                        # Merge session_state changes back
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        if isinstance(result, StepOutput):
                            final_response = result
                        elif isinstance(result, (RunOutput, TeamRunOutput)):
                            final_response = StepOutput(content=result.content)
                        else:
                            final_response = StepOutput(content=str(result))
                        log_debug("Function returned non-iterable, created StepOutput")
                else:
                    # For agents and teams, prepare message with context
                    message = self._prepare_message(
                        step_input.input,
                        step_input.previous_step_outputs,
                    )

                    if self._executor_type in ["agent", "team"]:
                        # Switch to appropriate logger based on executor type
                        if self._executor_type == "agent":
                            use_agent_logger()
                        elif self._executor_type == "team":
                            use_team_logger()

                        images = (
                            self._convert_image_artifacts_to_images(step_input.images) if step_input.images else None
                        )
                        videos = (
                            self._convert_video_artifacts_to_videos(step_input.videos) if step_input.videos else None
                        )
                        audios = self._convert_audio_artifacts_to_audio(step_input.audio) if step_input.audio else None

                        kwargs: Dict[str, Any] = {}
                        if isinstance(self.active_executor, Team):
                            kwargs["store_member_responses"] = True

                        # Forward background_tasks if provided
                        if background_tasks is not None:
                            kwargs["background_tasks"] = background_tasks

                        num_history_runs = self.num_history_runs if self.num_history_runs else num_history_runs

                        use_history = (
                            self.add_workflow_history
                            if self.add_workflow_history is not None
                            else add_workflow_history_to_steps
                        )

                        final_message = message
                        if use_history and workflow_session:
                            history_messages = workflow_session.get_workflow_history_context(num_runs=num_history_runs)
                            if history_messages:
                                final_message = f"{history_messages}{message}"

                        # Append user input context if available (from HITL)
                        if step_input.additional_data and step_input.additional_data.get("user_input"):
                            user_input = step_input.additional_data["user_input"]
                            user_input_str = "\n".join(f"- {k}: {v}" for k, v in user_input.items())
                            if final_message:
                                final_message = f"{final_message}\n\nUser preferences:\n{user_input_str}"
                            else:
                                final_message = f"User preferences:\n{user_input_str}"

                        # Append previous output and rejection feedback if available (from HITL retry)
                        if step_input.additional_data and step_input.additional_data.get("previous_output"):
                            prev_output = step_input.additional_data["previous_output"]
                            if final_message:
                                final_message = f"{final_message}\n\nYour previous output:\n{prev_output}"
                            else:
                                final_message = f"Your previous output:\n{prev_output}"
                        if step_input.additional_data and step_input.additional_data.get("rejection_feedback"):
                            feedback = step_input.additional_data["rejection_feedback"]
                            final_message = f"{final_message}\n\nFeedback from reviewer:\n{feedback}"

                        response_stream = self.active_executor.run(  # type: ignore[call-overload, misc]
                            input=final_message,
                            images=images,
                            videos=videos,
                            audio=audios,
                            files=step_input.files,
                            session_id=session_id,
                            user_id=user_id,
                            session_state=session_state_copy,  # Send a copy to the executor
                            stream=True,
                            stream_events=stream_events,
                            yield_run_output=True,
                            run_context=run_context,
                            add_dependencies_to_context=add_dependencies_to_context,
                            add_session_state_to_context=add_session_state_to_context,
                            **kwargs,
                        )

                        active_executor_run_response = None
                        for event in response_stream:
                            if isinstance(event, RunOutput) or isinstance(event, TeamRunOutput):
                                active_executor_run_response = event
                                continue
                            # Only yield executor events if stream_executor_events is True
                            if stream_executor_events:
                                enriched_event = self._enrich_event_with_context(
                                    event, workflow_run_response, step_index
                                )
                                yield enriched_event  # type: ignore[misc]

                        # Update workflow session state
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        if store_executor_outputs and workflow_run_response is not None:
                            self._store_executor_response(workflow_run_response, active_executor_run_response)  # type: ignore

                        # Check if agent/team response is paused (e.g., due to tool HITL)
                        # Propagate the pause to the workflow level
                        if (
                            active_executor_run_response is not None
                            and hasattr(active_executor_run_response, "is_paused")
                            and active_executor_run_response.is_paused
                        ):
                            use_workflow_logger()
                            paused_output = self._process_step_output(active_executor_run_response)
                            paused_output.is_paused = True
                            # paused state is already set on paused_output.is_paused
                            yield paused_output
                            return

                        final_response = active_executor_run_response  # type: ignore

                    elif self._executor_type == "workflow":
                        # Execute nested workflow with streaming
                        for event in self._execute_nested_workflow_stream(
                            step_input=step_input,
                            session_id=session_id,
                            user_id=user_id,
                            workflow_run_response=workflow_run_response,
                            session_state=session_state_copy,
                            store_executor_outputs=store_executor_outputs,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                        ):
                            if isinstance(event, StepOutput):
                                final_response = event
                            else:
                                # Yield nested workflow events
                                if stream_executor_events:
                                    enriched_event = self._enrich_event_with_context(
                                        event, workflow_run_response, step_index
                                    )
                                    yield enriched_event  # type: ignore[misc]

                        # Merge session_state changes back
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # If we didn't get a final response, create one
                if final_response is None:
                    final_response = StepOutput(content="")
                    log_debug("Created empty StepOutput as fallback")

                # Switch back to workflow logger after execution
                use_workflow_logger()

                # Yield the step output
                final_response = self._process_step_output(final_response)
                yield final_response

                # Emit StepCompletedEvent
                if stream_events and workflow_run_response:
                    yield StepCompletedEvent(
                        run_id=workflow_run_response.run_id or "",
                        workflow_name=workflow_run_response.workflow_name or "",
                        workflow_id=workflow_run_response.workflow_id or "",
                        session_id=workflow_run_response.session_id or "",
                        step_name=self.name,
                        step_index=step_index,
                        content=final_response.content,
                        step_response=final_response,
                        parent_step_id=parent_step_id,
                    )

                return
            except Exception as e:
                self.retry_count = attempt + 1
                log_warning(f"Step {self.name} failed (attempt {attempt + 1}): {str(e)}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        log_debug(f"Step {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty StepOutput for skipped step
                        step_output = StepOutput(
                            content=f"Step {self.name} failed but skipped", success=False, error=str(e)
                        )
                        yield step_output
                        return
                    else:
                        raise e

        return

    async def aexecute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        workflow_session: Optional["WorkflowSession"] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
    ) -> StepOutput:
        """Execute the step with StepInput, returning final StepOutput (non-streaming)"""
        logger.info(f"Executing async step (non-streaming): {self.name}")
        log_debug(f"Executor type: {self._executor_type}")

        if step_input.previous_step_outputs:
            step_input.previous_step_content = step_input.get_last_step_content()

        if workflow_session:
            step_input.workflow_session = workflow_session

        # Create session_state copy once to avoid duplication.
        # run_context.session_state is shared intentionally across steps in the same workflow,
        # so we use a direct reference. The session_state parameter (used for nested workflows)
        # is deepcopied to prevent cross-workflow mutation.
        if run_context is not None and run_context.session_state is not None:
            session_state_copy = run_context.session_state
        else:
            session_state_copy = deepcopy(session_state) if session_state is not None else {}

        # Execute with retries
        for attempt in range(self.max_retries + 1):
            try:
                if self._executor_type == "function":
                    if _is_generator_function(self.active_executor) or _is_async_generator_function(
                        self.active_executor
                    ):
                        content = ""
                        final_response = None
                        try:
                            if _is_generator_function(self.active_executor):
                                iterator = self._call_custom_function(
                                    self.active_executor,
                                    step_input,
                                    session_state_copy,
                                    run_context,
                                )
                                for chunk in iterator:  # type: ignore
                                    if isinstance(chunk, (BaseRunOutputEvent)):
                                        if (
                                            isinstance(chunk, (RunContentEvent, TeamRunContentEvent))
                                            and chunk.content is not None
                                        ):
                                            if isinstance(chunk.content, str):
                                                content += chunk.content
                                            elif isinstance(chunk.content, BaseModel):
                                                content = chunk.content  # type: ignore[assignment]
                                            else:
                                                content = str(chunk.content)
                                    elif isinstance(chunk, (RunOutput, TeamRunOutput)):
                                        content = chunk.content  # type: ignore[assignment]
                                    elif isinstance(chunk, StepOutput):
                                        final_response = chunk
                                        break
                                    else:
                                        content += str(chunk)

                            else:
                                if _is_async_generator_function(self.active_executor):
                                    iterator = await self._acall_custom_function(
                                        self.active_executor,
                                        step_input,
                                        session_state_copy,
                                        run_context,
                                    )
                                    async for chunk in iterator:  # type: ignore
                                        if isinstance(chunk, (BaseRunOutputEvent)):
                                            if (
                                                isinstance(chunk, (RunContentEvent, TeamRunContentEvent))
                                                and chunk.content is not None
                                            ):
                                                if isinstance(chunk.content, str):
                                                    content += chunk.content
                                                elif isinstance(chunk.content, BaseModel):
                                                    content = chunk.content  # type: ignore[assignment]
                                                else:
                                                    content = str(chunk.content)
                                        elif isinstance(chunk, (RunOutput, TeamRunOutput)):
                                            content = chunk.content  # type: ignore[assignment]
                                        elif isinstance(chunk, StepOutput):
                                            final_response = chunk
                                            break
                                        else:
                                            content += str(chunk)

                        except StopIteration as e:
                            if hasattr(e, "value") and isinstance(e.value, StepOutput):
                                final_response = e.value

                        # Merge session_state changes back
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        if final_response is not None:
                            response = final_response
                        else:
                            response = StepOutput(content=content)
                    else:
                        if _is_async_callable(self.active_executor):
                            result = await self._acall_custom_function(
                                self.active_executor,
                                step_input,
                                session_state_copy,
                                run_context,
                            )
                        else:
                            result = self._call_custom_function(
                                self.active_executor,  # type: ignore[arg-type]
                                step_input,
                                session_state_copy,
                                run_context,
                            )

                        # Merge session_state changes back
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        # If function returns StepOutput, use it directly
                        if isinstance(result, StepOutput):
                            response = result
                        elif isinstance(result, (RunOutput, TeamRunOutput)):
                            response = StepOutput(content=result.content)
                        else:
                            response = StepOutput(content=str(result))

                else:
                    # For agents and teams, prepare message with context
                    message = self._prepare_message(
                        step_input.input,
                        step_input.previous_step_outputs,
                    )

                    # Execute agent or team with media
                    if self._executor_type in ["agent", "team"]:
                        # Switch to appropriate logger based on executor type
                        if self._executor_type == "agent":
                            use_agent_logger()
                        elif self._executor_type == "team":
                            use_team_logger()

                        images = (
                            self._convert_image_artifacts_to_images(step_input.images) if step_input.images else None
                        )
                        videos = (
                            self._convert_video_artifacts_to_videos(step_input.videos) if step_input.videos else None
                        )
                        audios = self._convert_audio_artifacts_to_audio(step_input.audio) if step_input.audio else None

                        kwargs: Dict[str, Any] = {}
                        if isinstance(self.active_executor, Team):
                            kwargs["store_member_responses"] = True

                        # Forward background_tasks if provided
                        if background_tasks is not None:
                            kwargs["background_tasks"] = background_tasks

                        num_history_runs = self.num_history_runs if self.num_history_runs else num_history_runs

                        use_history = (
                            self.add_workflow_history
                            if self.add_workflow_history is not None
                            else add_workflow_history_to_steps
                        )

                        final_message = message
                        if use_history and workflow_session:
                            history_messages = workflow_session.get_workflow_history_context(num_runs=num_history_runs)
                            if history_messages:
                                final_message = f"{history_messages}{message}"

                        # Append user input context if available (from HITL)
                        if step_input.additional_data and step_input.additional_data.get("user_input"):
                            user_input = step_input.additional_data["user_input"]
                            user_input_str = "\n".join(f"- {k}: {v}" for k, v in user_input.items())
                            if final_message:
                                final_message = f"{final_message}\n\nUser preferences:\n{user_input_str}"
                            else:
                                final_message = f"User preferences:\n{user_input_str}"

                        # Append previous output and rejection feedback if available (from HITL retry)
                        if step_input.additional_data and step_input.additional_data.get("previous_output"):
                            prev_output = step_input.additional_data["previous_output"]
                            if final_message:
                                final_message = f"{final_message}\n\nYour previous output:\n{prev_output}"
                            else:
                                final_message = f"Your previous output:\n{prev_output}"
                        if step_input.additional_data and step_input.additional_data.get("rejection_feedback"):
                            feedback = step_input.additional_data["rejection_feedback"]
                            final_message = f"{final_message}\n\nFeedback from reviewer:\n{feedback}"

                        response = await self.active_executor.arun(  # type: ignore
                            input=final_message,  # type: ignore
                            images=images,
                            videos=videos,
                            audio=audios,
                            files=step_input.files,
                            session_id=session_id,
                            user_id=user_id,
                            session_state=session_state_copy,
                            run_context=run_context,
                            add_dependencies_to_context=add_dependencies_to_context,
                            add_session_state_to_context=add_session_state_to_context,
                            **kwargs,
                        )

                        # Update workflow session state
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        if store_executor_outputs and workflow_run_response is not None:
                            self._store_executor_response(workflow_run_response, response)  # type: ignore

                        # Check if agent/team response is paused (e.g., due to tool HITL)
                        # Propagate the pause to the workflow level
                        if hasattr(response, "is_paused") and response.is_paused:
                            use_workflow_logger()
                            step_output = self._process_step_output(response)
                            step_output.is_paused = True
                            return step_output

                        # Switch back to workflow logger after execution
                        use_workflow_logger()
                    elif self._executor_type == "workflow":
                        # Execute nested workflow asynchronously
                        response = await self._aexecute_nested_workflow(
                            step_input=step_input,
                            session_id=session_id,
                            user_id=user_id,
                            workflow_run_response=workflow_run_response,
                            session_state=session_state_copy,
                            store_executor_outputs=store_executor_outputs,
                            background_tasks=background_tasks,
                        )

                        # Merge session_state changes back
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)
                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # Create StepOutput from response
                step_output = self._process_step_output(response)  # type: ignore

                return step_output

            except Exception as e:
                self.retry_count = attempt + 1
                log_warning(f"Step {self.name} failed (attempt {attempt + 1}): {str(e)}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        log_debug(f"Step {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty StepOutput for skipped step
                        return StepOutput(content=f"Step {self.name} failed but skipped", success=False, error=str(e))
                    else:
                        raise e

        return StepOutput(content=f"Step {self.name} failed but skipped", success=False)

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional["WorkflowSession"] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Execute the step with event-driven streaming support"""

        if step_input.previous_step_outputs:
            step_input.previous_step_content = step_input.get_last_step_content()

        if workflow_session:
            step_input.workflow_session = workflow_session

        # Create session_state copy once to avoid duplication.
        # run_context.session_state is shared intentionally across steps in the same workflow,
        # so we use a direct reference. The session_state parameter (used for nested workflows)
        # is deepcopied to prevent cross-workflow mutation.
        if run_context is not None and run_context.session_state is not None:
            session_state_copy = run_context.session_state
        else:
            session_state_copy = deepcopy(session_state) if session_state is not None else {}

        if stream_events and workflow_run_response:
            # Emit StepStartedEvent
            yield StepStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                step_id=self.step_id,
                parent_step_id=parent_step_id,
            )

        # Execute with retries and streaming
        for attempt in range(self.max_retries + 1):
            try:
                log_debug(f"Async step {self.name} streaming attempt {attempt + 1}/{self.max_retries + 1}")
                final_response = None

                if self._executor_type == "function":
                    log_debug(f"Executing async function executor for step: {self.name}")

                    # Check if the function is an async generator
                    if _is_async_generator_function(self.active_executor):
                        content = ""
                        # It's an async generator - iterate over it
                        iterator = await self._acall_custom_function(
                            self.active_executor,
                            step_input,
                            session_state_copy,
                            run_context,
                        )
                        async for event in iterator:  # type: ignore
                            if isinstance(event, (BaseRunOutputEvent)):
                                if (
                                    isinstance(event, (RunContentEvent, TeamRunContentEvent))
                                    and event.content is not None
                                ):
                                    if isinstance(event.content, str):
                                        content += event.content
                                    elif isinstance(event.content, BaseModel):
                                        content = event.content  # type: ignore[assignment]
                                    else:
                                        content = str(event.content)

                                # Only yield executor events if stream_executor_events is True
                                if stream_executor_events:
                                    enriched_event = self._enrich_event_with_context(
                                        event, workflow_run_response, step_index
                                    )
                                    yield enriched_event  # type: ignore[misc]
                            elif isinstance(event, (RunOutput, TeamRunOutput)):
                                content = event.content  # type: ignore[assignment]
                            elif isinstance(event, StepOutput):
                                final_response = event
                                break
                            else:
                                content += str(event)
                        if not final_response:
                            final_response = StepOutput(content=content)
                    elif _is_async_callable(self.active_executor):
                        # It's a regular async function - await it
                        result = await self._acall_custom_function(
                            self.active_executor,
                            step_input,
                            session_state_copy,
                            run_context,
                        )
                        if isinstance(result, StepOutput):
                            final_response = result
                        elif isinstance(result, (RunOutput, TeamRunOutput)):
                            final_response = StepOutput(content=result.content)
                        else:
                            final_response = StepOutput(content=str(result))
                    elif _is_generator_function(self.active_executor):
                        content = ""
                        # It's a regular generator function - iterate over it
                        iterator = self._call_custom_function(
                            self.active_executor,
                            step_input,
                            session_state_copy,
                            run_context,
                        )
                        for event in iterator:  # type: ignore
                            if isinstance(event, (BaseRunOutputEvent)):
                                if (
                                    isinstance(event, (RunContentEvent, TeamRunContentEvent))
                                    and event.content is not None
                                ):
                                    if isinstance(event.content, str):
                                        content += event.content
                                    elif isinstance(event.content, BaseModel):
                                        content = event.content  # type: ignore[assignment]
                                    else:
                                        content = str(event.content)

                                # Only yield executor events if stream_executor_events is True
                                if stream_executor_events:
                                    enriched_event = self._enrich_event_with_context(
                                        event, workflow_run_response, step_index
                                    )
                                    yield enriched_event  # type: ignore[misc]
                            elif isinstance(event, (RunOutput, TeamRunOutput)):
                                content = event.content  # type: ignore[assignment]
                            elif isinstance(event, StepOutput):
                                final_response = event
                                break
                            else:
                                if isinstance(content, str):
                                    content += str(event)
                                else:
                                    content = str(event)
                        if not final_response:
                            final_response = StepOutput(content=content)
                    else:
                        # It's a regular function - call it directly
                        result = self._call_custom_function(
                            self.active_executor,  # type: ignore[arg-type]
                            step_input,
                            session_state_copy,
                            run_context,
                        )
                        if isinstance(result, StepOutput):
                            final_response = result
                        elif isinstance(result, (RunOutput, TeamRunOutput)):
                            final_response = StepOutput(content=result.content)
                        else:
                            final_response = StepOutput(content=str(result))

                    # Merge session_state changes back
                    if run_context is None and session_state is not None:
                        merge_dictionaries(session_state, session_state_copy)
                else:
                    # For agents and teams, prepare message with context
                    message = self._prepare_message(
                        step_input.input,
                        step_input.previous_step_outputs,
                    )

                    if self._executor_type in ["agent", "team"]:
                        # Switch to appropriate logger based on executor type
                        if self._executor_type == "agent":
                            use_agent_logger()
                        elif self._executor_type == "team":
                            use_team_logger()

                        images = (
                            self._convert_image_artifacts_to_images(step_input.images) if step_input.images else None
                        )
                        videos = (
                            self._convert_video_artifacts_to_videos(step_input.videos) if step_input.videos else None
                        )
                        audios = self._convert_audio_artifacts_to_audio(step_input.audio) if step_input.audio else None

                        kwargs: Dict[str, Any] = {}
                        if isinstance(self.active_executor, Team):
                            kwargs["store_member_responses"] = True

                        # Forward background_tasks if provided
                        if background_tasks is not None:
                            kwargs["background_tasks"] = background_tasks

                        num_history_runs = self.num_history_runs if self.num_history_runs else num_history_runs

                        use_history = (
                            self.add_workflow_history
                            if self.add_workflow_history is not None
                            else add_workflow_history_to_steps
                        )

                        final_message = message
                        if use_history and workflow_session:
                            history_messages = workflow_session.get_workflow_history_context(num_runs=num_history_runs)
                            if history_messages:
                                final_message = f"{history_messages}{message}"

                        # Append user input context if available (from HITL)
                        if step_input.additional_data and step_input.additional_data.get("user_input"):
                            user_input = step_input.additional_data["user_input"]
                            user_input_str = "\n".join(f"- {k}: {v}" for k, v in user_input.items())
                            if final_message:
                                final_message = f"{final_message}\n\nUser preferences:\n{user_input_str}"
                            else:
                                final_message = f"User preferences:\n{user_input_str}"

                        # Append previous output and rejection feedback if available (from HITL retry)
                        if step_input.additional_data and step_input.additional_data.get("previous_output"):
                            prev_output = step_input.additional_data["previous_output"]
                            if final_message:
                                final_message = f"{final_message}\n\nYour previous output:\n{prev_output}"
                            else:
                                final_message = f"Your previous output:\n{prev_output}"
                        if step_input.additional_data and step_input.additional_data.get("rejection_feedback"):
                            feedback = step_input.additional_data["rejection_feedback"]
                            final_message = f"{final_message}\n\nFeedback from reviewer:\n{feedback}"

                        response_stream = self.active_executor.arun(  # type: ignore
                            input=final_message,
                            images=images,
                            videos=videos,
                            audio=audios,
                            files=step_input.files,
                            session_id=session_id,
                            user_id=user_id,
                            session_state=session_state_copy,
                            stream=True,
                            stream_events=stream_events,
                            run_context=run_context,
                            yield_run_output=True,
                            add_dependencies_to_context=add_dependencies_to_context,
                            add_session_state_to_context=add_session_state_to_context,
                            **kwargs,
                        )

                        active_executor_run_response = None
                        async for event in response_stream:
                            if isinstance(event, RunOutput) or isinstance(event, TeamRunOutput):
                                active_executor_run_response = event
                                break
                            # Only yield executor events if stream_executor_events is True
                            if stream_executor_events:
                                enriched_event = self._enrich_event_with_context(
                                    event, workflow_run_response, step_index
                                )
                                yield enriched_event  # type: ignore[misc]

                        # Update workflow session state
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        if store_executor_outputs and workflow_run_response is not None:
                            self._store_executor_response(workflow_run_response, active_executor_run_response)  # type: ignore

                        # Check if agent/team response is paused (e.g., due to tool HITL)
                        # Propagate the pause to the workflow level
                        if (
                            active_executor_run_response is not None
                            and hasattr(active_executor_run_response, "is_paused")
                            and active_executor_run_response.is_paused
                        ):
                            use_workflow_logger()
                            paused_output = self._process_step_output(active_executor_run_response)
                            paused_output.is_paused = True
                            # paused state is already set on paused_output.is_paused
                            yield paused_output
                            return

                        final_response = active_executor_run_response  # type: ignore

                    elif self._executor_type == "workflow":
                        # Execute nested workflow with async streaming
                        async for event in self._aexecute_nested_workflow_stream(
                            step_input=step_input,
                            session_id=session_id,
                            user_id=user_id,
                            workflow_run_response=workflow_run_response,
                            session_state=session_state_copy,
                            store_executor_outputs=store_executor_outputs,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                        ):
                            if isinstance(event, StepOutput):
                                final_response = event
                            else:
                                # Yield nested workflow events
                                if stream_executor_events:
                                    enriched_event = self._enrich_event_with_context(
                                        event, workflow_run_response, step_index
                                    )
                                    yield enriched_event  # type: ignore[misc]

                        # Merge session_state changes back
                        if run_context is None and session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # If we didn't get a final response, create one
                if final_response is None:
                    final_response = StepOutput(content="")

                # Switch back to workflow logger after execution
                use_workflow_logger()

                # Yield the final response
                final_response = self._process_step_output(final_response)
                yield final_response

                if stream_events and workflow_run_response:
                    # Emit StepCompletedEvent
                    yield StepCompletedEvent(
                        run_id=workflow_run_response.run_id or "",
                        workflow_name=workflow_run_response.workflow_name or "",
                        workflow_id=workflow_run_response.workflow_id or "",
                        session_id=workflow_run_response.session_id or "",
                        step_name=self.name,
                        step_index=step_index,
                        step_id=self.step_id,
                        content=final_response.content,
                        step_response=final_response,
                        parent_step_id=parent_step_id,
                    )
                return

            except Exception as e:
                self.retry_count = attempt + 1
                log_warning(f"Step {self.name} failed (attempt {attempt + 1}): {str(e)}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        log_debug(f"Step {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty StepOutput for skipped step
                        step_output = StepOutput(
                            content=f"Step {self.name} failed but skipped", success=False, error=str(e)
                        )
                        yield step_output
                    else:
                        raise e

        return

    def get_chat_history(self, session_id: str, last_n_runs: Optional[int] = None) -> List[Message]:
        """Return the step's Agent or Team chat history for the given session.

        Args:
            session_id: The session ID to get the chat history for. If not provided, the current cached session ID is used.
            last_n_runs: Number of recent runs to include. If None, all runs will be considered.

        Returns:
            List[Message]: The step's Agent or Team chat history for the given session.
        """
        session: Union[AgentSession, TeamSession, WorkflowSession, None] = None

        if self.agent:
            session = self.agent.get_session(session_id=session_id)
            if not session:
                log_warning("Session not found")
                return []

            if not isinstance(session, WorkflowSession):
                raise ValueError("The provided session is not a WorkflowSession")

            session = cast(WorkflowSession, session)
            return session.get_messages(last_n_runs=last_n_runs, agent_id=self.agent.id)

        elif self.team:
            session = self.team.get_session(session_id=session_id)
            if not session:
                log_warning("Session not found")
                return []

            if not isinstance(session, WorkflowSession):
                raise ValueError("The provided session is not a WorkflowSession")

            session = cast(WorkflowSession, session)
            return session.get_messages(last_n_runs=last_n_runs, team_id=self.team.id)

        return []

    async def aget_chat_history(
        self, session_id: Optional[str] = None, last_n_runs: Optional[int] = None
    ) -> List[Message]:
        """Return the step's Agent or Team chat history for the given session.

        Args:
            session_id: The session ID to get the chat history for. If not provided, the current cached session ID is used.
            last_n_runs: Number of recent runs to include. If None, all runs will be considered.

        Returns:
            List[Message]: The step's Agent or Team chat history for the given session.
        """
        session: Union[AgentSession, TeamSession, WorkflowSession, None] = None

        if self.agent:
            session = await self.agent.aget_session(session_id=session_id)
            if not session:
                log_warning("Session not found")
                return []

            if not isinstance(session, WorkflowSession):
                raise ValueError("The provided session is not a WorkflowSession")

            session = cast(WorkflowSession, session)
            return session.get_messages(last_n_runs=last_n_runs, agent_id=self.agent.id)

        elif self.team:
            session = await self.team.aget_session(session_id=session_id)
            if not session:
                log_warning("Session not found")
                return []

            if not isinstance(session, WorkflowSession):
                raise ValueError("The provided session is not a WorkflowSession")

            return session.get_messages(last_n_runs=last_n_runs, team_id=self.team.id)

        return []

    def _store_executor_response(
        self,
        workflow_run_response: "WorkflowRunOutput",
        executor_run_response: Optional[Union[RunOutput, TeamRunOutput]],
    ) -> None:
        """Store agent/team responses in step_executor_runs if enabled"""
        if executor_run_response is None:
            log_warning(f"Step '{self.name}': executor produced no response to store")
            return
        if self._executor_type in ["agent", "team"]:
            # propogate the workflow run id as parent run id to the executor response
            executor_run_response.parent_run_id = workflow_run_response.run_id
            executor_run_response.workflow_step_id = self.step_id

            # Scrub the executor response based on the executor's storage flags before storing
            if (
                not self.active_executor.store_media
                or not self.active_executor.store_tool_messages
                or not self.active_executor.store_history_messages
            ):  # type: ignore
                self.active_executor.scrub_run_output_for_storage(executor_run_response)  # type: ignore

            # Get the raw response from the step's active executor
            raw_response = executor_run_response
            if raw_response and isinstance(raw_response, (RunOutput, TeamRunOutput)):
                if workflow_run_response.step_executor_runs is None:
                    workflow_run_response.step_executor_runs = []

                raw_response.workflow_step_id = self.step_id
                # Add the primary executor run
                workflow_run_response.step_executor_runs.append(raw_response)

                # Add direct member agent runs (in case of a team we force store_member_responses=True here)
                if isinstance(raw_response, TeamRunOutput) and getattr(
                    self.active_executor, "store_member_responses", False
                ):
                    for mr in raw_response.member_responses or []:
                        if isinstance(mr, RunOutput):
                            workflow_run_response.step_executor_runs.append(mr)

    def _get_deepest_content_from_step_output(self, step_output: "StepOutput") -> Optional[str]:
        """
        Extract the deepest content from a step output, handling nested structures like Steps, Router, Loop, etc.

        For container steps (Steps, Router, Loop, etc.), this will recursively find the content from the
        last actual step rather than using the generic container message.

        For Parallel steps, aggregates content from ALL inner steps (not just the last one).
        """
        # If this step has nested steps (like Steps, Condition, Router, Loop, Parallel, etc.)
        if hasattr(step_output, "steps") and step_output.steps and len(step_output.steps) > 0:
            # For Parallel steps, aggregate content from ALL inner steps
            if step_output.step_type == StepType.PARALLEL:
                aggregated_parts = []
                for i, inner_step in enumerate(step_output.steps):
                    inner_content = self._get_deepest_content_from_step_output(inner_step)
                    if inner_content:
                        step_name = inner_step.step_name or f"Step {i + 1}"
                        aggregated_parts.append(f"=== {step_name} ===\n{inner_content}")
                return "\n\n".join(aggregated_parts) if aggregated_parts else step_output.content  # type: ignore

            # For other nested step types, recursively get content from the last nested step
            return self._get_deepest_content_from_step_output(step_output.steps[-1])

        # For regular steps, return their content
        return step_output.content  # type: ignore

    def _prepare_message(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]],
        previous_step_outputs: Optional[Dict[str, StepOutput]] = None,
    ) -> Optional[Union[str, List[Any], Dict[str, Any], BaseModel]]:
        """Prepare the primary input by combining message and previous step outputs"""

        if previous_step_outputs and self._executor_type in ["agent", "team", "workflow"]:
            last_output = list(previous_step_outputs.values())[-1] if previous_step_outputs else None
            if last_output:
                deepest_content = self._get_deepest_content_from_step_output(last_output)
                if deepest_content:
                    return deepest_content

        # If no previous step outputs, return the original message unchanged
        return message

    def _create_executor_step_requirement(
        self,
        step_index: int,
        executor_response: Union[RunOutput, TeamRunOutput],
    ) -> StepRequirement:
        """Create a StepRequirement from a paused executor (agent/team) response.

        This propagates tool-level HITL requirements from the executor up to the workflow level,
        similar to how teams propagate member pauses via _propagate_member_pause().
        """
        executor_id = getattr(self.active_executor, "id", None) or getattr(self.active_executor, "agent_id", None)
        executor_name = getattr(self.active_executor, "name", None)
        executor_type = ExecutorType.TEAM if isinstance(self.active_executor, Team) else ExecutorType.AGENT

        # Serialize requirements for transport
        serialized_reqs: List[Any] = []
        if executor_response.requirements:
            for req in executor_response.requirements:
                serialized_reqs.append(req.to_dict() if hasattr(req, "to_dict") else req)

        return StepRequirement(
            step_id=self.step_id or str(uuid4()),
            step_name=self.name,
            step_index=step_index,
            step_type=StepType.STEP,
            requires_executor_input=True,
            executor_requirements=serialized_reqs,
            executor_id=executor_id,
            executor_name=executor_name,
            executor_run_id=executor_response.run_id,
            executor_type=executor_type,
            executor_session_id=getattr(executor_response, "session_id", None),
        )

    def _process_step_output(self, response: Union[RunOutput, TeamRunOutput, StepOutput]) -> StepOutput:
        """Create StepOutput from execution response"""
        if isinstance(response, StepOutput):
            response.step_name = self.name or "unnamed_step"
            response.step_id = self.step_id
            # Preserve step_type if already set (e.g., for workflow steps), otherwise default to STEP
            if response.step_type is None:
                response.step_type = StepType.STEP
            response.executor_type = self._executor_type
            response.executor_name = self.executor_name
            return response

        # Extract media from response
        images = getattr(response, "images", None)
        videos = getattr(response, "videos", None)
        audio = getattr(response, "audio", None)
        files = getattr(response, "files", None)

        # Extract metrics from response
        metrics = self._extract_metrics_from_response(response)

        # Determine step type based on executor type
        step_type = StepType.WORKFLOW if self._executor_type == "workflow" else StepType.STEP

        return StepOutput(
            step_name=self.name or "unnamed_step",
            step_id=self.step_id,
            step_type=step_type,
            executor_type=self._executor_type,
            executor_name=self.executor_name,
            content=response.content,
            step_run_id=getattr(response, "run_id", None),
            images=images,
            videos=videos,
            audio=audio,
            files=files,
            metrics=metrics,
        )

    def _convert_function_result_to_response(self, result: Any) -> RunOutput:
        """Convert function execution result to RunOutput"""
        if isinstance(result, RunOutput):
            return result
        elif isinstance(result, str):
            return RunOutput(content=result)
        elif isinstance(result, dict):
            # If it's a dict, try to extract content
            content = result.get("content", str(result))
            return RunOutput(content=content)
        else:
            # Convert any other type to string
            return RunOutput(content=str(result))

    def _convert_audio_artifacts_to_audio(self, audio_artifacts: List[Audio]) -> List[Audio]:
        """Convert AudioArtifact objects to Audio objects"""
        audios = []
        for audio_artifact in audio_artifacts:
            if audio_artifact.url:
                audios.append(Audio(url=audio_artifact.url))
            elif audio_artifact.content:
                audios.append(Audio(content=audio_artifact.content))
            else:
                logger.warning(f"Skipping AudioArtifact with no URL or content: {audio_artifact}")
                continue
        return audios

    # --- Nested Workflow Execution Methods ---

    def _convert_workflow_step_results_to_step_outputs(self, step_results: List[Any]) -> List[StepOutput]:
        """Convert nested workflow step results to StepOutput objects for nesting"""
        nested_steps = []
        for step_result in step_results:
            if isinstance(step_result, StepOutput):
                nested_steps.append(step_result)
            elif isinstance(step_result, list):
                # Handle List[StepOutput] from workflow components like Steps
                for s in step_result:
                    if isinstance(s, StepOutput):
                        nested_steps.append(s)
        return nested_steps

    @staticmethod
    def _aggregate_workflow_metrics(workflow_metrics: Any) -> Optional[RunMetrics]:
        """Aggregate a WorkflowMetrics into a single RunMetrics by summing all step metrics.

        WorkflowMetrics contains per-step StepMetrics (each wrapping a RunMetrics).
        This aggregates them into one RunMetrics so it fits into StepOutput.metrics.
        """
        from agno.workflow.types import WorkflowMetrics as WFMetrics

        if workflow_metrics is None or not isinstance(workflow_metrics, WFMetrics):
            return None

        aggregated = RunMetrics()
        if workflow_metrics.duration is not None:
            aggregated.duration = workflow_metrics.duration

        has_step_metrics = False
        for step_metric in workflow_metrics.steps.values():
            if step_metric.metrics is not None:
                has_step_metrics = True
                aggregated = aggregated + step_metric.metrics

        # Return aggregated metrics if any step had metrics or if duration is set
        if has_step_metrics or aggregated.duration is not None:
            return aggregated
        return None

    def _execute_nested_workflow(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Execute a nested workflow as a step (non-streaming)"""
        from agno.workflow.workflow import Workflow

        if not isinstance(self.workflow, Workflow):
            raise ValueError("Workflow executor is not a Workflow instance")

        # Guard against circular or excessively deep nesting
        current_depth = _nested_workflow_depth.get()
        if current_depth >= _MAX_NESTED_WORKFLOW_DEPTH:
            raise ValueError(
                f"Step '{self.name}': Maximum nested workflow depth ({_MAX_NESTED_WORKFLOW_DEPTH}) exceeded. "
                "This may indicate circular workflow nesting."
            )
        _nested_workflow_depth.set(current_depth + 1)

        try:
            return self._execute_nested_workflow_inner(
                step_input=step_input,
                session_id=session_id,
                user_id=user_id,
                workflow_run_response=workflow_run_response,
                session_state=session_state,
                store_executor_outputs=store_executor_outputs,
                background_tasks=background_tasks,
            )
        finally:
            _nested_workflow_depth.set(current_depth)

    def _execute_nested_workflow_inner(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Inner implementation of sync non-streaming nested workflow execution"""
        from agno.workflow.workflow import Workflow

        if not isinstance(self.workflow, Workflow):
            raise ValueError("Workflow executor is not a Workflow instance")

        # Prepare the input message
        message = self._prepare_message(step_input.input, step_input.previous_step_outputs)

        log_debug(f"Executing nested workflow: {self.workflow.name}")

        # Execute the nested workflow with shared session
        nested_run_output: WorkflowRunOutput = self.workflow.run(
            input=message,
            session_id=session_id,  # Share the parent's session_id
            user_id=user_id,
            session_state=session_state,  # Pass the session_state copy
            images=step_input.images,
            videos=step_input.videos,
            audio=step_input.audio,
            files=step_input.files,
            stream=False,
            background_tasks=background_tasks,
        )

        # Warn if the nested workflow paused (e.g., due to HITL on an inner step)
        if nested_run_output.is_paused:
            logger.warning(
                f"Step '{self.name}': Nested workflow '{self.workflow.name}' is paused "
                "(likely due to HITL on an inner step). The parent workflow will continue "
                "but the paused inner step may not have executed."
            )

        # Store the nested workflow run in step_executor_runs if enabled
        if store_executor_outputs and workflow_run_response is not None:
            nested_run_output.parent_run_id = workflow_run_response.run_id
            nested_run_output.workflow_step_id = self.step_id

            if workflow_run_response.step_executor_runs is None:
                workflow_run_response.step_executor_runs = []
            # Clear events from nested output before storing to avoid duplicating
            # data that is already captured at the outer workflow level.
            nested_run_output.events = None
            workflow_run_response.step_executor_runs.append(nested_run_output)

        # Convert nested workflow's step_results to nested StepOutput objects
        nested_steps = self._convert_workflow_step_results_to_step_outputs(nested_run_output.step_results)

        # Create StepOutput from the nested workflow run with nested steps
        return StepOutput(
            step_name=self.name,
            step_id=self.step_id,
            step_type=StepType.WORKFLOW,
            executor_type="workflow",
            executor_name=self.workflow.name,
            content=nested_run_output.content,
            step_run_id=nested_run_output.run_id,
            metrics=self._aggregate_workflow_metrics(nested_run_output.metrics),
            success=nested_run_output.status != RunStatus.error,
            error=nested_run_output.error if hasattr(nested_run_output, "error") else None,
            steps=nested_steps if nested_steps else None,  # Include nested workflow's step results
        )

    def _execute_nested_workflow_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        stream_events: bool = False,
        background_tasks: Optional[Any] = None,
    ) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Execute a nested workflow as a step with streaming"""
        from agno.workflow.workflow import Workflow

        if not isinstance(self.workflow, Workflow):
            raise ValueError("Workflow executor is not a Workflow instance")

        # Guard against circular or excessively deep nesting
        current_depth = _nested_workflow_depth.get()
        if current_depth >= _MAX_NESTED_WORKFLOW_DEPTH:
            raise ValueError(
                f"Step '{self.name}': Maximum nested workflow depth ({_MAX_NESTED_WORKFLOW_DEPTH}) exceeded. "
                "This may indicate circular workflow nesting."
            )
        _nested_workflow_depth.set(current_depth + 1)

        try:
            yield from self._execute_nested_workflow_stream_inner(
                step_input=step_input,
                session_id=session_id,
                user_id=user_id,
                workflow_run_response=workflow_run_response,
                session_state=session_state,
                store_executor_outputs=store_executor_outputs,
                stream_events=stream_events,
                background_tasks=background_tasks,
            )
        finally:
            _nested_workflow_depth.set(current_depth)

    def _execute_nested_workflow_stream_inner(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        stream_events: bool = False,
        background_tasks: Optional[Any] = None,
    ) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Inner implementation of sync streaming nested workflow execution"""
        from agno.run.workflow import WorkflowCompletedEvent
        from agno.workflow.workflow import Workflow

        if not isinstance(self.workflow, Workflow):
            raise ValueError("Workflow executor is not a Workflow instance")

        # Prepare the input message
        message = self._prepare_message(step_input.input, step_input.previous_step_outputs)

        log_debug(f"Executing nested workflow (streaming): {self.workflow.name}")

        # Execute the nested workflow with streaming
        # Capture the WorkflowCompletedEvent to get the final results
        completed_event: Optional[WorkflowCompletedEvent] = None
        for event in self.workflow.run(
            input=message,
            session_id=session_id,  # Share the parent's session_id
            user_id=user_id,
            session_state=session_state,
            images=step_input.images,
            videos=step_input.videos,
            audio=step_input.audio,
            files=step_input.files,
            stream=True,
            stream_events=stream_events,
            background_tasks=background_tasks,
        ):
            # Capture the WorkflowCompletedEvent which contains step_results
            if isinstance(event, WorkflowCompletedEvent):
                completed_event = event
            # Yield events from nested workflow
            yield event

        # Get the nested run output from the completed event (preferred) or from session
        nested_run_output: Optional[WorkflowRunOutput] = None
        if completed_event and completed_event.run_output:
            nested_run_output = completed_event.run_output
        elif self.workflow.session_id:
            session = self.workflow.get_session(session_id=self.workflow.session_id)
            if session and session.runs:
                nested_run_output = session.runs[-1]

        if nested_run_output is None:
            log_warning(
                f"Step '{self.name}': Nested workflow '{self.workflow.name}' did not produce a run output. "
                "The workflow may have failed before completion."
            )

        # Warn if the nested workflow paused (e.g., due to HITL on an inner step)
        if nested_run_output is not None and nested_run_output.is_paused:
            logger.warning(
                f"Step '{self.name}': Nested workflow '{self.workflow.name}' is paused "
                "(likely due to HITL on an inner step). The parent workflow will continue "
                "but the paused inner step may not have executed."
            )

        # Store the nested workflow run in step_executor_runs if enabled
        if store_executor_outputs and workflow_run_response is not None and nested_run_output is not None:
            nested_run_output.parent_run_id = workflow_run_response.run_id
            nested_run_output.workflow_step_id = self.step_id

            if workflow_run_response.step_executor_runs is None:
                workflow_run_response.step_executor_runs = []
            # Clear events from nested output before storing to avoid duplicating
            # data that is already captured at the outer workflow level.
            nested_run_output.events = None
            workflow_run_response.step_executor_runs.append(nested_run_output)

        # Get nested steps from the nested_run_output or from the completed event
        nested_steps: Optional[List[StepOutput]] = None
        if nested_run_output is not None and nested_run_output.step_results:
            nested_steps = self._convert_workflow_step_results_to_step_outputs(nested_run_output.step_results)
        elif completed_event and completed_event.step_results:
            nested_steps = self._convert_workflow_step_results_to_step_outputs(completed_event.step_results)

        # Yield the final StepOutput
        yield StepOutput(
            step_name=self.name,
            step_id=self.step_id,
            step_type=StepType.WORKFLOW,
            executor_type="workflow",
            executor_name=self.workflow.name,
            content=nested_run_output.content
            if nested_run_output is not None
            else (completed_event.content if completed_event else None),
            step_run_id=nested_run_output.run_id if nested_run_output is not None else None,
            metrics=self._aggregate_workflow_metrics(nested_run_output.metrics)
            if nested_run_output is not None
            else None,
            success=nested_run_output.status != RunStatus.error if nested_run_output is not None else False,
            error=nested_run_output.error
            if nested_run_output is not None and hasattr(nested_run_output, "error")
            else None,
            steps=nested_steps if nested_steps else None,
        )

    async def _aexecute_nested_workflow(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Execute a nested workflow as a step asynchronously (non-streaming)"""
        from agno.workflow.workflow import Workflow

        if not isinstance(self.workflow, Workflow):
            raise ValueError("Workflow executor is not a Workflow instance")

        # Guard against circular or excessively deep nesting
        current_depth = _nested_workflow_depth.get()
        if current_depth >= _MAX_NESTED_WORKFLOW_DEPTH:
            raise ValueError(
                f"Step '{self.name}': Maximum nested workflow depth ({_MAX_NESTED_WORKFLOW_DEPTH}) exceeded. "
                "This may indicate circular workflow nesting."
            )
        _nested_workflow_depth.set(current_depth + 1)

        try:
            return await self._aexecute_nested_workflow_inner(
                step_input=step_input,
                session_id=session_id,
                user_id=user_id,
                workflow_run_response=workflow_run_response,
                session_state=session_state,
                store_executor_outputs=store_executor_outputs,
                background_tasks=background_tasks,
            )
        finally:
            _nested_workflow_depth.set(current_depth)

    async def _aexecute_nested_workflow_inner(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Inner implementation of async non-streaming nested workflow execution"""
        from agno.workflow.workflow import Workflow

        if not isinstance(self.workflow, Workflow):
            raise ValueError("Workflow executor is not a Workflow instance")

        # Prepare the input message
        message = self._prepare_message(step_input.input, step_input.previous_step_outputs)

        log_debug(f"Executing nested workflow (async): {self.workflow.name}")

        # Execute the nested workflow asynchronously with shared session
        nested_run_output: WorkflowRunOutput = await self.workflow.arun(
            input=message,
            session_id=session_id,  # Share the parent's session_id
            user_id=user_id,
            session_state=session_state,
            images=step_input.images,
            videos=step_input.videos,
            audio=step_input.audio,
            files=step_input.files,
            stream=False,
            background_tasks=background_tasks,
        )

        # Warn if the nested workflow paused (e.g., due to HITL on an inner step)
        if nested_run_output.is_paused:
            logger.warning(
                f"Step '{self.name}': Nested workflow '{self.workflow.name}' is paused "
                "(likely due to HITL on an inner step). The parent workflow will continue "
                "but the paused inner step may not have executed."
            )

        # Store the nested workflow run in step_executor_runs if enabled
        if store_executor_outputs and workflow_run_response is not None:
            nested_run_output.parent_run_id = workflow_run_response.run_id
            nested_run_output.workflow_step_id = self.step_id

            if workflow_run_response.step_executor_runs is None:
                workflow_run_response.step_executor_runs = []
            # Clear events from nested output before storing to avoid duplicating
            # data that is already captured at the outer workflow level.
            nested_run_output.events = None
            workflow_run_response.step_executor_runs.append(nested_run_output)

        # Convert nested workflow's step_results to nested StepOutput objects
        nested_steps = self._convert_workflow_step_results_to_step_outputs(nested_run_output.step_results)

        # Create StepOutput from the nested workflow run with nested steps
        return StepOutput(
            step_name=self.name,
            step_id=self.step_id,
            step_type=StepType.WORKFLOW,
            executor_type="workflow",
            executor_name=self.workflow.name,
            content=nested_run_output.content,
            step_run_id=nested_run_output.run_id,
            metrics=self._aggregate_workflow_metrics(nested_run_output.metrics),
            success=nested_run_output.status != RunStatus.error,
            error=nested_run_output.error if hasattr(nested_run_output, "error") else None,
            steps=nested_steps if nested_steps else None,  # Include nested workflow's step results
        )

    async def _aexecute_nested_workflow_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        stream_events: bool = False,
        background_tasks: Optional[Any] = None,
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Execute a nested workflow as a step with async streaming"""
        from agno.workflow.workflow import Workflow

        if not isinstance(self.workflow, Workflow):
            raise ValueError("Workflow executor is not a Workflow instance")

        # Guard against circular or excessively deep nesting
        current_depth = _nested_workflow_depth.get()
        if current_depth >= _MAX_NESTED_WORKFLOW_DEPTH:
            raise ValueError(
                f"Step '{self.name}': Maximum nested workflow depth ({_MAX_NESTED_WORKFLOW_DEPTH}) exceeded. "
                "This may indicate circular workflow nesting."
            )
        _nested_workflow_depth.set(current_depth + 1)

        try:
            async for event in self._aexecute_nested_workflow_stream_inner(
                step_input=step_input,
                session_id=session_id,
                user_id=user_id,
                workflow_run_response=workflow_run_response,
                session_state=session_state,
                store_executor_outputs=store_executor_outputs,
                stream_events=stream_events,
                background_tasks=background_tasks,
            ):
                yield event
        finally:
            _nested_workflow_depth.set(current_depth)

    async def _aexecute_nested_workflow_stream_inner(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        stream_events: bool = False,
        background_tasks: Optional[Any] = None,
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Inner implementation of async streaming nested workflow execution"""
        from agno.run.workflow import WorkflowCompletedEvent
        from agno.workflow.workflow import Workflow

        if not isinstance(self.workflow, Workflow):
            raise ValueError("Workflow executor is not a Workflow instance")

        # Prepare the input message
        message = self._prepare_message(step_input.input, step_input.previous_step_outputs)

        log_debug(f"Executing nested workflow (async streaming): {self.workflow.name}")

        # Execute the nested workflow with async streaming
        # Capture the WorkflowCompletedEvent to get the final results
        completed_event: Optional[WorkflowCompletedEvent] = None
        async for event in self.workflow.arun(
            input=message,
            session_id=session_id,  # Share the parent's session_id
            user_id=user_id,
            session_state=session_state,
            images=step_input.images,
            videos=step_input.videos,
            audio=step_input.audio,
            files=step_input.files,
            stream=True,
            stream_events=stream_events,
            background_tasks=background_tasks,
        ):
            # Capture the WorkflowCompletedEvent which contains step_results
            if isinstance(event, WorkflowCompletedEvent):
                completed_event = event
            # Yield events from nested workflow
            yield event

        # Get the nested run output from the completed event (preferred) or from session
        nested_run_output: Optional[WorkflowRunOutput] = None
        if completed_event and completed_event.run_output:
            nested_run_output = completed_event.run_output
        elif self.workflow.session_id:
            session = await self.workflow.aget_session(session_id=self.workflow.session_id)
            if session and session.runs:
                nested_run_output = session.runs[-1]

        if nested_run_output is None:
            log_warning(
                f"Step '{self.name}': Nested workflow '{self.workflow.name}' did not produce a run output. "
                "The workflow may have failed before completion."
            )

        # Warn if the nested workflow paused (e.g., due to HITL on an inner step)
        if nested_run_output is not None and nested_run_output.is_paused:
            logger.warning(
                f"Step '{self.name}': Nested workflow '{self.workflow.name}' is paused "
                "(likely due to HITL on an inner step). The parent workflow will continue "
                "but the paused inner step may not have executed."
            )

        # Store the nested workflow run in step_executor_runs if enabled
        if store_executor_outputs and workflow_run_response is not None and nested_run_output is not None:
            nested_run_output.parent_run_id = workflow_run_response.run_id
            nested_run_output.workflow_step_id = self.step_id

            if workflow_run_response.step_executor_runs is None:
                workflow_run_response.step_executor_runs = []
            # Clear events from nested output before storing to avoid duplicating
            # data that is already captured at the outer workflow level.
            nested_run_output.events = None
            workflow_run_response.step_executor_runs.append(nested_run_output)

        # Get nested steps from the nested_run_output or from the completed event
        nested_steps: Optional[List[StepOutput]] = None
        if nested_run_output is not None and nested_run_output.step_results:
            nested_steps = self._convert_workflow_step_results_to_step_outputs(nested_run_output.step_results)
        elif completed_event and completed_event.step_results:
            nested_steps = self._convert_workflow_step_results_to_step_outputs(completed_event.step_results)

        # Yield the final StepOutput
        yield StepOutput(
            step_name=self.name,
            step_id=self.step_id,
            step_type=StepType.WORKFLOW,
            executor_type="workflow",
            executor_name=self.workflow.name,
            content=nested_run_output.content
            if nested_run_output is not None
            else (completed_event.content if completed_event else None),
            step_run_id=nested_run_output.run_id if nested_run_output is not None else None,
            metrics=self._aggregate_workflow_metrics(nested_run_output.metrics)
            if nested_run_output is not None
            else None,
            success=nested_run_output.status != RunStatus.error if nested_run_output is not None else False,
            error=nested_run_output.error
            if nested_run_output is not None and hasattr(nested_run_output, "error")
            else None,
            steps=nested_steps if nested_steps else None,
        )

    def _convert_image_artifacts_to_images(self, image_artifacts: List[Image]) -> List[Image]:
        """
        Convert ImageArtifact objects to Image objects with proper content handling.

        Args:
            image_artifacts: List of ImageArtifact objects to convert

        Returns:
            List of Image objects ready for agent processing
        """
        import base64
        import binascii

        images = []
        for i, img_artifact in enumerate(image_artifacts):
            # Create Image object with proper data from ImageArtifact
            if img_artifact.url:
                images.append(Image(url=img_artifact.url))

            elif img_artifact.filepath:
                # Pass through filepath-based images directly
                image_kwargs: Dict[str, Any] = {"filepath": img_artifact.filepath}
                if img_artifact.format:
                    image_kwargs["format"] = img_artifact.format
                if img_artifact.mime_type:
                    if "/" in img_artifact.mime_type:
                        format_from_mime = img_artifact.mime_type.split("/")[-1]
                        image_kwargs.setdefault("format", format_from_mime)
                images.append(Image(**image_kwargs))

            elif img_artifact.content:
                # Handle the case where content is base64-encoded bytes from OpenAI tools
                try:
                    # Try to decode as base64 first (for images from OpenAI tools)
                    if isinstance(img_artifact.content, bytes):
                        try:
                            # Attempt UTF-8 decode in case bytes are base64-encoded text
                            base64_str: str = img_artifact.content.decode("utf-8")
                            actual_image_bytes = base64.b64decode(base64_str)
                        except (UnicodeDecodeError, binascii.Error):
                            # Raw image bytes (e.g., from Telegram, WhatsApp, or file uploads)
                            actual_image_bytes = img_artifact.content
                    else:
                        # If it's already actual image bytes
                        actual_image_bytes = img_artifact.content

                    # Create Image object with proper format
                    image_kwargs = {"content": actual_image_bytes}
                    if img_artifact.mime_type:
                        # Convert mime_type to format (e.g., "image/png" -> "png")
                        if "/" in img_artifact.mime_type:
                            format_from_mime = img_artifact.mime_type.split("/")[-1]
                            image_kwargs["format"] = format_from_mime  # type: ignore[assignment]

                    images.append(Image(**image_kwargs))

                except Exception:
                    logger.exception("Failed to process image content")
                    # Skip this image if we can't process it
                    continue

            else:
                # Skip images that have neither URL, filepath, nor content
                logger.warning(f"Skipping ImageArtifact {i} with no URL, filepath, or content: {img_artifact}")
                continue

        return images

    def _convert_video_artifacts_to_videos(self, video_artifacts: List[Video]) -> List[Video]:
        """
        Convert VideoArtifact objects to Video objects with proper content handling.

        Args:
            video_artifacts: List of VideoArtifact objects to convert

        Returns:
            List of Video objects ready for agent processing
        """
        videos = []
        for i, video_artifact in enumerate(video_artifacts):
            # Create Video object with proper data from VideoArtifact
            if video_artifact.url:
                videos.append(Video(url=video_artifact.url))

            elif video_artifact.filepath:
                videos.append(Video(filepath=video_artifact.filepath))

            elif video_artifact.content:
                videos.append(Video(content=video_artifact.content))

            else:
                # Skip videos that have neither URL, filepath, nor content
                logger.warning(f"Skipping VideoArtifact {i} with no URL, filepath, or content: {video_artifact}")
                continue

        return videos


def _is_async_callable(obj: Any) -> TypeGuard[Callable[..., Any]]:
    """Checks if obj is an async callable (coroutine function or callable with async __call__)"""
    return inspect.iscoroutinefunction(obj) or (callable(obj) and inspect.iscoroutinefunction(obj.__call__))


def _is_generator_function(obj: Any) -> TypeGuard[Callable[..., Any]]:
    """Checks if obj is a generator function, including callable class instances with generator __call__ methods"""
    if inspect.isgeneratorfunction(obj):
        return True
    # Check if it's a callable class instance with a generator __call__ method
    if callable(obj) and hasattr(obj, "__call__"):
        return inspect.isgeneratorfunction(obj.__call__)
    return False


def _is_async_generator_function(obj: Any) -> TypeGuard[Callable[..., Any]]:
    """Checks if obj is an async generator function, including callable class instances"""
    if inspect.isasyncgenfunction(obj):
        return True
    # Check if it's a callable class instance with an async generator __call__ method
    if callable(obj) and hasattr(obj, "__call__"):
        return inspect.isasyncgenfunction(obj.__call__)
    return False
