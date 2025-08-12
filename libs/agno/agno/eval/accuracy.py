from dataclasses import asdict, dataclass, field
from enum import Enum
from os import getenv
from textwrap import dedent
from typing import TYPE_CHECKING, Callable, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.api.schemas.evals import EvalType
from agno.eval.utils import async_log_eval_run, log_eval_run, store_result_in_file
from agno.eval.utils.prompts import (
    accuracy_agentic_mode_system_prompt,
    accuracy_evaluator_input,
    accuracy_reasoning_mode_system_prompt,
)
from agno.exceptions import EvalError
from agno.models.base import Model
from agno.team.team import Team
from agno.utils.log import logger, set_log_level_to_debug, set_log_level_to_info

if TYPE_CHECKING:
    from rich.console import Console


class AccuracyAgentResponse(BaseModel):
    accuracy_score: int = Field(..., description="Accuracy Score between 1 and 10 assigned to the Agent's answer.")
    accuracy_reason: str = Field(..., description="Detailed reasoning for the accuracy score.")


class AccuracyEvalMode(str, Enum):
    """
    The complexity mode used for the evaluation.

    BASIC: The evaluation is performed using a simple comparison of the expected output and the Agent's output.
    AGENTIC: The evaluation is performed by the evaluator agent, comparing the Agent's output and the expected output.
    REASONING: The evaluation is performed by the evaluator agent, analyzing the Agent's output rationale, completeness and correctness, apart from accuracy.
    """

    BASIC = "basic"
    AGENTIC = "agentic"
    REASONING = "reasoning"


@dataclass
class AccuracyEvaluation:
    input: str
    output: str
    expected_output: Union[str, list[str]]
    score: int
    reason: str
    passing_score: int

    def print_eval(self, console: Optional["Console"] = None):
        from rich.box import ROUNDED
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.table import Table

        if console is None:
            console = Console()

        results_table = Table(
            box=ROUNDED,
            border_style="blue",
            show_header=False,
            title="[ Evaluation Result ]",
            title_style="bold sky_blue1",
            title_justify="center",
        )
        results_table.add_row("Input", self.input)
        results_table.add_row("Output", self.output)
        passed = "[green]Passed[/green]" if self.score >= self.passing_score else "[red]Failed[/red]"
        results_table.add_row("Result", passed)
        results_table.add_row("Expected Output", str(self.expected_output))
        results_table.add_row("Accuracy Score", f"{str(self.score)}/10")
        results_table.add_row("Accuracy Reason", Markdown(self.reason))
        console.print(results_table)


@dataclass
class AccuracyResult:
    passing_score: int

    results: List[AccuracyEvaluation] = field(default_factory=list)
    avg_score: float = field(init=False)
    mean_score: float = field(init=False)
    min_score: float = field(init=False)
    max_score: float = field(init=False)
    std_dev_score: float = field(init=False)

    def __post_init__(self):
        self.compute_stats()

    def compute_stats(self):
        import statistics

        if self.results and len(self.results) > 0:
            _results = [r.score for r in self.results]
            self.avg_score = statistics.mean(_results)
            self.mean_score = statistics.mean(_results)
            self.min_score = min(_results)
            self.max_score = max(_results)
            self.std_dev_score = statistics.stdev(_results) if len(_results) > 1 else 0

    def print_summary(self, console: Optional["Console"] = None):
        from rich.box import ROUNDED
        from rich.console import Console
        from rich.table import Table

        if console is None:
            console = Console()

        summary_table = Table(
            box=ROUNDED,
            border_style="blue",
            show_header=False,
            title="[ Evaluation Summary ]",
            title_style="bold sky_blue1",
            title_justify="center",
        )
        summary_table.add_row("Number of Runs", f"{len(self.results)}")
        passed = "[green]Passed[/green]" if self.avg_score >= self.passing_score else "[red]Failed[/red]"
        summary_table.add_row("Result", passed)
        summary_table.add_row("Average Score", f"{self.avg_score:.2f}")
        summary_table.add_row("Mean Score", f"{self.mean_score:.2f}")
        summary_table.add_row("Minimum Score", f"{self.min_score:.2f}")
        summary_table.add_row("Maximum Score", f"{self.max_score:.2f}")
        summary_table.add_row("Standard Deviation", f"{self.std_dev_score:.2f}")
        console.print(summary_table)

    def print_results(self, console: Optional["Console"] = None):
        from rich.box import ROUNDED
        from rich.console import Console
        from rich.table import Table

        if console is None:
            console = Console()

        results_table = Table(
            box=ROUNDED,
            border_style="blue",
            show_header=False,
            title="[ Evaluation Result ]",
            title_style="bold sky_blue1",
            title_justify="center",
        )
        for result in self.results:
            results_table.add_row("Input", result.input)
            results_table.add_row("Output", result.output)
            results_table.add_row("Expected Output(s)", str(result.expected_output))
            passed = "[green]Passed[/green]" if result.score >= result.passing_score else "[red]Failed[/red]"
            results_table.add_row("Result", passed)
            results_table.add_row("Accuracy Score", f"{str(result.score)}/10")

            if result.reason:
                results_table.add_row("Accuracy Reason", result.reason)
        console.print(results_table)


@dataclass
class AccuracyEval:
    """Interface to evaluate the accuracy of an Agent or Team, given a prompt and expected answer"""

    # Input to evaluate
    input: Union[str, Callable]
    # Expected answer to the input
    expected_output: Union[str, Callable, list[str]]
    # Agent to evaluate
    agent: Optional[Agent] = None
    # Mode defining how the evaluation is performed
    mode: AccuracyEvalMode = AccuracyEvalMode.REASONING
    # Team to evaluate
    team: Optional[Team] = None

    # Evaluation name
    name: Optional[str] = None
    # Evaluation UUID
    eval_id: str = field(default_factory=lambda: str(uuid4()))
    # Number of iterations to run
    num_iterations: int = 1
    # Result of the evaluation
    result: Optional[AccuracyResult] = None

    # Model for the evaluator agent
    model: Optional[Model] = None
    # Agent used to evaluate the answer
    evaluator_agent: Optional[Agent] = None
    # Guidelines for the evaluator agent
    additional_guidelines: Optional[Union[str, List[str]]] = None
    # Additional context to the evaluator agent
    additional_context: Optional[str] = None

    # Score (from 1 to 10) from which the evaluation is considered passed
    passing_score: int = 7
    # Print summary of results
    print_summary: bool = False
    # Print detailed results
    print_results: bool = False
    # If set, results will be saved in the given file path
    file_path_to_save_results: Optional[str] = None
    # Enable debug logs
    debug_mode: bool = getenv("AGNO_DEBUG", "false").lower() == "true"
    # Log the results to the Agno platform. On by default.
    monitoring: bool = getenv("AGNO_MONITOR", "true").lower() == "true"

    def _warn_configuration_conflicts(self):
        """Handle validation of the evaluation configuration and warnings."""
        if self.passing_score < 1 or self.passing_score > 10:
            raise EvalError("The passing score must be between 1 and 10.")

        if self.mode != AccuracyEvalMode.REASONING and (self.evaluator_agent is not None or self.model is not None):
            logger.warning(
                f"The provided evaluation mode ({self.mode}) is not compatible with having a custom evaluator agent or model. The custom evaluator agent or model will be ignored."
            )

        if self.mode in [AccuracyEvalMode.AGENTIC, AccuracyEvalMode.BASIC] and (
            self.additional_context is not None or self.additional_guidelines is not None
        ):
            logger.warning(
                f"The provided evaluation mode ({self.mode}) is not compatible with having additional context or guidelines. The additional context or guidelines will be ignored."
            )

    def get_evaluator_agent(self) -> Agent:
        """Return the evaluator agent. If not provided, build it based on the evaluator fields and default instructions."""
        if self.evaluator_agent is not None:
            return self.evaluator_agent

        model = self.model
        if model is None:
            try:
                from agno.models.openai import OpenAIChat

                model = OpenAIChat(id="o4-mini")
            except (ModuleNotFoundError, ImportError) as e:
                logger.exception(e)
                raise EvalError(
                    "Agno uses `openai` as the default model provider. Please run `pip install openai` to use the default evaluator."
                )

        additional_guidelines = ""
        if self.additional_guidelines is not None:
            additional_guidelines = "\n## Additional Guidelines\n"
            if isinstance(self.additional_guidelines, str):
                additional_guidelines += self.additional_guidelines
            else:
                additional_guidelines += "\n- ".join(self.additional_guidelines)
            additional_guidelines += "\n"

        additional_context = ""
        if self.additional_context is not None and len(self.additional_context) > 0:
            additional_context = "\n## Additional Context\n"
            additional_context += self.additional_context
            additional_context += "\n"

        if self.mode == AccuracyEvalMode.AGENTIC:
            agent_description = accuracy_agentic_mode_system_prompt
        else:
            agent_description = accuracy_reasoning_mode_system_prompt.substitute(
                additional_guidelines=additional_guidelines,
                additional_context=additional_context,
            )

        return Agent(
            model=model,
            description=agent_description,
            response_model=AccuracyAgentResponse,
            structured_outputs=True,
        )

    def get_eval_expected_output(self) -> Union[str, list[str]]:
        """Return the eval expected answer. If it is a callable, call it and return the resulting string"""
        if callable(self.expected_output):
            _output = self.expected_output()
            if isinstance(_output, str):
                return _output
            else:
                raise EvalError(f"The expected output needs to be or return a string, but it returned: {type(_output)}")
        return self.expected_output

    def get_eval_input(self) -> str:
        """Return the evaluation input. If it is a callable, call it and return the resulting string"""
        if callable(self.input):
            _input = self.input()
            if isinstance(_input, str):
                return _input
            else:
                raise EvalError(f"The eval input needs to be or return a string, but it returned: {type(_input)}")
        return self.input

    def evaluate_answer(
        self,
        input: str,
        evaluator_input: str,
        expected_output: Union[str, list[str]],
        agent_output: str,
        evaluator_agent: Optional[Agent] = None,
    ) -> Optional[AccuracyEvaluation]:
        """Orchestrate the evaluation process."""
        try:
            if self.mode == AccuracyEvalMode.BASIC:
                if isinstance(expected_output, list):
                    score = 10 if agent_output in expected_output else 0
                else:
                    score = 10 if agent_output == expected_output else 0
                return AccuracyEvaluation(
                    input=input,
                    output=agent_output,
                    expected_output=expected_output,
                    score=score,
                    reason="",
                    passing_score=self.passing_score,
                )
            else:
                if evaluator_agent is None:
                    raise EvalError("Evaluator agent is required for the reasoning mode.")
                accuracy_agent_response = evaluator_agent.run(evaluator_input).content
                if accuracy_agent_response is None or not isinstance(accuracy_agent_response, AccuracyAgentResponse):
                    raise EvalError(f"Evaluator Agent returned an invalid response: {accuracy_agent_response}")
                return AccuracyEvaluation(
                    input=input,
                    output=agent_output,
                    expected_output=expected_output,
                    score=accuracy_agent_response.accuracy_score,
                    reason=accuracy_agent_response.accuracy_reason,
                    passing_score=self.passing_score,
                )
        except Exception as e:
            logger.exception(f"Failed to perform the evaluation: {e}")
            return None

    async def aevaluate_answer(
        self,
        input: str,
        evaluator_agent: Agent,
        evaluation_input: str,
        evaluator_expected_output: str,
        agent_output: str,
    ) -> Optional[AccuracyEvaluation]:
        """Orchestrate the evaluation process asynchronously."""
        try:
            response = await evaluator_agent.arun(evaluation_input)
            accuracy_agent_response = response.content
            if accuracy_agent_response is None or not isinstance(accuracy_agent_response, AccuracyAgentResponse):
                raise EvalError(f"Evaluator Agent returned an invalid response: {accuracy_agent_response}")
            return AccuracyEvaluation(
                input=input,
                output=agent_output,
                expected_output=evaluator_expected_output,
                score=accuracy_agent_response.accuracy_score,
                reason=accuracy_agent_response.accuracy_reason,
                passing_score=self.passing_score,
            )
        except Exception as e:
            logger.exception(f"Failed to evaluate accuracy asynchronously: {e}")
            return None

    def run(
        self,
        *,
        print_summary: bool = True,
        print_results: bool = True,
    ) -> Optional[AccuracyResult]:
        if self.agent is None and self.team is None:
            raise ValueError("You need to provide one of 'agent' or 'team' to run the evaluation.")

        if self.agent is not None and self.team is not None:
            raise ValueError("Provide only one of 'agent' or 'team' to run the evaluation.")

        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        self._warn_configuration_conflicts()
        self.result = AccuracyResult(passing_score=self.passing_score)

        logger.debug(f"************ Evaluation Start: {self.eval_id} ************")

        console = Console()

        with Live(console=console, transient=True) as live_log:
            evaluator_agent = self.get_evaluator_agent() if self.mode != AccuracyEvalMode.BASIC else None
            eval_input = self.get_eval_input()
            eval_expected_output = self.get_eval_expected_output()

            for i in range(self.num_iterations):
                status = Status(f"Running evaluation {i + 1}...", spinner="dots", speed=1.0, refresh_per_second=10)
                live_log.update(status)

                if self.agent is not None:
                    output = self.agent.run(message=eval_input).content
                elif self.team is not None:
                    output = self.team.run(message=eval_input).content

                if not output:
                    logger.error(f"Failed to generate a valid answer on iteration {i + 1}: {output}")
                    continue

                evaluator_input = accuracy_evaluator_input.substitute(
                    eval_input=eval_input, eval_expected_output=str(eval_expected_output), agent_output=output
                )
                logger.debug(f"Agent output #{i + 1}: {output}")

                result = self.evaluate_answer(
                    input=eval_input,
                    evaluator_input=evaluator_input,
                    evaluator_agent=evaluator_agent,
                    expected_output=eval_expected_output,
                    agent_output=output,
                )
                if result is None:
                    logger.error(f"Failed to evaluate accuracy on iteration {i + 1}")
                    continue

                self.result.results.append(result)
                self.result.compute_stats()
                status.update(f"Eval iteration {i + 1} finished")

            status.stop()

        # Save result to file if requested
        if self.file_path_to_save_results is not None and self.result is not None:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                name=self.name,
                eval_id=self.eval_id,
                result=self.result,
            )

        # Print results if requested
        if self.print_results or print_results:
            self.result.print_results(console)
        if self.print_summary or print_summary:
            self.result.print_summary(console)

        # Log results to the Agno platform if requested
        if self.agent is not None:
            agent_id = self.agent.agent_id
            team_id = None
            model_id = self.agent.model.id if self.agent.model is not None else None
            model_provider = self.agent.model.provider if self.agent.model is not None else None
            evaluated_entity_name = self.agent.name
        elif self.team is not None:
            agent_id = None
            team_id = self.team.team_id
            model_id = self.team.model.id if self.team.model is not None else None
            model_provider = self.team.model.provider if self.team.model is not None else None
            evaluated_entity_name = self.team.name

        if self.monitoring:
            log_eval_run(
                run_id=self.eval_id,  # type: ignore
                run_data=asdict(self.result),
                eval_type=EvalType.ACCURACY,
                agent_id=agent_id,
                team_id=team_id,
                model_id=model_id,
                model_provider=model_provider,
                name=self.name if self.name is not None else None,
                evaluated_entity_name=evaluated_entity_name,
            )

        logger.debug(f"*********** Evaluation {self.eval_id} Finished ***********")
        return self.result

    async def arun(
        self,
        *,
        print_summary: bool = True,
        print_results: bool = True,
    ) -> Optional[AccuracyResult]:
        if self.agent is None and self.team is None:
            raise ValueError("You need to provide one of 'agent' or 'team' to run the evaluation.")

        if self.agent is not None and self.team is not None:
            raise ValueError("Provide only one of 'agent' or 'team' to run the evaluation.")

        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()

        self.result = AccuracyResult(passing_score=self.passing_score)

        logger.debug(f"************ Evaluation Start: {self.eval_id} ************")

        # Add a spinner while running the evaluations
        console = Console()
        with Live(console=console, transient=True) as live_log:
            evaluator_agent = self.get_evaluator_agent()
            eval_input = self.get_eval_input()
            eval_expected_output = self.get_eval_expected_output()

            for i in range(self.num_iterations):
                status = Status(f"Running evaluation {i + 1}...", spinner="dots", speed=1.0, refresh_per_second=10)
                live_log.update(status)

                if self.agent is not None:
                    response = await self.agent.arun(message=eval_input)
                    output = response.content
                elif self.team is not None:
                    response = await self.team.arun(message=eval_input)
                    output = response.content

                if not output:
                    logger.error(f"Failed to generate a valid answer on iteration {i + 1}: {output}")
                    continue

                evaluation_input = dedent(f"""\
                    <agent_input>
                    {eval_input}
                    </agent_input>

                    <expected_output>
                    {eval_expected_output}
                    </expected_output>

                    <agent_output>
                    {output}
                    </agent_output>\
                    """)
                logger.debug(f"Agent output #{i + 1}: {output}")
                result = await self.aevaluate_answer(
                    input=eval_input,
                    evaluator_agent=evaluator_agent,
                    evaluation_input=evaluation_input,
                    evaluator_expected_output=eval_expected_output,
                    agent_output=output,
                )
                if result is None:
                    logger.error(f"Failed to evaluate accuracy on iteration {i + 1}")
                    continue

                self.result.results.append(result)
                self.result.compute_stats()
                status.update(f"Eval iteration {i + 1} finished")

            status.stop()

        # Save result to file if requested
        if self.file_path_to_save_results is not None and self.result is not None:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                name=self.name,
                eval_id=self.eval_id,
                result=self.result,
            )

        # Print results if requested
        if self.print_results or print_results:
            self.result.print_results(console)
        if self.print_summary or print_summary:
            self.result.print_summary(console)

        # Log results to the Agno platform if requested
        if self.monitoring:
            await async_log_eval_run(
                run_id=self.eval_id,  # type: ignore
                run_data=asdict(self.result),
                eval_type=EvalType.ACCURACY,
                agent_id=self.agent.agent_id if self.agent is not None else None,
                model_id=self.agent.model.id if self.agent is not None and self.agent.model is not None else None,
                model_provider=self.agent.model.provider
                if self.agent is not None and self.agent.model is not None
                else None,
                name=self.name if self.name is not None else None,
                evaluated_entity_name=self.agent.name if self.agent is not None else None,
            )

        logger.debug(f"*********** Evaluation {self.eval_id} Finished ***********")
        return self.result

    def run_with_output(
        self,
        *,
        output: str,
        print_summary: bool = True,
        print_results: bool = True,
    ) -> Optional[AccuracyResult]:
        """Run the evaluation logic against the given answer, instead of generating an answer with the Agent"""
        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        self._warn_configuration_conflicts()
        self.result = AccuracyResult(passing_score=self.passing_score)

        logger.debug(f"************ Evaluation Start: {self.eval_id} ************")

        evaluator_agent = self.get_evaluator_agent() if self.mode != AccuracyEvalMode.BASIC else None
        eval_input = self.get_eval_input()
        eval_expected_output = self.get_eval_expected_output()

        evaluator_input = accuracy_evaluator_input.substitute(
            eval_input=eval_input, eval_expected_output=str(eval_expected_output), agent_output=output
        )
        result = self.evaluate_answer(
            input=eval_input,
            evaluator_input=evaluator_input,
            evaluator_agent=evaluator_agent,
            expected_output=eval_expected_output,
            agent_output=output,
        )

        if result is not None:
            self.result.results.append(result)
            self.result.compute_stats()

            # Print results if requested
            if self.print_results or print_results:
                self.result.print_results()
            if self.print_summary or print_summary:
                self.result.print_summary()

            # Save result to file if requested
            if self.file_path_to_save_results is not None:
                store_result_in_file(
                    file_path=self.file_path_to_save_results,
                    name=self.name,
                    eval_id=self.eval_id,
                    result=self.result,
                )
        # Log results to the Agno platform if requested
        if self.monitoring:
            if self.agent is not None:
                agent_id = self.agent.agent_id
                team_id = None
                model_id = self.agent.model.id if self.agent.model is not None else None
                model_provider = self.agent.model.provider if self.agent.model is not None else None
                evaluated_entity_name = self.agent.name
            elif self.team is not None:
                agent_id = None
                team_id = self.team.team_id
                model_id = self.team.model.id if self.team.model is not None else None
                model_provider = self.team.model.provider if self.team.model is not None else None
                evaluated_entity_name = self.team.name
            else:
                agent_id = None
                team_id = None
                model_id = None
                model_provider = None
                evaluated_entity_name = None

            log_eval_run(
                run_id=self.eval_id,  # type: ignore
                run_data=asdict(self.result),
                eval_type=EvalType.ACCURACY,
                name=self.name if self.name is not None else None,
                agent_id=agent_id,
                team_id=team_id,
                model_id=model_id,
                model_provider=model_provider,
                evaluated_entity_name=evaluated_entity_name,
            )

        logger.debug(f"*********** Evaluation End: {self.eval_id} ***********")
        return self.result

    async def arun_with_output(
        self,
        *,
        output: str,
        print_summary: bool = True,
        print_results: bool = True,
    ) -> Optional[AccuracyResult]:
        """Run the evaluation logic against the given answer, instead of generating an answer with the Agent"""
        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()

        self.result = AccuracyResult(passing_score=self.passing_score)

        logger.debug(f"************ Evaluation Start: {self.eval_id} ************")

        evaluator_agent = self.get_evaluator_agent()
        eval_input = self.get_eval_input()
        eval_expected_output = self.get_eval_expected_output()

        evaluation_input = dedent(f"""\
            <agent_input>
            {eval_input}
            </agent_input>

            <expected_output>
            {eval_expected_output}
            </expected_output>

            <agent_output>
            {output}
            </agent_output>\
            """)

        result = await self.aevaluate_answer(
            input=eval_input,
            evaluator_agent=evaluator_agent,
            evaluation_input=evaluation_input,
            evaluator_expected_output=str(eval_expected_output),
            agent_output=output,
        )

        if result is not None:
            self.result.results.append(result)
            self.result.compute_stats()

            # Print results if requested
            if self.print_results or print_results:
                self.result.print_results()
            if self.print_summary or print_summary:
                self.result.print_summary()

            # Save result to file if requested
            if self.file_path_to_save_results is not None:
                store_result_in_file(
                    file_path=self.file_path_to_save_results,
                    name=self.name,
                    eval_id=self.eval_id,
                    result=self.result,
                )
        # Log results to the Agno platform if requested
        if self.monitoring:
            if self.agent is not None:
                agent_id = self.agent.agent_id
                team_id = None
                model_id = self.agent.model.id if self.agent.model is not None else None
                model_provider = self.agent.model.provider if self.agent.model is not None else None
                evaluated_entity_name = self.agent.name
            elif self.team is not None:
                agent_id = None
                team_id = self.team.team_id
                model_id = self.team.model.id if self.team.model is not None else None
                model_provider = self.team.model.provider if self.team.model is not None else None
                evaluated_entity_name = self.team.name

            await async_log_eval_run(
                run_id=self.eval_id,  # type: ignore
                run_data=asdict(self.result),
                eval_type=EvalType.ACCURACY,
                name=self.name if self.name is not None else None,
                agent_id=agent_id,
                team_id=team_id,
                model_id=model_id,
                model_provider=model_provider,
                evaluated_entity_name=evaluated_entity_name,
            )

        logger.debug(f"*********** Evaluation End: {self.eval_id} ***********")
        return self.result
