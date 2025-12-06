from dataclasses import asdict, dataclass, field
from os import getenv
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.evals import EvalType
from agno.eval.base import BaseEval
from agno.eval.utils import async_log_eval, log_eval_run, store_result_in_file
from agno.exceptions import EvalError
from agno.models.base import Model
from agno.run.agent import RunInput, RunOutput
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.utils.log import logger, set_log_level_to_debug, set_log_level_to_info

if TYPE_CHECKING:
    from rich.console import Console


class CriteriaJudgeResponse(BaseModel):
    """Response schema for the LLM judge."""

    score: int = Field(..., description="Score between 1 and 10 based on the evaluation criteria.")
    reason: str = Field(..., description="Detailed reasoning for the score.")


@dataclass
class CriteriaEvaluation:
    """Result of a single criteria evaluation."""

    input: str
    output: str
    criteria: str
    score: int
    reason: str
    passed: bool

    def print_eval(self, console: Optional["Console"] = None):
        from rich.box import ROUNDED
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.table import Table

        if console is None:
            console = Console()

        status_style = "green" if self.passed else "red"
        status_text = "PASSED" if self.passed else "FAILED"

        results_table = Table(
            box=ROUNDED,
            border_style="blue",
            show_header=False,
            title="[ Criteria Evaluation ]",
            title_style="bold sky_blue1",
            title_justify="center",
        )
        results_table.add_row("Input", self.input[:200] + "..." if len(self.input) > 200 else self.input)
        results_table.add_row("Output", self.output[:200] + "..." if len(self.output) > 200 else self.output)
        results_table.add_row("Score", f"{self.score}/10")
        results_table.add_row("Status", f"[{status_style}]{status_text}[/{status_style}]")
        results_table.add_row("Reason", Markdown(self.reason))
        console.print(results_table)


@dataclass
class CriteriaResult:
    """Aggregated results from criteria evaluations."""

    results: List[CriteriaEvaluation] = field(default_factory=list)
    avg_score: float = field(init=False)
    min_score: float = field(init=False)
    max_score: float = field(init=False)
    std_dev_score: float = field(init=False)
    pass_rate: float = field(init=False)

    def __post_init__(self):
        self.compute_stats()

    def compute_stats(self):
        import statistics

        if self.results and len(self.results) > 0:
            scores = [r.score for r in self.results]
            passed = [r.passed for r in self.results]
            self.avg_score = statistics.mean(scores)
            self.min_score = min(scores)
            self.max_score = max(scores)
            self.std_dev_score = statistics.stdev(scores) if len(scores) > 1 else 0.0
            self.pass_rate = sum(passed) / len(passed) * 100
        else:
            self.avg_score = 0.0
            self.min_score = 0.0
            self.max_score = 0.0
            self.std_dev_score = 0.0
            self.pass_rate = 0.0

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
            title="[ Criteria Evaluation Summary ]",
            title_style="bold sky_blue1",
            title_justify="center",
        )
        summary_table.add_row("Number of Evaluations", f"{len(self.results)}")
        summary_table.add_row("Pass Rate", f"{self.pass_rate:.1f}%")
        summary_table.add_row("Average Score", f"{self.avg_score:.2f}/10")
        summary_table.add_row("Min Score", f"{self.min_score:.2f}/10")
        summary_table.add_row("Max Score", f"{self.max_score:.2f}/10")
        if self.std_dev_score > 0:
            summary_table.add_row("Std Deviation", f"{self.std_dev_score:.2f}")
        console.print(summary_table)

    def print_results(self, console: Optional["Console"] = None):
        for result in self.results:
            result.print_eval(console)


@dataclass
class CriteriaEval(BaseEval):
    """Evaluate agent outputs using custom criteria with an LLM judge."""

    # Core evaluation fields
    criteria: str = ""
    threshold: int = 7
    on_fail: Optional[Callable[["CriteriaEvaluation"], None]] = None
    additional_guidelines: Optional[Union[str, List[str]]] = None
    additional_context: Optional[str] = None

    # Evaluation metadata
    name: Optional[str] = None
    eval_id: str = field(default_factory=lambda: str(uuid4()))
    num_iterations: int = 1
    run_id: Optional[str] = None
    result: Optional[CriteriaResult] = None

    # Model configuration
    model: Optional[Model] = None

    # Output options
    print_summary: bool = False
    print_results: bool = False
    file_path_to_save_results: Optional[str] = None
    debug_mode: bool = getenv("AGNO_DEBUG", "false").lower() == "true"
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    telemetry: bool = True

    def get_evaluator_agent(self) -> Agent:
        """Build the evaluator agent with criteria-based instructions."""
        model = self.model
        if model is None:
            try:
                from agno.models.openai import OpenAIChat

                model = OpenAIChat(id="gpt-4o-mini")
            except (ModuleNotFoundError, ImportError) as e:
                logger.exception(e)
                raise EvalError(
                    "Agno uses `openai` as the default model provider. Please run `pip install openai` to use the default evaluator."
                )

        # Format additional guidelines
        additional_guidelines = ""
        if self.additional_guidelines:
            guidelines_text = (
                self.additional_guidelines
                if isinstance(self.additional_guidelines, str)
                else "\n- " + "\n- ".join(self.additional_guidelines)
            )
            additional_guidelines = f"\n## Additional Guidelines\n{guidelines_text}\n"

        # Format additional context
        additional_context = (
            f"\n## Additional Context\n{self.additional_context}\n" if self.additional_context else ""
        )

        return Agent(
            model=model,
            description=f"""\
You are an expert evaluator. Score the output based on these criteria:

## Criteria
{self.criteria}

## Scoring (1-10)
- 1-2: Completely fails the criteria
- 3-4: Major issues
- 5-6: Partial success with significant issues
- 7-8: Mostly meets criteria with minor issues
- 9-10: Fully meets or exceeds criteria

## Instructions
1. Carefully evaluate the output against the criteria above
2. Follow the additional guidelines if provided
3. Provide detailed reasoning that references specific parts of the output
4. Assign a score from 1 to 10 (whole numbers only)
{additional_guidelines}{additional_context}
Be objective and thorough in your evaluation.
""",
            output_schema=CriteriaJudgeResponse,
            structured_outputs=True,
        )

    def _evaluate(self, input: str, output: str, evaluator_agent: Agent) -> Optional[CriteriaEvaluation]:
        """Evaluate a single input/output pair."""
        try:
            prompt = dedent(f"""\
                <input>
                {input}
                </input>

                <output>
                {output}
                </output>
            """)

            response = evaluator_agent.run(prompt).content
            if not isinstance(response, CriteriaJudgeResponse):
                raise EvalError(f"Invalid response: {response}")

            passed = response.score >= self.threshold
            evaluation = CriteriaEvaluation(
                input=input,
                output=output,
                criteria=self.criteria,
                score=response.score,
                reason=response.reason,
                passed=passed,
            )

            # Trigger on_fail callback if evaluation failed
            if not passed and self.on_fail:
                try:
                    self.on_fail(evaluation)
                except Exception as e:
                    logger.warning(f"on_fail callback error: {e}")

            return evaluation
        except Exception as e:
            logger.exception(f"Evaluation failed: {e}")
            return None

    async def _aevaluate(self, input: str, output: str, evaluator_agent: Agent) -> Optional[CriteriaEvaluation]:
        """Evaluate a single input/output pair asynchronously."""
        try:
            prompt = dedent(f"""\
                <input>
                {input}
                </input>

                <output>
                {output}
                </output>
            """)

            response = await evaluator_agent.arun(prompt)
            judge_response = response.content
            if not isinstance(judge_response, CriteriaJudgeResponse):
                raise EvalError(f"Invalid response: {judge_response}")

            passed = judge_response.score >= self.threshold
            evaluation = CriteriaEvaluation(
                input=input,
                output=output,
                criteria=self.criteria,
                score=judge_response.score,
                reason=judge_response.reason,
                passed=passed,
            )

            # Trigger on_fail callback if evaluation failed
            if not passed and self.on_fail:
                try:
                    self.on_fail(evaluation)
                except Exception as e:
                    logger.warning(f"on_fail callback error: {e}")

            return evaluation
        except Exception as e:
            logger.exception(f"Async evaluation failed: {e}")
            return None

    def _log_eval_to_db(
        self,
        agent_id: Optional[str] = None,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        team_id: Optional[str] = None,
        evaluated_component_name: Optional[str] = None,
    ) -> None:
        """Helper to log evaluation to database."""
        if not self.db or not self.run_id:
            return

        log_eval_run(
            db=self.db,  # type: ignore
            run_id=self.run_id,
            run_data=asdict(self.result) if self.result else {},
            eval_type=EvalType.CRITERIA,
            agent_id=agent_id,
            model_id=model_id,
            model_provider=model_provider,
            name=self.name,
            team_id=team_id,
            evaluated_component_name=evaluated_component_name,
            eval_input={"criteria": self.criteria, "threshold": self.threshold},
        )

    async def _async_log_eval_to_db(
        self,
        agent_id: Optional[str] = None,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        team_id: Optional[str] = None,
        evaluated_component_name: Optional[str] = None,
    ) -> None:
        """Helper to log evaluation to database asynchronously."""
        if not self.db or not self.run_id:
            return

        await async_log_eval(
            db=self.db,
            run_id=self.run_id,
            run_data=asdict(self.result) if self.result else {},
            eval_type=EvalType.CRITERIA,
            agent_id=agent_id,
            model_id=model_id,
            model_provider=model_provider,
            name=self.name,
            team_id=team_id,
            evaluated_component_name=evaluated_component_name,
            eval_input={"criteria": self.criteria, "threshold": self.threshold},
        )

    def run(
        self,
        *,
        input: Optional[str] = None,
        output: Optional[str] = None,
        cases: Optional[List[Dict[str, str]]] = None,
        print_summary: bool = False,
        print_results: bool = False,
    ) -> Optional[CriteriaResult]:
        """Evaluate input/output against the criteria.

        Supports both single evaluation and batch evaluation:

        Args:
            input: Input text for single evaluation
            output: Output text for single evaluation
            cases: List of input/output pairs for batch evaluation
            print_summary: Whether to print summary
            print_results: Whether to print detailed results
        """
        # Validate parameters
        single_mode = input is not None or output is not None
        batch_mode = cases is not None

        if single_mode and batch_mode:
            raise ValueError("Provide either (input, output) OR cases, not both")

        if not single_mode and not batch_mode:
            raise ValueError("Must provide either (input, output) OR cases")

        # Batch mode if cases provided
        if batch_mode and cases is not None:
            return self.run_batch(cases, print_summary=print_summary, print_results=print_results)

        # Validate single mode has both input and output
        if input is None or output is None:
            raise ValueError("Both input and output are required for single evaluation")

        # Single evaluation logic
        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("Use arun() with async DB.")

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        self.result = CriteriaResult()

        console = Console()
        with Live(console=console, transient=True) as live_log:
            evaluator = self.get_evaluator_agent()

            for i in range(self.num_iterations):
                status = Status(f"Running evaluation {i + 1}...", spinner="dots", speed=1.0, refresh_per_second=10)
                live_log.update(status)

                evaluation = self._evaluate(input=input, output=output, evaluator_agent=evaluator)

                if evaluation:
                    self.result.results.append(evaluation)
                    self.result.compute_stats()

                status.stop()

        # Save result to file
        if self.file_path_to_save_results and self.result:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                result=self.result,
                eval_id=self.eval_id,
                name=self.name,
            )

        # Print results
        if self.print_results or print_results:
            self.result.print_results(console)
        if self.print_summary or print_summary:
            self.result.print_summary(console)

        # Generate unique run_id for each execution
        self.run_id = str(uuid4())

        # Log to DB
        self._log_eval_to_db()

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, create_eval_run_telemetry

            create_eval_run_telemetry(
                eval_run=EvalRunCreate(run_id=self.run_id, eval_type=EvalType.CRITERIA, data=self._get_telemetry_data())
            )

        return self.result

    async def arun(
        self,
        *,
        input: Optional[str] = None,
        output: Optional[str] = None,
        cases: Optional[List[Dict[str, str]]] = None,
        print_summary: bool = False,
        print_results: bool = False,
    ) -> Optional[CriteriaResult]:
        """Evaluate input/output against the criteria asynchronously.

        Supports both single evaluation and batch evaluation:

        Args:
            input: Input text for single evaluation
            output: Output text for single evaluation
            cases: List of input/output pairs for batch evaluation
            print_summary: Whether to print summary
            print_results: Whether to print detailed results
        """
        # Validate parameters
        single_mode = input is not None or output is not None
        batch_mode = cases is not None

        if single_mode and batch_mode:
            raise ValueError("Provide either (input, output) OR cases, not both")

        if not single_mode and not batch_mode:
            raise ValueError("Must provide either (input, output) OR cases")

        # Batch mode if cases provided
        if batch_mode and cases is not None:
            return await self.arun_batch(cases, print_summary=print_summary, print_results=print_results)

        # Validate single mode has both input and output
        if input is None or output is None:
            raise ValueError("Both input and output are required for single evaluation")

        # Single evaluation logic
        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        self.result = CriteriaResult()

        console = Console()
        with Live(console=console, transient=True) as live_log:
            evaluator = self.get_evaluator_agent()

            for i in range(self.num_iterations):
                status = Status(f"Running evaluation {i + 1}...", spinner="dots", speed=1.0, refresh_per_second=10)
                live_log.update(status)

                evaluation = await self._aevaluate(input=input, output=output, evaluator_agent=evaluator)

                if evaluation:
                    self.result.results.append(evaluation)
                    self.result.compute_stats()

                status.stop()

        # Save result to file
        if self.file_path_to_save_results and self.result:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                result=self.result,
                eval_id=self.eval_id,
                name=self.name,
            )

        # Print results
        if self.print_results or print_results:
            self.result.print_results(console)
        if self.print_summary or print_summary:
            self.result.print_summary(console)

        # Generate unique run_id for each execution
        self.run_id = str(uuid4())

        # Log to DB
        await self._async_log_eval_to_db()

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, async_create_eval_run_telemetry

            await async_create_eval_run_telemetry(
                eval_run=EvalRunCreate(run_id=self.run_id, eval_type=EvalType.CRITERIA, data=self._get_telemetry_data())
            )

        return self.result

    def run_batch(
        self,
        cases: List[Dict[str, str]],
        *,
        print_summary: bool = True,
        print_results: bool = False,
    ) -> Optional[CriteriaResult]:
        """Evaluate multiple input/output pairs.

        Args:
            cases: List of dicts with 'input' and 'output' keys
        """
        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("Use arun_batch() with async DB.")

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        self.result = CriteriaResult()

        console = Console()
        with Live(console=console, transient=True) as live_log:
            evaluator = self.get_evaluator_agent()

            for i, case in enumerate(cases):
                for iteration in range(self.num_iterations):
                    if self.num_iterations > 1:
                        status = Status(
                            f"Evaluating {i + 1}/{len(cases)} (iteration {iteration + 1}/{self.num_iterations})...",
                            spinner="dots",
                        )
                    else:
                        status = Status(f"Evaluating {i + 1}/{len(cases)}...", spinner="dots")
                    live_log.update(status)

                    evaluation = self._evaluate(input=case["input"], output=case["output"], evaluator_agent=evaluator)
                    if evaluation:
                        self.result.results.append(evaluation)
                        self.result.compute_stats()

            status.stop()

        # Save result to file
        if self.file_path_to_save_results and self.result:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                result=self.result,
                eval_id=self.eval_id,
                name=self.name,
            )

        # Print results
        if self.print_results or print_results:
            self.result.print_results(console)
        if self.print_summary or print_summary:
            self.result.print_summary(console)

        # Generate unique run_id for each execution
        self.run_id = str(uuid4())

        # Log to DB
        self._log_eval_to_db()

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, create_eval_run_telemetry

            create_eval_run_telemetry(
                eval_run=EvalRunCreate(run_id=self.run_id, eval_type=EvalType.CRITERIA, data=self._get_telemetry_data())
            )

        return self.result

    async def arun_batch(
        self,
        cases: List[Dict[str, str]],
        *,
        print_summary: bool = True,
        print_results: bool = False,
    ) -> Optional[CriteriaResult]:
        """Evaluate multiple input/output pairs asynchronously."""
        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        self.result = CriteriaResult()

        console = Console()
        with Live(console=console, transient=True) as live_log:
            evaluator = self.get_evaluator_agent()

            for i, case in enumerate(cases):
                for iteration in range(self.num_iterations):
                    if self.num_iterations > 1:
                        status = Status(
                            f"Evaluating {i + 1}/{len(cases)} (iteration {iteration + 1}/{self.num_iterations})...",
                            spinner="dots",
                        )
                    else:
                        status = Status(f"Evaluating {i + 1}/{len(cases)}...", spinner="dots")
                    live_log.update(status)

                    evaluation = await self._aevaluate(
                        input=case["input"], output=case["output"], evaluator_agent=evaluator
                    )
                    if evaluation:
                        self.result.results.append(evaluation)
                        self.result.compute_stats()

            status.stop()

        # Save result to file
        if self.file_path_to_save_results and self.result:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                result=self.result,
                eval_id=self.eval_id,
                name=self.name,
            )

        # Print results
        if self.print_results or print_results:
            self.result.print_results(console)
        if self.print_summary or print_summary:
            self.result.print_summary(console)

        # Generate unique run_id for each execution
        self.run_id = str(uuid4())

        # Log to DB
        await self._async_log_eval_to_db()

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, async_create_eval_run_telemetry

            await async_create_eval_run_telemetry(
                eval_run=EvalRunCreate(run_id=self.run_id, eval_type=EvalType.CRITERIA, data=self._get_telemetry_data())
            )

        return self.result

    def _get_telemetry_data(self) -> Dict[str, Any]:
        return {
            "criteria_length": len(self.criteria) if self.criteria else 0,
            "threshold": self.threshold,
            "num_results": len(self.result.results) if self.result else 0,
            "num_iterations": self.num_iterations,
        }

    # BaseEval hook methods
    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Perform sync pre-check to validate input before agent runs."""
        input_str = run_input.input_content_string() if run_input else ""
        output_str = "(Input validation - no output yet)"

        # Temporarily disable DB logging and add pre-hook instruction
        original_db = self.db
        original_guidelines = self.additional_guidelines
        self.db = None

        # Prepend pre-hook instruction to evaluate input quality
        pre_hook_instruction = "IMPORTANT: This is PRE-HOOK evaluation. Evaluate the INPUT quality (shown in Input field), NOT the output. The output is a placeholder. Score the INPUT based on the criteria."

        if original_guidelines:
            if isinstance(original_guidelines, str):
                self.additional_guidelines = [pre_hook_instruction, original_guidelines]
            else:
                self.additional_guidelines = [pre_hook_instruction] + list(original_guidelines)
        else:
            self.additional_guidelines = pre_hook_instruction

        self.run(input=input_str, output=output_str, print_results=self.print_results, print_summary=self.print_summary)

        # Restore DB and guidelines
        self.db = original_db
        self.additional_guidelines = original_guidelines

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("pre_check() requires sync DB. Use async_pre_check() with async DB.")

        self._log_eval_to_db()

    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Perform async pre-check to validate input before agent runs."""
        input_str = run_input.input_content_string() if run_input else ""
        output_str = "(Input validation - no output yet)"

        # Temporarily disable DB logging and add pre-hook instruction
        original_db = self.db
        original_guidelines = self.additional_guidelines
        self.db = None

        # Prepend pre-hook instruction to evaluate INPUT quality
        pre_hook_instruction = "IMPORTANT: This is PRE-HOOK evaluation. Evaluate the INPUT quality (shown in Input field), NOT the output. The output is a placeholder. Score the INPUT based on the criteria."

        if original_guidelines:
            if isinstance(original_guidelines, str):
                self.additional_guidelines = [pre_hook_instruction, original_guidelines]
            else:
                self.additional_guidelines = [pre_hook_instruction] + list(original_guidelines)
        else:
            self.additional_guidelines = pre_hook_instruction

        await self.arun(
            input=input_str, output=output_str, print_results=self.print_results, print_summary=self.print_summary
        )

        # Restore DB and guidelines
        self.db = original_db
        self.additional_guidelines = original_guidelines

        await self._async_log_eval_to_db()

    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Perform sync post-check to evaluate agent output."""
        input_str = run_output.input.input_content_string() if run_output.input else ""
        output_str = str(run_output.content) if run_output.content else ""

        # Temporarily disable DB logging
        original_db = self.db
        self.db = None

        self.run(input=input_str, output=output_str, print_results=self.print_results, print_summary=self.print_summary)

        # Restore DB and log with context from run_output
        self.db = original_db

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("post_check() requires sync DB. Use async_post_check() with async DB.")

        # Extract metadata from run_output
        if isinstance(run_output, RunOutput):
            agent_id = run_output.agent_id
            team_id = None
            model_id = run_output.model
            model_provider = run_output.model_provider
        elif isinstance(run_output, TeamRunOutput):
            agent_id = None
            team_id = run_output.team_id
            model_id = run_output.model
            model_provider = run_output.model_provider

        self._log_eval_to_db(
            agent_id=agent_id,
            model_id=model_id,
            model_provider=model_provider,
            team_id=team_id,
        )

    async def async_post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Perform async post-check to evaluate agent output."""
        input_str = run_output.input.input_content_string() if run_output.input else ""
        output_str = str(run_output.content) if run_output.content else ""

        # Temporarily disable DB logging
        original_db = self.db
        self.db = None

        await self.arun(
            input=input_str, output=output_str, print_results=self.print_results, print_summary=self.print_summary
        )

        # Restore DB and log with context from run_output
        self.db = original_db

        # Extract metadata from run_output
        if isinstance(run_output, RunOutput):
            agent_id = run_output.agent_id
            team_id = None
            model_id = run_output.model
            model_provider = run_output.model_provider
        elif isinstance(run_output, TeamRunOutput):
            agent_id = None
            team_id = run_output.team_id
            model_id = run_output.model
            model_provider = run_output.model_provider

        await self._async_log_eval_to_db(
            agent_id=agent_id,
            model_id=model_id,
            model_provider=model_provider,
            team_id=team_id,
        )
