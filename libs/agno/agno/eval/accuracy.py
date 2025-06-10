from dataclasses import asdict, dataclass, field
from os import getenv
from textwrap import dedent
from typing import TYPE_CHECKING, Callable, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.api.schemas.evals import EvalType
from agno.eval.utils import async_log_eval_run, log_eval_run, store_result_in_file
from agno.exceptions import EvalError
from agno.models.base import Model
from agno.team.team import Team
from agno.utils.log import logger, set_log_level_to_debug, set_log_level_to_info

if TYPE_CHECKING:
    from rich.console import Console


class AccuracyAgentResponse(BaseModel):
    accuracy_score: int = Field(..., description="Accuracy Score between 1 and 10 assigned to the Agent's answer.")
    accuracy_reason: str = Field(..., description="Detailed reasoning for the accuracy score.")


@dataclass
class AccuracyEvaluation:
    input: str
    output: str
    expected_output: str
    score: int
    reason: str

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
        results_table.add_row("Expected Output", self.expected_output)
        results_table.add_row("Accuracy Score", f"{str(self.score)}/10")
        results_table.add_row("Accuracy Reason", Markdown(self.reason))
        console.print(results_table)


@dataclass
class AccuracyResult:
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
            results_table.add_row("Expected Output", result.expected_output)
            results_table.add_row("Accuracy Score", f"{str(result.score)}/10")
            results_table.add_row("Accuracy Reason", result.reason)
        console.print(results_table)


@dataclass
class AccuracyEval:
    """Interface to evaluate the accuracy of an Agent or Team, given a prompt and expected answer"""

    # Input to evaluate
    input: Union[str, Callable]
    # Expected answer to the input
    expected_output: Union[str, Callable]
    # Agent to evaluate
    agent: Optional[Agent] = None
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

        return Agent(
            model=model,
            description=f"""\
You are an expert judge tasked with comparing the quality of an AI Agent’s output to a user-provided expected output. You must assume the expected_output is correct - even if you personally disagree.

## Evaluation Inputs
- agent_input: The original task or query given to the Agent.
- expected_output: The correct response to the task (provided by the user).
    - NOTE: You must assume the expected_output is correct - even if you personally disagree.
- agent_output: The response generated by the Agent.

## Evaluation Criteria
- Accuracy: How closely does the agent_output match the expected_output?
- Completeness: Does the agent_output include all the key elements of the expected_output?

## Instructions
1. Compare the agent_output only to the expected_output, not what you think the expected_output should be.
2. Do not judge the correctness of the expected_output itself. Your role is only to compare the two outputs, the user provided expected_output is correct.
3. Follow the additional guidelines if provided.
4. Provide a detailed analysis including:
    - Specific similarities and differences
    - Important points included or omitted
    - Any inaccuracies, paraphrasing errors, or structural differences
5. Reference the criteria explicitly in your reasoning.
6. Assign a score from 1 to 10 (whole numbers only):
   1-2: Completely incorrect or irrelevant.
   3-4: Major inaccuracies or missing key information.
   5-6: Partially correct, but with significant issues.
   7-8: Mostly accurate and complete, with minor issues
   9-10: Highly accurate and complete, matching the expected answer and given guidelines closely.
{additional_guidelines}{additional_context}
Remember: You must only compare the agent_output to the expected_output. The expected_output is correct as it was provided by the user.
""",
            response_model=AccuracyAgentResponse,
            structured_outputs=True,
        )

    def get_eval_expected_output(self) -> str:
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
        evaluator_agent: Agent,
        evaluation_input: str,
        evaluator_expected_output: str,
        agent_output: str,
    ) -> Optional[AccuracyEvaluation]:
        """Orchestrate the evaluation process."""
        try:
            accuracy_agent_response = evaluator_agent.run(evaluation_input).content
            if accuracy_agent_response is None or not isinstance(accuracy_agent_response, AccuracyAgentResponse):
                raise EvalError(f"Evaluator Agent returned an invalid response: {accuracy_agent_response}")
            return AccuracyEvaluation(
                input=input,
                output=agent_output,
                expected_output=evaluator_expected_output,
                score=accuracy_agent_response.accuracy_score,
                reason=accuracy_agent_response.accuracy_reason,
            )
        except Exception as e:
            logger.exception(f"Failed to evaluate accuracy: {e}")
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
            logger.error("You need to provide one of 'agent' or 'team' to run the evaluation.")
            return None

        if self.agent is not None and self.team is not None:
            logger.error("Provide only one of 'agent' or 'team' to run the evaluation.")
            return None

        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()

        self.result = AccuracyResult()

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
                    output = self.agent.run(message=eval_input).content
                elif self.team is not None:
                    output = self.team.run(message=eval_input).content

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
                result = self.evaluate_answer(
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
            logger.error("You need to provide one of 'agent' or 'team' to run the evaluation.")
            return None

        if self.agent is not None and self.team is not None:
            logger.error("Provide only one of 'agent' or 'team' to run the evaluation.")
            return None

        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()

        self.result = AccuracyResult()

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

        self.result = AccuracyResult()

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

        result = self.evaluate_answer(
            input=eval_input,
            evaluator_agent=evaluator_agent,
            evaluation_input=evaluation_input,
            evaluator_expected_output=eval_expected_output,
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

        self.result = AccuracyResult()

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
            evaluator_expected_output=eval_expected_output,
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
