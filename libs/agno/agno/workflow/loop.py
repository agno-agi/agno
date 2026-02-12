import inspect
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union
from uuid import uuid4

from agno.registry import Registry
from agno.run.agent import RunOutputEvent
from agno.run.base import RunContext
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import (
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    LoopIterationCompletedEvent,
    LoopIterationStartedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
)
from agno.session.workflow import WorkflowSession
from agno.utils.log import log_debug, logger
from agno.workflow.cel import CEL_AVAILABLE, evaluate_cel_loop_end_condition, is_cel_expression
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
class Loop:
    """A loop of steps that execute in order.

    The end_condition can be:
        - A callable function that takes List[StepOutput] and returns bool
        - A CEL (Common Expression Language) expression string
        - None (loop runs for max_iterations)

    CEL expressions for end_condition have access to:
        - current_iteration: Current iteration number (1-indexed, after completion)
        - max_iterations: Maximum iterations configured for the loop
        - all_success: Boolean - True if all steps in this iteration succeeded
        - last_step_content: Content string from the last step in the iteration
        - step_outputs: Map of step name to content string from the current iteration

    Example CEL expressions:
        - 'current_iteration >= 2'
        - 'current_iteration >= max_iterations'
        - 'all_success'
        - 'last_step_content.contains("DONE")'
        - 'all_success && current_iteration >= 2'
    """

    steps: WorkflowSteps

    name: Optional[str] = None
    description: Optional[str] = None

    max_iterations: int = 3  # Default to 3
    end_condition: Optional[Union[Callable[[List[StepOutput]], bool], str]] = None

    def __init__(
        self,
        steps: WorkflowSteps,
        name: Optional[str] = None,
        description: Optional[str] = None,
        max_iterations: int = 3,
        end_condition: Optional[Union[Callable[[List[StepOutput]], bool], str]] = None,
    ):
        self.steps = steps
        self.name = name
        self.description = description
        self.max_iterations = max_iterations
        self.end_condition = end_condition

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "type": "Loop",
            "name": self.name,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps if hasattr(step, "to_dict")],
            "max_iterations": self.max_iterations,
        }
        # Serialize end_condition
        if self.end_condition is None:
            result["end_condition"] = None
            result["end_condition_type"] = None
        elif isinstance(self.end_condition, str):
            result["end_condition"] = self.end_condition
            result["end_condition_type"] = "cel"
        elif callable(self.end_condition):
            result["end_condition"] = self.end_condition.__name__
            result["end_condition_type"] = "function"
        else:
            raise ValueError(f"Invalid end_condition type: {type(self.end_condition).__name__}")

        return result

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        registry: Optional["Registry"] = None,
        db: Optional[Any] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> "Loop":
        from agno.workflow.condition import Condition
        from agno.workflow.parallel import Parallel
        from agno.workflow.router import Router
        from agno.workflow.steps import Steps

        def deserialize_step(step_data: Dict[str, Any]) -> Any:
            step_type = step_data.get("type", "Step")
            if step_type == "Loop":
                return cls.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Parallel":
                return Parallel.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Steps":
                return Steps.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Condition":
                return Condition.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Router":
                return Router.from_dict(step_data, registry=registry, db=db, links=links)
            else:
                return Step.from_dict(step_data, registry=registry, db=db, links=links)

        # Deserialize end_condition
        end_condition_data = data.get("end_condition")
        end_condition_type = data.get("end_condition_type")
        end_condition: Optional[Union[Callable[[List[StepOutput]], bool], str]] = None

        if end_condition_data is None:
            end_condition = None
        elif isinstance(end_condition_data, str):
            if end_condition_type == "cel" or (end_condition_type is None and is_cel_expression(end_condition_data)):
                end_condition = end_condition_data
            else:
                if registry:
                    end_condition = registry.get_function(end_condition_data)
                    if end_condition is None:
                        raise ValueError(f"End condition function '{end_condition_data}' not found in registry")
                else:
                    raise ValueError(f"Registry required to deserialize end_condition function '{end_condition_data}'")

        return cls(
            name=data.get("name"),
            description=data.get("description"),
            steps=[deserialize_step(step) for step in data.get("steps", [])],
            max_iterations=data.get("max_iterations", 3),
            end_condition=end_condition,
        )

    def _evaluate_end_condition(self, iteration_results: List[StepOutput], current_iteration: int = 0) -> bool:
        """Evaluate the end condition and return whether the loop should stop."""
        if self.end_condition is None:
            return False

        if isinstance(self.end_condition, str):
            if not CEL_AVAILABLE:
                logger.error(
                    "CEL expression used but cel-python is not installed. Install with: pip install cel-python"
                )
                return False
            try:
                return evaluate_cel_loop_end_condition(
                    self.end_condition, iteration_results, current_iteration, self.max_iterations
                )
            except Exception as e:
                logger.warning(f"CEL end condition evaluation failed: {e}")
                return False

        if callable(self.end_condition):
            try:
                return self.end_condition(iteration_results)
            except Exception as e:
                logger.warning(f"End condition evaluation failed: {e}")
                return False

        return False

    async def _aevaluate_end_condition(self, iteration_results: List[StepOutput], current_iteration: int = 0) -> bool:
        """Async evaluate the end condition."""
        if self.end_condition is None:
            return False

        if isinstance(self.end_condition, str):
            if not CEL_AVAILABLE:
                logger.error(
                    "CEL expression used but cel-python is not installed. Install with: pip install cel-python"
                )
                return False
            try:
                return evaluate_cel_loop_end_condition(
                    self.end_condition, iteration_results, current_iteration, self.max_iterations
                )
            except Exception as e:
                logger.warning(f"CEL end condition evaluation failed: {e}")
                return False

        if callable(self.end_condition):
            try:
                if inspect.iscoroutinefunction(self.end_condition):
                    return await self.end_condition(iteration_results)
                else:
                    return self.end_condition(iteration_results)
            except Exception as e:
                logger.warning(f"End condition evaluation failed: {e}")
                return False

        return False

    def _prepare_steps(self):
        """Prepare the steps for execution - mirrors workflow logic"""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.condition import Condition
        from agno.workflow.parallel import Parallel
        from agno.workflow.router import Router
        from agno.workflow.step import Step
        from agno.workflow.steps import Steps

        prepared_steps: WorkflowSteps = []
        for step in self.steps:
            if callable(step) and hasattr(step, "__name__"):
                prepared_steps.append(Step(name=step.__name__, description="User-defined callable step", executor=step))
            elif isinstance(step, Agent):
                prepared_steps.append(Step(name=step.name, description=step.description, agent=step))
            elif isinstance(step, Team):
                prepared_steps.append(Step(name=step.name, description=step.description, team=step))
            elif isinstance(step, (Step, Steps, Loop, Parallel, Condition, Router)):
                prepared_steps.append(step)
            else:
                raise ValueError(f"Invalid step type: {type(step).__name__}")

        self.steps = prepared_steps

    def _update_step_input_from_outputs(
        self,
        step_input: StepInput,
        step_outputs: Union[StepOutput, List[StepOutput]],
        loop_step_outputs: Optional[Dict[str, StepOutput]] = None,
    ) -> StepInput:
        """Helper to update step input from step outputs (handles both single and multiple outputs)"""
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
        if loop_step_outputs:
            updated_previous_step_outputs.update(loop_step_outputs)

        return StepInput(
            input=step_input.input,
            previous_step_content=previous_step_content,
            previous_step_outputs=updated_previous_step_outputs,
            additional_data=step_input.additional_data,
            images=current_images + all_images,
            videos=current_videos + all_videos,
            audio=current_audio + all_audio,
        )

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
        """Execute loop steps with iteration control - mirrors workflow execution logic"""
        # Use workflow logger for loop orchestration
        log_debug(f"Loop Start: {self.name}", center=True, symbol="=")

        # Prepare steps first
        self._prepare_steps()

        all_results = []
        iteration = 0
        early_termination = False

        while iteration < self.max_iterations:
            # Execute all steps in this iteration - mirroring workflow logic
            iteration_results: List[StepOutput] = []
            current_step_input = step_input
            loop_step_outputs = {}  # Track outputs within this loop iteration

            for i, step in enumerate(self.steps):
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

                # Handle both single StepOutput and List[StepOutput] (from Loop/Condition steps)
                if isinstance(step_output, list):
                    # This is a step that returns multiple outputs (Loop, Condition etc.)
                    iteration_results.extend(step_output)
                    if step_output:  # Add last output to loop tracking
                        step_name = getattr(step, "name", f"step_{i + 1}")
                        loop_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by step {step_name}")
                            early_termination = True
                            break
                else:
                    # Single StepOutput
                    iteration_results.append(step_output)
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    loop_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by step {step_name}")
                        early_termination = True
                        break

                # Update step input for next step
                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, loop_step_outputs
                )

            all_results.append(iteration_results)
            iteration += 1

            # Check end condition
            if self._evaluate_end_condition(iteration_results, iteration):
                break

            # Break out of iteration loop if early termination was requested
            if early_termination:
                log_debug(f"Loop ending early due to step termination request at iteration {iteration}")
                break

        log_debug(f"Loop End: {self.name} ({iteration} iterations)", center=True, symbol="=")

        # Return flattened results from all iterations
        flattened_results = []
        for iteration_results in all_results:
            flattened_results.extend(iteration_results)

        return StepOutput(
            step_name=self.name,
            step_id=str(uuid4()),
            step_type=StepType.LOOP,
            content=f"Loop {self.name} completed {iteration} iterations with {len(flattened_results)} total steps",
            success=all(result.success for result in flattened_results) if flattened_results else True,
            stop=any(result.stop for result in flattened_results) if flattened_results else False,
            steps=flattened_results,
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
        """Execute loop steps with streaming support - mirrors workflow execution logic"""
        log_debug(f"Loop Start: {self.name}", center=True, symbol="=")

        # Prepare steps first
        self._prepare_steps()

        loop_step_id = str(uuid4())

        if stream_events and workflow_run_response:
            # Yield loop started event
            yield LoopExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                max_iterations=self.max_iterations,
                step_id=loop_step_id,
                parent_step_id=parent_step_id,
            )

        all_results = []
        iteration = 0
        early_termination = False

        while iteration < self.max_iterations:
            log_debug(f"Loop iteration {iteration + 1}/{self.max_iterations}")

            if stream_events and workflow_run_response:
                # Yield iteration started event
                yield LoopIterationStartedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    iteration=iteration + 1,
                    max_iterations=self.max_iterations,
                    step_id=loop_step_id,
                    parent_step_id=parent_step_id,
                )

            # Execute all steps in this iteration - mirroring workflow logic
            iteration_results = []
            current_step_input = step_input
            loop_step_outputs = {}

            for i, step in enumerate(self.steps):
                step_outputs_for_iteration = []

                # Loop children always get sequential sub-indices: parent_index.1, parent_index.2, etc.
                if step_index is None or isinstance(step_index, int):
                    # Loop is a main step
                    composite_step_index = (step_index if step_index is not None else 0, i)
                else:
                    # Loop is a nested step - extend the tuple
                    composite_step_index = step_index + (i,)

                # Stream step execution
                for event in step.execute_stream(  # type: ignore[union-attr]
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_events=stream_events,
                    stream_executor_events=stream_executor_events,
                    workflow_run_response=workflow_run_response,
                    step_index=composite_step_index,
                    store_executor_outputs=store_executor_outputs,
                    run_context=run_context,
                    session_state=session_state,
                    parent_step_id=loop_step_id,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    workflow_session=workflow_session,
                    num_history_runs=num_history_runs,
                    background_tasks=background_tasks,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_iteration.append(event)
                        iteration_results.append(event)
                    else:
                        # Yield other events (streaming content, step events, etc.)
                        yield event

                # Update loop_step_outputs with this step's output
                if step_outputs_for_iteration:
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    if len(step_outputs_for_iteration) == 1:
                        loop_step_outputs[step_name] = step_outputs_for_iteration[0]

                        if step_outputs_for_iteration[0].stop:
                            logger.info(f"Early termination requested by step {step_name}")
                            early_termination = True
                            break  # Break out of step loop

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_iteration[0], loop_step_outputs
                        )
                    else:
                        # Use last output
                        loop_step_outputs[step_name] = step_outputs_for_iteration[-1]

                        if any(output.stop for output in step_outputs_for_iteration):
                            logger.info(f"Early termination requested by step {step_name}")
                            early_termination = True
                            break  # Break out of step loop

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_iteration, loop_step_outputs
                        )

            all_results.append(iteration_results)
            iteration += 1

            # Check end condition
            should_continue = True
            if self._evaluate_end_condition(iteration_results, iteration):
                should_continue = False
                log_debug("End condition met, loop will stop")

            if early_termination:
                should_continue = False
                log_debug(f"Loop ending early due to step termination request at iteration {iteration}")

            if stream_events and workflow_run_response:
                # Yield iteration completed event
                yield LoopIterationCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    iteration=iteration,
                    max_iterations=self.max_iterations,
                    iteration_results=iteration_results,
                    should_continue=should_continue,
                    step_id=loop_step_id,
                    parent_step_id=parent_step_id,
                )

            if not should_continue:
                log_debug(f"Loop ending early at iteration {iteration}")
                break

        log_debug(f"Loop End: {self.name} ({iteration} iterations)", center=True, symbol="=")

        if stream_events and workflow_run_response:
            # Yield loop completed event
            yield LoopExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                total_iterations=iteration,
                max_iterations=self.max_iterations,
                all_results=all_results,
                step_id=loop_step_id,
                parent_step_id=parent_step_id,
            )

        flattened_results = []
        for iteration_results in all_results:
            flattened_results.extend(iteration_results)

        yield StepOutput(
            step_name=self.name,
            step_id=loop_step_id,
            step_type=StepType.LOOP,
            content=f"Loop {self.name} completed {iteration} iterations with {len(flattened_results)} total steps",
            success=all(result.success for result in flattened_results) if flattened_results else True,
            stop=any(result.stop for result in flattened_results) if flattened_results else False,
            steps=flattened_results,
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
        """Execute loop steps asynchronously with iteration control - mirrors workflow execution logic"""
        # Use workflow logger for async loop orchestration
        log_debug(f"Loop Start: {self.name}", center=True, symbol="=")

        loop_step_id = str(uuid4())

        # Prepare steps first
        self._prepare_steps()

        all_results = []
        iteration = 0
        early_termination = False

        while iteration < self.max_iterations:
            # Execute all steps in this iteration - mirroring workflow logic
            iteration_results: List[StepOutput] = []
            current_step_input = step_input
            loop_step_outputs = {}  # Track outputs within this loop iteration

            for i, step in enumerate(self.steps):
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

                # Handle both single StepOutput and List[StepOutput] (from Loop/Condition steps)
                if isinstance(step_output, list):
                    # This is a step that returns multiple outputs (Loop, Condition etc.)
                    iteration_results.extend(step_output)
                    if step_output:  # Add last output to loop tracking
                        step_name = getattr(step, "name", f"step_{i + 1}")
                        loop_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by step {step_name}")
                            early_termination = True
                            break
                else:
                    # Single StepOutput
                    iteration_results.append(step_output)
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    loop_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by step {step_name}")
                        early_termination = True
                        break

                # Update step input for next step
                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, loop_step_outputs
                )

            all_results.append(iteration_results)
            iteration += 1

            # Check end condition
            if await self._aevaluate_end_condition(iteration_results, iteration):
                break

            # Break out of iteration loop if early termination was requested
            if early_termination:
                log_debug(f"Loop ending early due to step termination request at iteration {iteration}")
                break

        log_debug(f"Async Loop End: {self.name} ({iteration} iterations)", center=True, symbol="=")

        # Return flattened results from all iterations
        flattened_results = []
        for iteration_results in all_results:
            flattened_results.extend(iteration_results)

        return StepOutput(
            step_name=self.name,
            step_id=loop_step_id,
            step_type=StepType.LOOP,
            content=f"Loop {self.name} completed {iteration} iterations with {len(flattened_results)} total steps",
            success=all(result.success for result in flattened_results) if flattened_results else True,
            stop=any(result.stop for result in flattened_results) if flattened_results else False,
            steps=flattened_results,
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
        """Execute loop steps with async streaming support - mirrors workflow execution logic"""
        log_debug(f"Loop Start: {self.name}", center=True, symbol="=")

        loop_step_id = str(uuid4())

        # Prepare steps first
        self._prepare_steps()

        if stream_events and workflow_run_response:
            # Yield loop started event
            yield LoopExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                max_iterations=self.max_iterations,
                step_id=loop_step_id,
                parent_step_id=parent_step_id,
            )

        all_results = []
        iteration = 0
        early_termination = False

        while iteration < self.max_iterations:
            log_debug(f"Async loop iteration {iteration + 1}/{self.max_iterations}")

            if stream_events and workflow_run_response:
                # Yield iteration started event
                yield LoopIterationStartedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    iteration=iteration + 1,
                    max_iterations=self.max_iterations,
                    step_id=loop_step_id,
                    parent_step_id=parent_step_id,
                )

            # Execute all steps in this iteration - mirroring workflow logic
            iteration_results = []
            current_step_input = step_input
            loop_step_outputs = {}  # Track outputs within this loop iteration

            for i, step in enumerate(self.steps):
                step_outputs_for_iteration = []

                # Loop children always get sequential sub-indices: parent_index.1, parent_index.2, etc.
                if step_index is None or isinstance(step_index, int):
                    # Loop is a main step
                    composite_step_index = (step_index if step_index is not None else 0, i)
                else:
                    # Loop is a nested step - extend the tuple
                    composite_step_index = step_index + (i,)

                # Stream step execution - mirroring workflow logic
                async for event in step.aexecute_stream(  # type: ignore[union-attr]
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_events=stream_events,
                    stream_executor_events=stream_executor_events,
                    workflow_run_response=workflow_run_response,
                    step_index=composite_step_index,
                    store_executor_outputs=store_executor_outputs,
                    run_context=run_context,
                    session_state=session_state,
                    parent_step_id=loop_step_id,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    background_tasks=background_tasks,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_iteration.append(event)
                        iteration_results.append(event)
                    else:
                        # Yield other events (streaming content, step events, etc.)
                        yield event

                # Update loop_step_outputs with this step's output
                if step_outputs_for_iteration:
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    if len(step_outputs_for_iteration) == 1:
                        loop_step_outputs[step_name] = step_outputs_for_iteration[0]

                        if step_outputs_for_iteration[0].stop:
                            logger.info(f"Early termination requested by step {step_name}")
                            early_termination = True
                            break  # Break out of step loop

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_iteration[0], loop_step_outputs
                        )
                    else:
                        # Use last output
                        loop_step_outputs[step_name] = step_outputs_for_iteration[-1]

                        if any(output.stop for output in step_outputs_for_iteration):
                            logger.info(f"Early termination requested by step {step_name}")
                            early_termination = True
                            break  # Break out of step loop

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_iteration, loop_step_outputs
                        )

            all_results.append(iteration_results)
            iteration += 1

            # Check end condition
            should_continue = True
            if await self._aevaluate_end_condition(iteration_results, iteration):
                should_continue = False
                log_debug("End condition met, loop will stop")

            if early_termination:
                should_continue = False
                log_debug(f"Loop ending early due to step termination request at iteration {iteration}")

            if stream_events and workflow_run_response:
                # Yield iteration completed event
                yield LoopIterationCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    iteration=iteration,
                    max_iterations=self.max_iterations,
                    iteration_results=iteration_results,
                    should_continue=should_continue,
                    step_id=loop_step_id,
                    parent_step_id=parent_step_id,
                )

            if not should_continue:
                log_debug(f"Loop ending early at iteration {iteration}")
                break

        log_debug(f"Loop End: {self.name} ({iteration} iterations)", center=True, symbol="=")

        if stream_events and workflow_run_response:
            # Yield loop completed event
            yield LoopExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                total_iterations=iteration,
                max_iterations=self.max_iterations,
                all_results=all_results,
                step_id=loop_step_id,
                parent_step_id=parent_step_id,
            )

        flattened_results = []
        for iteration_results in all_results:
            flattened_results.extend(iteration_results)

        yield StepOutput(
            step_name=self.name,
            step_id=loop_step_id,
            step_type=StepType.LOOP,
            content=f"Loop {self.name} completed {iteration} iterations with {len(flattened_results)} total steps",
            success=all(result.success for result in flattened_results) if flattened_results else True,
            stop=any(result.stop for result in flattened_results) if flattened_results else False,
            steps=flattened_results,
        )
