import inspect
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union

from agno.run.response import RunResponseEvent
from agno.run.team import TeamRunResponseEvent
from agno.run.v2.workflow import (
    RouterExecutionCompletedEvent,
    RouterExecutionStartedEvent,
    WorkflowRunResponse,
    WorkflowRunResponseEvent,
)
from agno.utils.log import log_debug, logger
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput

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
    """A router that dynamically selects which step(s) to execute based on input"""

    # Router function that returns the step(s) to execute
    selector: Union[
        Callable[[StepInput], Union[WorkflowSteps, List[WorkflowSteps]]],
        Callable[[StepInput], Awaitable[Union[WorkflowSteps, List[WorkflowSteps]]]],
    ]
    choices: WorkflowSteps  # Available steps that can be selected

    name: Optional[str] = None
    description: Optional[str] = None

    def _prepare_steps(self):
        """Prepare the steps for execution - mirrors workflow logic"""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.v2.condition import Condition
        from agno.workflow.v2.loop import Loop
        from agno.workflow.v2.parallel import Parallel
        from agno.workflow.v2.step import Step
        from agno.workflow.v2.steps import Steps

        prepared_steps: WorkflowSteps = []
        for step in self.choices:
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
            message=step_input.message,
            previous_step_content=previous_step_content,
            previous_step_outputs=updated_previous_step_outputs,
            additional_data=step_input.additional_data,
            images=current_images + all_images,
            videos=current_videos + all_videos,
            audio=current_audio + all_audio,
        )

    def _route_steps(self, step_input: StepInput) -> List[Step]:  # type: ignore[return-value]
        """Route to the appropriate steps based on input"""
        if callable(self.selector):
            result = self.selector(step_input)

            # Handle the result based on its type
            if isinstance(result, Step):
                return [result]
            elif isinstance(result, list):
                return result  # type: ignore
            else:
                logger.warning(f"Router function returned unexpected type: {type(result)}")
                return []

        return []

    async def _aroute_steps(self, step_input: StepInput) -> List[Step]:  # type: ignore[return-value]
        """Async version of step routing"""
        if callable(self.selector):
            if inspect.iscoroutinefunction(self.selector):
                result = await self.selector(step_input)
            else:
                result = self.selector(step_input)

            # Handle the result based on its type
            if isinstance(result, Step):
                return [result]
            elif isinstance(result, list):
                return result
            else:
                logger.warning(f"Router function returned unexpected type: {type(result)}")
                return []

        return []

    def execute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> List[StepOutput]:
        """Execute the router and its selected steps with sequential chaining"""
        log_debug(f"Router Start: {self.name}", center=True, symbol="-")

        self._prepare_steps()

        # Route to appropriate steps
        steps_to_execute = self._route_steps(step_input)
        log_debug(f"Router {self.name}: Selected {len(steps_to_execute)} steps to execute")

        if not steps_to_execute:
            return []

        all_results: List[StepOutput] = []
        current_step_input = step_input
        router_step_outputs = {}

        for i, step in enumerate(steps_to_execute):
            try:
                step_output = step.execute(current_step_input, session_id=session_id, user_id=user_id)

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
        return all_results

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> Iterator[Union[WorkflowRunResponseEvent, StepOutput]]:
        """Execute the router with streaming support"""
        log_debug(f"Router Start: {self.name}", center=True, symbol="-")

        self._prepare_steps()

        # Route to appropriate steps
        steps_to_execute = self._route_steps(step_input)
        log_debug(f"Router {self.name}: Selected {len(steps_to_execute)} steps to execute")

        if stream_intermediate_steps and workflow_run_response:
            # Yield router started event
            yield RouterExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                selected_steps=[getattr(step, "name", f"step_{i}") for i, step in enumerate(steps_to_execute)],
            )

        if not steps_to_execute:
            # Yield router completed event for empty case
            if stream_intermediate_steps and workflow_run_response:
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
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=step_index,
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

        if stream_intermediate_steps and workflow_run_response:
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
            )

        for result in all_results:
            yield result

    async def aexecute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> List[StepOutput]:
        """Async execute the router and its selected steps with sequential chaining"""
        log_debug(f"Router Start: {self.name}", center=True, symbol="-")

        self._prepare_steps()

        # Route to appropriate steps
        steps_to_execute = await self._aroute_steps(step_input)
        log_debug(f"Router {self.name} selected: {len(steps_to_execute)} steps to execute")

        if not steps_to_execute:
            return []

        # Chain steps sequentially like Loop does
        all_results: List[StepOutput] = []
        current_step_input = step_input
        router_step_outputs = {}

        for i, step in enumerate(steps_to_execute):
            try:
                step_output = await step.aexecute(current_step_input, session_id=session_id, user_id=user_id)
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
        return all_results

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> AsyncIterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent, StepOutput]]:
        """Async execute the router with streaming support"""
        log_debug(f"Router Start: {self.name}", center=True, symbol="-")

        self._prepare_steps()

        # Route to appropriate steps
        steps_to_execute = await self._aroute_steps(step_input)
        log_debug(f"Router {self.name} selected: {len(steps_to_execute)} steps to execute")

        if stream_intermediate_steps and workflow_run_response:
            # Yield router started event
            yield RouterExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                selected_steps=[getattr(step, "name", f"step_{i}") for i, step in enumerate(steps_to_execute)],
            )

        if not steps_to_execute:
            if stream_intermediate_steps and workflow_run_response:
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
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=step_index,
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

        if stream_intermediate_steps and workflow_run_response:
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
            )

        for result in all_results:
            yield result
