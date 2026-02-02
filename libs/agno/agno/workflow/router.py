import inspect
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union
from uuid import uuid4

from agno.registry import Registry
from agno.run.agent import RunOutputEvent
from agno.run.base import RunContext
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import (
    RouterExecutionCompletedEvent,
    RouterExecutionStartedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
)
from agno.session.workflow import WorkflowSession
from agno.utils.log import log_debug, logger
from agno.workflow.cel import CEL_AVAILABLE, evaluate_cel_router_selector, is_cel_expression
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput, StepType

WorkflowSteps = List[
    Union[
        Callable[
            [StepInput], Union[StepOutput, Awaitable[StepOutput], Iterator[StepOutput], AsyncIterator[StepOutput]]
        ],
        Step,
        "Steps",  # type: ignore # noqa: F821
        "Loop",  # type: ignore # noqa: F821
        "Parallel",  # type: ignore # noqa: F821
        "Condition",  # type: ignore # noqa: F821
        "Router",  # type: ignore # noqa: F821
    ]
]


@dataclass
class Router:
    """A router that dynamically selects which step(s) to execute based on input.

    The selector can be:
        - A callable function that takes StepInput and returns step(s)
        - A CEL (Common Expression Language) expression string that returns a step name

    CEL expressions for selector have access to (same as Condition, plus step_choices):
        - input: The workflow input as a string
        - previous_step_content: Content from the previous step
        - previous_step_outputs: Map of step name to content string from all previous steps
        - additional_data: Map of additional data passed to the workflow
        - session_state: Map of session state values
        - step_choices: List of step names available to the selector

    CEL expressions must return the name of a step from choices.

    Example CEL expressions:
        - 'input.contains("video") ? "video_step" : "image_step"'
        - 'additional_data.route'
        - 'previous_step_outputs.classifier.contains("billing") ? "Billing" : "Support"'
    """

    # Router function or CEL expression that selects step(s) to execute
    selector: Union[
        Callable[[StepInput], Union[WorkflowSteps, List[WorkflowSteps]]],
        Callable[[StepInput], Awaitable[Union[WorkflowSteps, List[WorkflowSteps]]]],
        str,  # CEL expression returning step name
    ]
    choices: WorkflowSteps  # Available steps that can be selected

    name: Optional[str] = None
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "type": "Router",
            "name": self.name,
            "description": self.description,
            "choices": [step.to_dict() for step in self.choices if hasattr(step, "to_dict")],
        }
        # Serialize selector
        if callable(self.selector):
            result["selector"] = self.selector.__name__
            result["selector_type"] = "function"
        elif isinstance(self.selector, str):
            result["selector"] = self.selector
            result["selector_type"] = "cel"
        else:
            raise ValueError(f"Invalid selector type: {type(self.selector).__name__}")

        return result

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        registry: Optional["Registry"] = None,
        db: Optional[Any] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> "Router":
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.steps import Steps

        def deserialize_step(step_data: Dict[str, Any]) -> Any:
            step_type = step_data.get("type", "Step")
            if step_type == "Loop":
                return Loop.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Parallel":
                return Parallel.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Steps":
                return Steps.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Condition":
                return Condition.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Router":
                return cls.from_dict(step_data, registry=registry, db=db, links=links)
            else:
                return Step.from_dict(step_data, registry=registry, db=db, links=links)

        # Deserialize selector
        selector_data = data.get("selector")
        selector_type = data.get("selector_type")

        selector: Any = None
        if selector_data is None:
            raise ValueError("Router requires a selector")
        elif isinstance(selector_data, str):
            # Determine if this is a CEL expression or a function name
            if selector_type == "cel" or (selector_type is None and is_cel_expression(selector_data)):
                # CEL expression - use as-is
                selector = selector_data
            else:
                # Function name - look up in registry
                if registry:
                    func = registry.get_function(selector_data)
                    if func is None:
                        raise ValueError(f"Selector function '{selector_data}' not found in registry")
                    selector = func
                else:
                    raise ValueError(f"Registry required to deserialize selector function '{selector_data}'")
        else:
            raise ValueError(f"Invalid selector type in data: {type(selector_data).__name__}")

        return cls(
            selector=selector,
            choices=[deserialize_step(step) for step in data.get("choices", [])],
            name=data.get("name"),
            description=data.get("description"),
        )

    def _prepare_single_step(self, step: Any) -> Any:
        """Prepare a single step for execution."""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.step import Step
        from agno.workflow.steps import Steps

        if callable(step) and hasattr(step, "__name__"):
            return Step(name=step.__name__, description="User-defined callable step", executor=step)
        elif isinstance(step, Agent):
            return Step(name=step.name, description=step.description, agent=step)
        elif isinstance(step, Team):
            return Step(name=step.name, description=step.description, team=step)
        elif isinstance(step, (Step, Steps, Loop, Parallel, Condition, Router)):
            return step
        else:
            raise ValueError(f"Invalid step type: {type(step).__name__}")

    def _prepare_steps(self):
        """Prepare the steps for execution - mirrors workflow logic"""
        from agno.workflow.steps import Steps

        prepared_steps: WorkflowSteps = []
        for step in self.choices:
            if isinstance(step, list):
                # Handle nested list of steps - wrap in Steps container
                nested_prepared = [self._prepare_single_step(s) for s in step]
                # Create a Steps container with a generated name
                steps_container = Steps(
                    name=f"steps_group_{len(prepared_steps)}",
                    steps=nested_prepared,
                )
                prepared_steps.append(steps_container)
            else:
                prepared_steps.append(self._prepare_single_step(step))

        self.steps = prepared_steps
        # Build name-to-step mapping for string-based selection (used by CEL and callable selectors)
        self._step_name_map: Dict[str, Any] = {}
        for step in self.steps:
            if hasattr(step, "name") and step.name:
                self._step_name_map[step.name] = step

    def _update_step_input_from_outputs(
        self,
        step_input: StepInput,
        step_outputs: Union[StepOutput, List[StepOutput]],
        router_step_outputs: Optional[Dict[str, StepOutput]] = None,
    ) -> StepInput:
        """Helper to update step input from step outputs - mirrors Loop logic"""
        current_images = step_input.images or []
        current_videos = step_input.videos or []
        current_audio = step_input.audio or []

        if isinstance(step_outputs, list):
            all_images = sum([out.images or [] for out in step_outputs], [])
            all_videos = sum([out.videos or [] for out in step_outputs], [])
            all_audio = sum([out.audio or [] for out in step_outputs], [])
            previous_step_content = step_outputs[-1].content if step_outputs else None
        else:
            all_images = step_outputs.images or []
            all_videos = step_outputs.videos or []
            all_audio = step_outputs.audio or []
            previous_step_content = step_outputs.content

        updated_previous_step_outputs = {}
        if step_input.previous_step_outputs:
            updated_previous_step_outputs.update(step_input.previous_step_outputs)
        if router_step_outputs:
            updated_previous_step_outputs.update(router_step_outputs)

        return StepInput(
            input=step_input.input,
            previous_step_content=previous_step_content,
            previous_step_outputs=updated_previous_step_outputs,
            additional_data=step_input.additional_data,
            images=current_images + all_images,
            videos=current_videos + all_videos,
            audio=current_audio + all_audio,
        )

    def _resolve_selector_result(self, result: Any) -> List[Any]:
        """Resolve selector result to a list of steps, handling strings, Steps, and lists.

        This unified resolver handles:
        - String step names (from CEL expressions or callable selectors)
        - Step objects directly returned by callable selectors
        - Lists of strings or Steps
        """
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.steps import Steps

        if result is None:
            return []

        # Handle string - look up by name in the step_name_map
        if isinstance(result, str):
            if result in self._step_name_map:
                return [self._step_name_map[result]]
            else:
                available_steps = list(self._step_name_map.keys())
                logger.warning(
                    f"Router '{self.name}' selector returned unknown step name: '{result}'. "
                    f"Available step names are: {available_steps}. "
                    f"Make sure the selector returns one of the available step names."
                )
                return []

        # Handle step types (Step, Steps, Loop, Parallel, Condition, Router)
        if isinstance(result, (Step, Steps, Loop, Parallel, Condition, Router)):
            # Validate that the returned step is in the router's choices
            step_name = getattr(result, "name", None)
            if step_name and step_name not in self._step_name_map:
                available_steps = list(self._step_name_map.keys())
                logger.warning(
                    f"Router '{self.name}' selector returned a Step '{step_name}' that is not in choices. "
                    f"Available step names are: {available_steps}. "
                    f"The step will still be executed, but this may indicate a configuration error."
                )
            return [result]

        # Handle list of results (could be strings, Steps, or mixed)
        if isinstance(result, list):
            resolved = []
            for item in result:
                resolved.extend(self._resolve_selector_result(item))
            return resolved

        logger.warning(f"Router selector returned unexpected type: {type(result)}")
        return []

    def _selector_has_step_choices_param(self) -> bool:
        """Check if the selector function has a step_choices parameter"""
        if not callable(self.selector):
            return False

        try:
            sig = inspect.signature(self.selector)
            return "step_choices" in sig.parameters
        except Exception:
            return False

    def _route_steps(self, step_input: StepInput, session_state: Optional[Dict[str, Any]] = None) -> List[Step]:  # type: ignore[return-value]
        """Route to the appropriate steps based on input."""
        # Handle CEL expression selector
        if isinstance(self.selector, str):
            if not CEL_AVAILABLE:
                logger.error(
                    "CEL expression used but cel-python is not installed. Install with: pip install cel-python"
                )
                return []
            try:
                step_names = list(self._step_name_map.keys())
                step_name = evaluate_cel_router_selector(
                    self.selector, step_input, session_state, step_choices=step_names
                )
                return self._resolve_selector_result(step_name)
            except Exception as e:
                logger.error(f"Router CEL evaluation failed: {e}")
                return []

        # Handle callable selector
        if callable(self.selector):
            has_session_state = session_state is not None and self._selector_has_session_state_param()
            has_step_choices = self._selector_has_step_choices_param()

            # Build kwargs based on what parameters the selector accepts
            kwargs: Dict[str, Any] = {}
            if has_session_state:
                kwargs["session_state"] = session_state
            if has_step_choices:
                kwargs["step_choices"] = self.steps

            result = self.selector(step_input, **kwargs)  # type: ignore[call-arg]

            return self._resolve_selector_result(result)

        return []

    async def _aroute_steps(self, step_input: StepInput, session_state: Optional[Dict[str, Any]] = None) -> List[Step]:  # type: ignore[return-value]
        """Async version of step routing."""
        # Handle CEL expression selector (CEL evaluation is synchronous)
        if isinstance(self.selector, str):
            if not CEL_AVAILABLE:
                logger.error(
                    "CEL expression used but cel-python is not installed. Install with: pip install cel-python"
                )
                return []
            try:
                step_names = list(self._step_name_map.keys())
                step_name = evaluate_cel_router_selector(
                    self.selector, step_input, session_state, step_choices=step_names
                )
                return self._resolve_selector_result(step_name)
            except Exception as e:
                logger.error(f"Router CEL evaluation failed: {e}")
                return []

        # Handle callable selector
        if callable(self.selector):
            has_session_state = session_state is not None and self._selector_has_session_state_param()
            has_step_choices = self._selector_has_step_choices_param()

            # Build kwargs based on what parameters the selector accepts
            kwargs: Dict[str, Any] = {}
            if has_session_state:
                kwargs["session_state"] = session_state
            if has_step_choices:
                kwargs["step_choices"] = self.steps

            if inspect.iscoroutinefunction(self.selector):
                result = await self.selector(step_input, **kwargs)  # type: ignore[call-arg]
            else:
                result = self.selector(step_input, **kwargs)  # type: ignore[call-arg]

            return self._resolve_selector_result(result)

        return []

    def _selector_has_session_state_param(self) -> bool:
        """Check if the selector function has a session_state parameter."""
        if not callable(self.selector):
            return False

        try:
            sig = inspect.signature(self.selector)
            return "session_state" in sig.parameters
        except Exception:
            return False

    def execute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Execute the router and its selected steps with sequential chaining"""
        log_debug(f"Router Start: {self.name}", center=True, symbol="-")

        router_step_id = str(uuid4())

        self._prepare_steps()

        # Route to appropriate steps
        if run_context is not None and run_context.session_state is not None:
            steps_to_execute = self._route_steps(step_input, session_state=run_context.session_state)
        else:
            steps_to_execute = self._route_steps(step_input, session_state=session_state)
        log_debug(f"Router {self.name}: Selected {len(steps_to_execute)} steps to execute")

        if not steps_to_execute:
            return StepOutput(
                step_name=self.name,
                step_id=router_step_id,
                step_type=StepType.ROUTER,
                content=f"Router {self.name} completed with 0 results (no steps selected)",
                success=True,
            )

        all_results: List[StepOutput] = []
        current_step_input = step_input
        router_step_outputs = {}

        for i, step in enumerate(steps_to_execute):
            try:
                step_output = step.execute(
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    workflow_run_response=workflow_run_response,
                    store_executor_outputs=store_executor_outputs,
                    run_context=run_context,
                    session_state=session_state,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    background_tasks=background_tasks,
                )

                # Handle both single StepOutput and List[StepOutput]
                if isinstance(step_output, list):
                    all_results.extend(step_output)
                    if step_output:
                        step_name = getattr(step, "name", f"step_{i}")
                        router_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by step {step_name}")
                            break
                else:
                    all_results.append(step_output)
                    step_name = getattr(step, "name", f"step_{i}")
                    router_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by step {step_name}")
                        break

                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, router_step_outputs
                )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Router step {step_name} failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break

        log_debug(f"Router End: {self.name} ({len(all_results)} results)", center=True, symbol="-")

        return StepOutput(
            step_name=self.name,
            step_id=router_step_id,
            step_type=StepType.ROUTER,
            content=f"Router {self.name} completed with {len(all_results)} results",
            success=all(result.success for result in all_results) if all_results else True,
            stop=any(result.stop for result in all_results) if all_results else False,
            steps=all_results,
        )

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Execute the router with streaming support"""
        log_debug(f"Router Start: {self.name}", center=True, symbol="-")

        self._prepare_steps()

        router_step_id = str(uuid4())

        # Route to appropriate steps
        if run_context is not None and run_context.session_state is not None:
            steps_to_execute = self._route_steps(step_input, session_state=run_context.session_state)
        else:
            steps_to_execute = self._route_steps(step_input, session_state=session_state)
        log_debug(f"Router {self.name}: Selected {len(steps_to_execute)} steps to execute")

        if stream_events and workflow_run_response:
            # Yield router started event
            yield RouterExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                selected_steps=[getattr(step, "name", f"step_{i}") for i, step in enumerate(steps_to_execute)],
                step_id=router_step_id,
                parent_step_id=parent_step_id,
            )

        if not steps_to_execute:
            # Yield router completed event for empty case
            if stream_events and workflow_run_response:
                yield RouterExecutionCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    selected_steps=[],
                    executed_steps=0,
                    step_results=[],
                    step_id=router_step_id,
                    parent_step_id=parent_step_id,
                )
            return

        all_results = []
        current_step_input = step_input
        router_step_outputs = {}

        for i, step in enumerate(steps_to_execute):
            try:
                step_outputs_for_step = []
                # Stream step execution
                for event in step.execute_stream(
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_events=stream_events,
                    stream_executor_events=stream_executor_events,
                    workflow_run_response=workflow_run_response,
                    step_index=step_index,
                    store_executor_outputs=store_executor_outputs,
                    run_context=run_context,
                    session_state=session_state,
                    parent_step_id=router_step_id,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    background_tasks=background_tasks,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_step.append(event)
                        all_results.append(event)
                    else:
                        # Yield other events (streaming content, step events, etc.)
                        yield event

                step_name = getattr(step, "name", f"step_{i}")
                log_debug(f"Router step {step_name} streaming completed")

                if step_outputs_for_step:
                    if len(step_outputs_for_step) == 1:
                        router_step_outputs[step_name] = step_outputs_for_step[0]

                        if step_outputs_for_step[0].stop:
                            logger.info(f"Early termination requested by step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step[0], router_step_outputs
                        )
                    else:
                        # Use last output
                        router_step_outputs[step_name] = step_outputs_for_step[-1]

                        if any(output.stop for output in step_outputs_for_step):
                            logger.info(f"Early termination requested by step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step, router_step_outputs
                        )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Router step {step_name} streaming failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break

        log_debug(f"Router End: {self.name} ({len(all_results)} results)", center=True, symbol="-")

        if stream_events and workflow_run_response:
            # Yield router completed event
            yield RouterExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                selected_steps=[getattr(step, "name", f"step_{i}") for i, step in enumerate(steps_to_execute)],
                executed_steps=len(steps_to_execute),
                step_results=all_results,
                step_id=router_step_id,
                parent_step_id=parent_step_id,
            )

        yield StepOutput(
            step_name=self.name,
            step_id=router_step_id,
            step_type=StepType.ROUTER,
            content=f"Router {self.name} completed with {len(all_results)} results",
            success=all(result.success for result in all_results) if all_results else True,
            stop=any(result.stop for result in all_results) if all_results else False,
            steps=all_results,
        )

    async def aexecute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Async execute the router and its selected steps with sequential chaining"""
        log_debug(f"Router Start: {self.name}", center=True, symbol="-")

        router_step_id = str(uuid4())

        self._prepare_steps()

        # Route to appropriate steps
        if run_context is not None and run_context.session_state is not None:
            steps_to_execute = await self._aroute_steps(step_input, session_state=run_context.session_state)
        else:
            steps_to_execute = await self._aroute_steps(step_input, session_state=session_state)
        log_debug(f"Router {self.name} selected: {len(steps_to_execute)} steps to execute")

        if not steps_to_execute:
            return StepOutput(
                step_name=self.name,
                step_id=router_step_id,
                step_type=StepType.ROUTER,
                content=f"Router {self.name} completed with 0 results (no steps selected)",
                success=True,
            )

        # Chain steps sequentially like Loop does
        all_results: List[StepOutput] = []
        current_step_input = step_input
        router_step_outputs = {}

        for i, step in enumerate(steps_to_execute):
            try:
                step_output = await step.aexecute(
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    workflow_run_response=workflow_run_response,
                    store_executor_outputs=store_executor_outputs,
                    run_context=run_context,
                    session_state=session_state,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    background_tasks=background_tasks,
                )
                # Handle both single StepOutput and List[StepOutput]
                if isinstance(step_output, list):
                    all_results.extend(step_output)
                    if step_output:
                        step_name = getattr(step, "name", f"step_{i}")
                        router_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by step {step_name}")
                            break
                else:
                    all_results.append(step_output)
                    step_name = getattr(step, "name", f"step_{i}")
                    router_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by step {step_name}")
                        break

                step_name = getattr(step, "name", f"step_{i}")
                log_debug(f"Router step {step_name} async completed")

                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, router_step_outputs
                )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Router step {step_name} async failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break  # Stop on first error

        log_debug(f"Router End: {self.name} ({len(all_results)} results)", center=True, symbol="-")

        return StepOutput(
            step_name=self.name,
            step_id=router_step_id,
            step_type=StepType.ROUTER,
            content=f"Router {self.name} completed with {len(all_results)} results",
            success=all(result.success for result in all_results) if all_results else True,
            stop=any(result.stop for result in all_results) if all_results else False,
            steps=all_results,
        )

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, TeamRunOutputEvent, RunOutputEvent, StepOutput]]:
        """Async execute the router with streaming support"""
        log_debug(f"Router Start: {self.name}", center=True, symbol="-")

        self._prepare_steps()

        router_step_id = str(uuid4())

        # Route to appropriate steps
        if run_context is not None and run_context.session_state is not None:
            steps_to_execute = await self._aroute_steps(step_input, session_state=run_context.session_state)
        else:
            steps_to_execute = await self._aroute_steps(step_input, session_state=session_state)
        log_debug(f"Router {self.name} selected: {len(steps_to_execute)} steps to execute")

        if stream_events and workflow_run_response:
            # Yield router started event
            yield RouterExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                selected_steps=[getattr(step, "name", f"step_{i}") for i, step in enumerate(steps_to_execute)],
                step_id=router_step_id,
                parent_step_id=parent_step_id,
            )

        if not steps_to_execute:
            if stream_events and workflow_run_response:
                # Yield router completed event for empty case
                yield RouterExecutionCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    selected_steps=[],
                    executed_steps=0,
                    step_results=[],
                    step_id=router_step_id,
                    parent_step_id=parent_step_id,
                )
            return

        # Chain steps sequentially like Loop does
        all_results = []
        current_step_input = step_input
        router_step_outputs = {}

        for i, step in enumerate(steps_to_execute):
            try:
                step_outputs_for_step = []

                # Stream step execution - mirroring Loop logic
                async for event in step.aexecute_stream(
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_events=stream_events,
                    stream_executor_events=stream_executor_events,
                    workflow_run_response=workflow_run_response,
                    step_index=step_index,
                    store_executor_outputs=store_executor_outputs,
                    run_context=run_context,
                    session_state=session_state,
                    parent_step_id=router_step_id,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    background_tasks=background_tasks,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_step.append(event)
                        all_results.append(event)
                    else:
                        # Yield other events (streaming content, step events, etc.)
                        yield event

                step_name = getattr(step, "name", f"step_{i}")
                log_debug(f"Router step {step_name} async streaming completed")

                if step_outputs_for_step:
                    if len(step_outputs_for_step) == 1:
                        router_step_outputs[step_name] = step_outputs_for_step[0]

                        if step_outputs_for_step[0].stop:
                            logger.info(f"Early termination requested by step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step[0], router_step_outputs
                        )
                    else:
                        # Use last output
                        router_step_outputs[step_name] = step_outputs_for_step[-1]

                        if any(output.stop for output in step_outputs_for_step):
                            logger.info(f"Early termination requested by step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step, router_step_outputs
                        )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Router step {step_name} async streaming failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break  # Stop on first error

        log_debug(f"Router End: {self.name} ({len(all_results)} results)", center=True, symbol="-")

        if stream_events and workflow_run_response:
            # Yield router completed event
            yield RouterExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                selected_steps=[getattr(step, "name", f"step_{i}") for i, step in enumerate(steps_to_execute)],
                executed_steps=len(steps_to_execute),
                step_results=all_results,
                step_id=router_step_id,
                parent_step_id=parent_step_id,
            )

        yield StepOutput(
            step_name=self.name,
            step_id=router_step_id,
            step_type=StepType.ROUTER,
            content=f"Router {self.name} completed with {len(all_results)} results",
            success=all(result.success for result in all_results) if all_results else True,
            error=None,
            stop=any(result.stop for result in all_results) if all_results else False,
            steps=all_results,
        )
