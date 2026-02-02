import inspect
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union
from uuid import uuid4

from agno.registry import Registry
from agno.run.agent import RunOutputEvent
from agno.run.base import RunContext
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
)
from agno.session.workflow import WorkflowSession
from agno.utils.log import log_debug, logger
from agno.workflow.cel import CEL_AVAILABLE, evaluate_cel_condition_evaluator, is_cel_expression
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput, StepType

# Constants for condition branch identifiers
CONDITION_BRANCH_IF = "if"
CONDITION_BRANCH_ELSE = "else"

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
class Condition:
    """A condition that executes a step (or list of steps) if the condition is met.

    If the condition evaluates to True, the `steps` are executed.
    If the condition evaluates to False and `else_steps` is provided (and not empty),
    the `else_steps` are executed instead.

    The evaluator can be:
        - A callable function that returns bool
        - A boolean literal (True/False)
        - A CEL (Common Expression Language) expression string

    CEL expressions have access to these variables:
        - input: The workflow input as a string
        - previous_step_content: Content from the previous step
        - previous_step_outputs: Map of step name to content string from all previous steps
        - additional_data: Map of additional data passed to the workflow
        - session_state: Map of session state values

    Example CEL expressions:
        - 'input.contains("urgent")'
        - 'session_state.retry_count < 3'
        - 'additional_data.priority > 5'
        - 'previous_step_outputs.research.contains("error")'
    """

    # Evaluator should only return boolean
    # Can be a callable, a bool, or a CEL expression string
    evaluator: Union[
        Callable[[StepInput], bool],
        Callable[[StepInput], Awaitable[bool]],
        bool,
        str,  # CEL expression
    ]
    steps: WorkflowSteps

    # Steps to execute when condition is False (optional)
    else_steps: Optional[WorkflowSteps] = None

    name: Optional[str] = None
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "type": "Condition",
            "name": self.name,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps if hasattr(step, "to_dict")],
            "else_steps": [step.to_dict() for step in (self.else_steps or []) if hasattr(step, "to_dict")],
        }
        if callable(self.evaluator):
            result["evaluator"] = self.evaluator.__name__
            result["evaluator_type"] = "function"
        elif isinstance(self.evaluator, bool):
            result["evaluator"] = self.evaluator
            result["evaluator_type"] = "bool"
        elif isinstance(self.evaluator, str):
            # CEL expression string
            result["evaluator"] = self.evaluator
            result["evaluator_type"] = "cel"
        else:
            raise ValueError(f"Invalid evaluator type: {type(self.evaluator).__name__}")

        return result

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        registry: Optional["Registry"] = None,
        db: Optional[Any] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> "Condition":
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.router import Router
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
                return cls.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Router":
                return Router.from_dict(step_data, registry=registry, db=db, links=links)
            else:
                return Step.from_dict(step_data, registry=registry, db=db, links=links)

        evaluator_data = data.get("evaluator", True)
        evaluator_type = data.get("evaluator_type")
        evaluator: Union[Callable[[StepInput], bool], Callable[[StepInput], Awaitable[bool]], bool, str]

        if isinstance(evaluator_data, bool):
            evaluator = evaluator_data
        elif isinstance(evaluator_data, str):
            # Determine if this is a CEL expression or a function name
            # Use evaluator_type if provided, otherwise detect
            if evaluator_type == "cel" or (evaluator_type is None and is_cel_expression(evaluator_data)):
                # CEL expression - use as-is
                evaluator = evaluator_data
            else:
                # Function name - look up in registry
                if registry:
                    func = registry.get_function(evaluator_data)
                    if func is None:
                        raise ValueError(f"Evaluator function '{evaluator_data}' not found in registry")
                    evaluator = func
                else:
                    raise ValueError(f"Registry required to deserialize evaluator function '{evaluator_data}'")
        else:
            raise ValueError(f"Invalid evaluator type in data: {type(evaluator_data).__name__}")

        return cls(
            evaluator=evaluator,
            steps=[deserialize_step(step) for step in data.get("steps", [])],
            else_steps=[deserialize_step(step) for step in data.get("else_steps", [])],
            name=data.get("name"),
            description=data.get("description"),
        )

    def _prepare_steps(self):
        """Prepare the steps for execution - mirrors workflow logic"""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.router import Router
        from agno.workflow.step import Step
        from agno.workflow.steps import Steps

        def prepare_step_list(steps: WorkflowSteps) -> WorkflowSteps:
            """Helper to prepare a list of steps."""
            prepared: WorkflowSteps = []
            for step in steps:
                if callable(step) and hasattr(step, "__name__"):
                    prepared.append(Step(name=step.__name__, description="User-defined callable step", executor=step))
                elif isinstance(step, Agent):
                    prepared.append(Step(name=step.name, description=step.description, agent=step))
                elif isinstance(step, Team):
                    prepared.append(Step(name=step.name, description=step.description, team=step))
                elif isinstance(step, (Step, Steps, Loop, Parallel, Condition, Router)):
                    prepared.append(step)
                else:
                    raise ValueError(f"Invalid step type: {type(step).__name__}")
            return prepared

        self.steps = prepare_step_list(self.steps)

        # Also prepare else_steps if provided and not empty
        if self.else_steps and len(self.else_steps) > 0:
            self.else_steps = prepare_step_list(self.else_steps)

    def _update_step_input_from_outputs(
        self,
        step_input: StepInput,
        step_outputs: Union[StepOutput, List[StepOutput]],
        condition_step_outputs: Optional[Dict[str, StepOutput]] = None,
    ) -> StepInput:
        """Helper to update step input from step outputs - mirrors Loop logic"""
        current_images = step_input.images or []
        current_videos = step_input.videos or []
        current_audio = step_input.audio or []

        if isinstance(step_outputs, list):
            all_images = sum([out.images or [] for out in step_outputs], [])
            all_videos = sum([out.videos or [] for out in step_outputs], [])
            all_audio = sum([out.audio or [] for out in step_outputs], [])
            # Use the last output's content for chaining
            previous_step_content = step_outputs[-1].content if step_outputs else None
        else:
            # Single output
            all_images = step_outputs.images or []
            all_videos = step_outputs.videos or []
            all_audio = step_outputs.audio or []
            previous_step_content = step_outputs.content

        updated_previous_step_outputs = {}
        if step_input.previous_step_outputs:
            updated_previous_step_outputs.update(step_input.previous_step_outputs)
        if condition_step_outputs:
            updated_previous_step_outputs.update(condition_step_outputs)

        return StepInput(
            input=step_input.input,
            previous_step_content=previous_step_content,
            previous_step_outputs=updated_previous_step_outputs,
            additional_data=step_input.additional_data,
            images=current_images + all_images,
            videos=current_videos + all_videos,
            audio=current_audio + all_audio,
        )

    def _evaluate_condition(self, step_input: StepInput, session_state: Optional[Dict[str, Any]] = None) -> bool:
        """Evaluate the condition and return boolean result.

        Supports:
            - Boolean literals (True/False)
            - Callable functions
            - CEL expression strings
        """
        if isinstance(self.evaluator, bool):
            return self.evaluator

        if isinstance(self.evaluator, str):
            # CEL expression
            if not CEL_AVAILABLE:
                logger.error(
                    "CEL expression used but cel-python is not installed. Install with: pip install cel-python"
                )
                return False
            try:
                return evaluate_cel_condition_evaluator(self.evaluator, step_input, session_state)
            except Exception as e:
                logger.error(f"CEL expression evaluation failed: {e}")
                return False

        if callable(self.evaluator):
            if session_state is not None and self._evaluator_has_session_state_param():
                result = self.evaluator(step_input, session_state=session_state)  # type: ignore[call-arg]
            else:
                result = self.evaluator(step_input)

            if isinstance(result, bool):
                return result
            else:
                logger.warning(f"Condition evaluator returned unexpected type: {type(result)}, expected bool")
                return False

        return False

    async def _aevaluate_condition(self, step_input: StepInput, session_state: Optional[Dict[str, Any]] = None) -> bool:
        """Async version of condition evaluation.

        Supports:
            - Boolean literals (True/False)
            - Callable functions (sync and async)
            - CEL expression strings
        """
        if isinstance(self.evaluator, bool):
            return self.evaluator

        if isinstance(self.evaluator, str):
            # CEL expression - CEL evaluation is synchronous
            if not CEL_AVAILABLE:
                logger.error(
                    "CEL expression used but cel-python is not installed. Install with: pip install cel-python"
                )
                return False
            try:
                return evaluate_cel_condition_evaluator(self.evaluator, step_input, session_state)
            except Exception as e:
                logger.error(f"CEL expression evaluation failed: {e}")
                return False

        if callable(self.evaluator):
            has_session_state = session_state is not None and self._evaluator_has_session_state_param()

            if inspect.iscoroutinefunction(self.evaluator):
                if has_session_state:
                    result = await self.evaluator(step_input, session_state=session_state)  # type: ignore[call-arg]
                else:
                    result = await self.evaluator(step_input)
            else:
                if has_session_state:
                    result = self.evaluator(step_input, session_state=session_state)  # type: ignore[call-arg]
                else:
                    result = self.evaluator(step_input)

            if isinstance(result, bool):
                return result
            else:
                logger.warning(f"Condition evaluator returned unexpected type: {type(result)}, expected bool")
                return False

        return False

    def _evaluator_has_session_state_param(self) -> bool:
        """Check if the evaluator function has a session_state parameter"""
        if not callable(self.evaluator):
            return False

        try:
            sig = inspect.signature(self.evaluator)
            return "session_state" in sig.parameters
        except Exception:
            return False

    def _has_else_steps(self) -> bool:
        """Check if else_steps is provided and not empty."""
        return self.else_steps is not None and len(self.else_steps) > 0

    def execute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        store_executor_outputs: bool = True,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Execute the condition and its steps with sequential chaining.

        If condition is True, executes `steps`.
        If condition is False and `else_steps` is provided (and not empty), executes `else_steps`.
        If condition is False and no `else_steps`, returns a "not met" message.
        """
        log_debug(f"Condition Start: {self.name}", center=True, symbol="-")

        conditional_step_id = str(uuid4())

        self._prepare_steps()

        # Evaluate the condition
        if run_context is not None and run_context.session_state is not None:
            condition_result = self._evaluate_condition(step_input, session_state=run_context.session_state)
        else:
            condition_result = self._evaluate_condition(step_input, session_state=session_state)

        log_debug(f"Condition {self.name} evaluated to: {condition_result}")

        # Determine which steps to execute
        if condition_result:
            steps_to_execute = self.steps
            branch = CONDITION_BRANCH_IF
            log_debug(f"Condition {self.name} met, executing {len(steps_to_execute)} steps (if branch)")
        elif self._has_else_steps():
            steps_to_execute = self.else_steps  # type: ignore[assignment]
            branch = CONDITION_BRANCH_ELSE
            log_debug(f"Condition {self.name} not met, executing {len(steps_to_execute)} else_steps (else branch)")
        else:
            # No else_steps provided, return "not met" message
            log_debug(f"Condition {self.name} not met, skipping {len(self.steps)} steps")
            return StepOutput(
                step_name=self.name,
                step_id=conditional_step_id,
                step_type=StepType.CONDITION,
                content=f"Condition {self.name} not met - skipped {len(self.steps)} steps",
                success=True,
            )

        all_results: List[StepOutput] = []
        current_step_input = step_input
        condition_step_outputs: Dict[str, StepOutput] = {}

        for i, step in enumerate(steps_to_execute):
            try:
                step_output = step.execute(  # type: ignore[union-attr]
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

                # Handle both single StepOutput and List[StepOutput] (from Loop/Condition/Router steps)
                if isinstance(step_output, list):
                    all_results.extend(step_output)
                    if step_output:
                        step_name = getattr(step, "name", f"step_{i}")
                        log_debug(f"Executing condition step {i + 1}/{len(steps_to_execute)}: {step_name}")

                        condition_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break
                else:
                    all_results.append(step_output)
                    step_name = getattr(step, "name", f"step_{i}")
                    condition_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by condition step {step_name}")
                        break

                step_name = getattr(step, "name", f"step_{i}")
                log_debug(f"Condition step {step_name} completed")

                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, condition_step_outputs
                )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Condition step {step_name} failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break

        log_debug(f"Condition End: {self.name} ({len(all_results)} results, {branch} branch)", center=True, symbol="-")

        return StepOutput(
            step_name=self.name,
            step_id=conditional_step_id,
            step_type=StepType.CONDITION,
            content=f"Condition {self.name} completed with {len(all_results)} results ({branch} branch)",
            success=all(result.success for result in all_results) if all_results else True,
            error=None,
            stop=any(result.stop for result in all_results) if all_results else False,
            steps=all_results,
        )

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Execute the condition with streaming support.

        If condition is True, executes `steps`.
        If condition is False and `else_steps` is provided (and not empty), executes `else_steps`.
        If condition is False and no `else_steps`, yields completed event and returns.
        """
        log_debug(f"Condition Start: {self.name}", center=True, symbol="-")

        conditional_step_id = str(uuid4())

        self._prepare_steps()

        # Evaluate the condition
        if run_context is not None and run_context.session_state is not None:
            condition_result = self._evaluate_condition(step_input, session_state=run_context.session_state)
        else:
            condition_result = self._evaluate_condition(step_input, session_state=session_state)
        log_debug(f"Condition {self.name} evaluated to: {condition_result}")

        if stream_events and workflow_run_response:
            # Yield condition started event
            yield ConditionExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                condition_result=condition_result,
                step_id=conditional_step_id,
                parent_step_id=parent_step_id,
            )

        # Determine which steps to execute
        if condition_result:
            steps_to_execute = self.steps
            branch = CONDITION_BRANCH_IF
            log_debug(f"Condition {self.name} met, executing {len(steps_to_execute)} steps (if branch)")
        elif self._has_else_steps():
            steps_to_execute = self.else_steps  # type: ignore[assignment]
            branch = CONDITION_BRANCH_ELSE
            log_debug(f"Condition {self.name} not met, executing {len(steps_to_execute)} else_steps (else branch)")
        else:
            # No else_steps provided, yield completed event and return
            if stream_events and workflow_run_response:
                yield ConditionExecutionCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    condition_result=False,
                    executed_steps=0,
                    branch=None,
                    step_results=[],
                    step_id=conditional_step_id,
                    parent_step_id=parent_step_id,
                )
            return

        all_results: List[StepOutput] = []
        current_step_input = step_input
        condition_step_outputs: Dict[str, StepOutput] = {}

        for i, step in enumerate(steps_to_execute):
            try:
                step_outputs_for_step: List[StepOutput] = []

                # Create child index for each step within condition
                if step_index is None or isinstance(step_index, int):
                    # Condition is a main step - child steps get x.1, x.2, x.3 format
                    child_step_index = (step_index if step_index is not None else 1, i)
                else:
                    # Condition is already a child step - child steps get same parent number: x.y, x.y, x.y
                    child_step_index = step_index

                # Stream step execution
                for event in step.execute_stream(  # type: ignore[union-attr]
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_events=stream_events,
                    stream_executor_events=stream_executor_events,
                    workflow_run_response=workflow_run_response,
                    step_index=child_step_index,
                    store_executor_outputs=store_executor_outputs,
                    run_context=run_context,
                    session_state=session_state,
                    parent_step_id=conditional_step_id,
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
                log_debug(f"Condition step {step_name} streaming completed")

                if step_outputs_for_step:
                    if len(step_outputs_for_step) == 1:
                        condition_step_outputs[step_name] = step_outputs_for_step[0]

                        if step_outputs_for_step[0].stop:
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step[0], condition_step_outputs
                        )
                    else:
                        # Use last output
                        condition_step_outputs[step_name] = step_outputs_for_step[-1]

                        if any(output.stop for output in step_outputs_for_step):
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step, condition_step_outputs
                        )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Condition step {step_name} streaming failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break

        log_debug(f"Condition End: {self.name} ({len(all_results)} results, {branch} branch)", center=True, symbol="-")
        if stream_events and workflow_run_response:
            # Yield condition completed event
            yield ConditionExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                condition_result=condition_result,
                executed_steps=len(steps_to_execute),
                branch=branch,
                step_results=all_results,
                step_id=conditional_step_id,
                parent_step_id=parent_step_id,
            )

        yield StepOutput(
            step_name=self.name,
            step_id=conditional_step_id,
            step_type=StepType.CONDITION,
            content=f"Condition {self.name} completed with {len(all_results)} results ({branch} branch)",
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
        store_executor_outputs: bool = True,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Async execute the condition and its steps with sequential chaining.

        If condition is True, executes `steps`.
        If condition is False and `else_steps` is provided (and not empty), executes `else_steps`.
        If condition is False and no `else_steps`, returns a "not met" message.
        """
        log_debug(f"Condition Start: {self.name}", center=True, symbol="-")

        conditional_step_id = str(uuid4())

        self._prepare_steps()

        # Evaluate the condition
        if run_context is not None and run_context.session_state is not None:
            condition_result = await self._aevaluate_condition(step_input, session_state=run_context.session_state)
        else:
            condition_result = await self._aevaluate_condition(step_input, session_state=session_state)
        log_debug(f"Condition {self.name} evaluated to: {condition_result}")

        # Determine which steps to execute
        if condition_result:
            steps_to_execute = self.steps
            branch = CONDITION_BRANCH_IF
            log_debug(f"Condition {self.name} met, executing {len(steps_to_execute)} steps (if branch)")
        elif self._has_else_steps():
            steps_to_execute = self.else_steps  # type: ignore[assignment]
            branch = CONDITION_BRANCH_ELSE
            log_debug(f"Condition {self.name} not met, executing {len(steps_to_execute)} else_steps (else branch)")
        else:
            # No else_steps provided, return "not met" message
            log_debug(f"Condition {self.name} not met, skipping {len(self.steps)} steps")
            return StepOutput(
                step_name=self.name,
                step_id=conditional_step_id,
                step_type=StepType.CONDITION,
                content=f"Condition {self.name} not met - skipped {len(self.steps)} steps",
                success=True,
            )

        # Chain steps sequentially like Loop does
        all_results: List[StepOutput] = []
        current_step_input = step_input
        condition_step_outputs: Dict[str, StepOutput] = {}

        for i, step in enumerate(steps_to_execute):
            try:
                step_output = await step.aexecute(  # type: ignore[union-attr]
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
                        condition_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break
                else:
                    all_results.append(step_output)
                    step_name = getattr(step, "name", f"step_{i}")
                    condition_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by condition step {step_name}")
                        break

                step_name = getattr(step, "name", f"step_{i}")
                log_debug(f"Condition step {step_name} async completed")

                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, condition_step_outputs
                )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Condition step {step_name} async failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break

        log_debug(f"Condition End: {self.name} ({len(all_results)} results, {branch} branch)", center=True, symbol="-")

        return StepOutput(
            step_name=self.name,
            step_id=conditional_step_id,
            step_type=StepType.CONDITION,
            content=f"Condition {self.name} completed with {len(all_results)} results ({branch} branch)",
            success=all(result.success for result in all_results) if all_results else True,
            error=None,
            stop=any(result.stop for result in all_results) if all_results else False,
            steps=all_results,
        )

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, TeamRunOutputEvent, RunOutputEvent, StepOutput]]:
        """Async execute the condition with streaming support.

        If condition is True, executes `steps`.
        If condition is False and `else_steps` is provided (and not empty), executes `else_steps`.
        If condition is False and no `else_steps`, yields completed event and returns.
        """
        log_debug(f"Condition Start: {self.name}", center=True, symbol="-")

        conditional_step_id = str(uuid4())

        self._prepare_steps()

        # Evaluate the condition
        if run_context is not None and run_context.session_state is not None:
            condition_result = await self._aevaluate_condition(step_input, session_state=run_context.session_state)
        else:
            condition_result = await self._aevaluate_condition(step_input, session_state=session_state)
        log_debug(f"Condition {self.name} evaluated to: {condition_result}")

        if stream_events and workflow_run_response:
            # Yield condition started event
            yield ConditionExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                condition_result=condition_result,
                step_id=conditional_step_id,
                parent_step_id=parent_step_id,
            )

        # Determine which steps to execute
        if condition_result:
            steps_to_execute = self.steps
            branch = CONDITION_BRANCH_IF
            log_debug(f"Condition {self.name} met, executing {len(steps_to_execute)} steps (if branch)")
        elif self._has_else_steps():
            steps_to_execute = self.else_steps  # type: ignore[assignment]
            branch = CONDITION_BRANCH_ELSE
            log_debug(f"Condition {self.name} not met, executing {len(steps_to_execute)} else_steps (else branch)")
        else:
            # No else_steps provided, yield completed event and return
            if stream_events and workflow_run_response:
                yield ConditionExecutionCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    condition_result=False,
                    executed_steps=0,
                    branch=None,
                    step_results=[],
                    step_id=conditional_step_id,
                    parent_step_id=parent_step_id,
                )
            return

        # Chain steps sequentially like Loop does
        all_results: List[StepOutput] = []
        current_step_input = step_input
        condition_step_outputs: Dict[str, StepOutput] = {}

        for i, step in enumerate(steps_to_execute):
            try:
                step_outputs_for_step: List[StepOutput] = []

                # Create child index for each step within condition
                if step_index is None or isinstance(step_index, int):
                    # Condition is a main step - child steps get x.1, x.2, x.3 format
                    child_step_index = (step_index if step_index is not None else 1, i)
                else:
                    # Condition is already a child step - child steps get same parent number: x.y, x.y, x.y
                    child_step_index = step_index

                # Stream step execution - mirroring Loop logic
                async for event in step.aexecute_stream(  # type: ignore[union-attr]
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_events=stream_events,
                    stream_executor_events=stream_executor_events,
                    workflow_run_response=workflow_run_response,
                    step_index=child_step_index,
                    store_executor_outputs=store_executor_outputs,
                    run_context=run_context,
                    session_state=session_state,
                    parent_step_id=conditional_step_id,
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
                log_debug(f"Condition step {step_name} async streaming completed")

                if step_outputs_for_step:
                    if len(step_outputs_for_step) == 1:
                        condition_step_outputs[step_name] = step_outputs_for_step[0]

                        if step_outputs_for_step[0].stop:
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step[0], condition_step_outputs
                        )
                    else:
                        # Use last output
                        condition_step_outputs[step_name] = step_outputs_for_step[-1]

                        if any(output.stop for output in step_outputs_for_step):
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step, condition_step_outputs
                        )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Condition step {step_name} async streaming failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break

        log_debug(f"Condition End: {self.name} ({len(all_results)} results, {branch} branch)", center=True, symbol="-")

        if stream_events and workflow_run_response:
            # Yield condition completed event
            yield ConditionExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                condition_result=condition_result,
                executed_steps=len(steps_to_execute),
                branch=branch,
                step_results=all_results,
                step_id=conditional_step_id,
                parent_step_id=parent_step_id,
            )

        yield StepOutput(
            step_name=self.name,
            step_id=conditional_step_id,
            step_type=StepType.CONDITION,
            content=f"Condition {self.name} completed with {len(all_results)} results ({branch} branch)",
            success=all(result.success for result in all_results) if all_results else True,
            stop=any(result.stop for result in all_results) if all_results else False,
            steps=all_results,
        )
