from dataclasses import asdict, dataclass, field
from inspect import iscoroutinefunction
from os import getenv
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Union
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
from agno.utils.log import log_warning, logger, set_log_level_to_debug, set_log_level_to_info

if TYPE_CHECKING:
    from rich.console import Console


class NumericJudgeResponse(BaseModel):
    """Response schema for numeric scoring mode."""

    score: int = Field(..., ge=1, le=10, description="Score between 1 and 10.")
    reason: str = Field(..., description="Detailed reasoning for the evaluation.")


class BinaryJudgeResponse(BaseModel):
    """Response schema for binary scoring mode."""

    passed: bool = Field(..., description="Pass/fail result.")
    reason: str = Field(..., description="Detailed reasoning for the evaluation.")


@dataclass
class AgentAsJudgeEvaluation:
    """Result of a single agent-as-judge evaluation."""

    input: str
    output: str
    criteria: str
    score: Optional[int]
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
            title="[ Agent As Judge Evaluation ]",
            title_style="bold sky_blue1",
            title_justify="center",
        )
        results_table.add_row("Input", self.input[:200] + "..." if len(self.input) > 200 else self.input)
        results_table.add_row("Output", self.output[:200] + "..." if len(self.output) > 200 else self.output)
        if self.score is not None:
            results_table.add_row("Score", f"{self.score}/10")
        results_table.add_row("Status", f"[{status_style}]{status_text}[/{status_style}]")
        results_table.add_row("Reason", Markdown(self.reason))
        console.print(results_table)


@dataclass
class AgentAsJudgeResult:
    """Aggregated results from agent-as-judge evaluations."""

    run_id: str
    results: List[AgentAsJudgeEvaluation] = field(default_factory=list)
    avg_score: Optional[float] = field(init=False)
    min_score: Optional[float] = field(init=False)
    max_score: Optional[float] = field(init=False)
    std_dev_score: Optional[float] = field(init=False)
    pass_rate: float = field(init=False)

    def __post_init__(self):
        self.compute_stats()

    def compute_stats(self):
        import statistics

        if self.results and len(self.results) > 0:
            passed = [r.passed for r in self.results]
            self.pass_rate = sum(passed) / len(passed) * 100

            # Compute score statistics only for numeric mode (where score is not None)
            scores = [r.score for r in self.results if r.score is not None]
            if scores:
                self.avg_score = statistics.mean(scores)
                self.min_score = min(scores)
                self.max_score = max(scores)
                self.std_dev_score = statistics.stdev(scores) if len(scores) > 1 else 0.0
            else:
                # Binary mode - no scores
                self.avg_score = None
                self.min_score = None
                self.max_score = None
                self.std_dev_score = None
        else:
            self.avg_score = None
            self.min_score = None
            self.max_score = None
            self.std_dev_score = None
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
            title="[ Agent As Judge Evaluation Summary ]",
            title_style="bold sky_blue1",
            title_justify="center",
            padding=(0, 2),  # Add horizontal padding to make table wider
            min_width=45,  # Ensure table is wide enough for title
        )

        num_results = len(self.results)
        summary_table.add_row("Number of Evaluations", f"{num_results}")
        summary_table.add_row("Pass Rate", f"{self.pass_rate:.1f}%")

        # Only show score statistics for numeric mode (when scores exist)
        if self.avg_score is not None:
            # For single evaluation, show "Score" instead of statistics
            if num_results == 1:
                summary_table.add_row("Score", f"{self.avg_score:.2f}/10")
            # For multiple evaluations, show full statistics
            elif num_results > 1:
                summary_table.add_row("Average Score", f"{self.avg_score:.2f}/10")
                summary_table.add_row("Min Score", f"{self.min_score:.2f}/10")
                summary_table.add_row("Max Score", f"{self.max_score:.2f}/10")
                if self.std_dev_score and self.std_dev_score > 0:
                    summary_table.add_row("Std Deviation", f"{self.std_dev_score:.2f}")

        console.print(summary_table)

    def print_results(self, console: Optional["Console"] = None):
        for result in self.results:
            result.print_eval(console)


@dataclass
class AgentAsJudgeEval(BaseEval):
    """Evaluate agent outputs using custom criteria with an LLM judge."""

    # Core evaluation fields
    criteria: str = ""
    scoring_strategy: Literal["numeric", "binary"] = "binary"
    threshold: int = 7  # Only used for numeric strategy
    on_fail: Optional[Callable[["AgentAsJudgeEvaluation"], None]] = None
    additional_guidelines: Optional[Union[str, List[str]]] = None

    # Evaluation metadata
    name: Optional[str] = None

    # Model configuration
    model: Optional[Model] = None
    evaluator_agent: Optional[Agent] = None

    # Output options
    print_summary: bool = False
    print_results: bool = False
    file_path_to_save_results: Optional[str] = None
    debug_mode: bool = getenv("AGNO_DEBUG", "false").lower() == "true"
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    telemetry: bool = True
    run_in_background: bool = False

    def __post_init__(self):
        """Validate scoring_strategy and threshold."""
        if self.scoring_strategy == "numeric" and not 1 <= self.threshold <= 10:
            raise ValueError(f"threshold must be between 1 and 10, got {self.threshold}")

    def get_evaluator_agent(self) -> Agent:
        """Return the evaluator agent. If not provided, build it based on the model and criteria."""
        # Select response schema based on scoring strategy
        response_schema = NumericJudgeResponse if self.scoring_strategy == "numeric" else BinaryJudgeResponse

        if self.evaluator_agent is not None:
            # Ensure custom evaluator has the required output_schema for structured responses
            self.evaluator_agent.output_schema = response_schema
            return self.evaluator_agent

        model = self.model
        if model is None:
            try:
                from agno.models.openai import OpenAIChat

                model = OpenAIChat(id="gpt-5-mini")
            except (ModuleNotFoundError, ImportError) as e:
                logger.exception(e)
                raise EvalError(
                    "Agno uses `openai` as the default model provider. Please run `pip install openai` to use the default evaluator."
                )

        # Build instructions based on scoring strategy
        instructions_parts = ["## Criteria", self.criteria, ""]

        if self.scoring_strategy == "numeric":
            instructions_parts.extend(
                [
                    "## Scoring (1-10)",
                    "- 1-2: Completely fails the criteria",
                    "- 3-4: Major issues",
                    "- 5-6: Partial success with significant issues",
                    "- 7-8: Mostly meets criteria with minor issues",
                    "- 9-10: Fully meets or exceeds criteria",
                    "",
                    "## Instructions",
                    "1. Carefully evaluate the output against the criteria above",
                    "2. Provide a score from 1-10",
                    "3. Provide detailed reasoning that references specific parts of the output",
                ]
            )
        else:  # binary
            instructions_parts.extend(
                [
                    "## Evaluation",
                    "Determine if the output PASSES or FAILS the criteria above.",
                    "",
                    "## Instructions",
                    "1. Carefully evaluate the output against the criteria above",
                    "2. Decide if it passes (true) or fails (false)",
                    "3. Provide detailed reasoning that references specific parts of the output",
                ]
            )

        # Add additional guidelines if provided
        if self.additional_guidelines:
            instructions_parts.append("")
            instructions_parts.append("## Additional Guidelines")
            if isinstance(self.additional_guidelines, str):
                instructions_parts.append(self.additional_guidelines)
            else:
                for guideline in self.additional_guidelines:
                    instructions_parts.append(f"- {guideline}")

        # Add closing instruction
        instructions_parts.append("")
        instructions_parts.append("Be objective and thorough in your evaluation.")

        return Agent(
            model=model,
            description="You are an expert evaluator. Score outputs objectively based on the provided criteria.",
            instructions="\n".join(instructions_parts),
            output_schema=response_schema,
        )

    def _evaluate(self, input: str, output: str, evaluator_agent: Agent) -> Optional[AgentAsJudgeEvaluation]:
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

            response = evaluator_agent.run(prompt, stream=False)
            judge_response = response.content
            if not isinstance(judge_response, (NumericJudgeResponse, BinaryJudgeResponse)):
                raise EvalError(f"Invalid response: {judge_response}")

            # Determine pass/fail based on scoring strategy and response type
            if isinstance(judge_response, NumericJudgeResponse):
                score = judge_response.score
                passed = score >= self.threshold
            else:  # BinaryJudgeResponse
                score = None
                passed = judge_response.passed

            evaluation = AgentAsJudgeEvaluation(
                input=input,
                output=output,
                criteria=self.criteria,
                score=score,
                reason=judge_response.reason,
                passed=passed,
            )

            # Trigger on_fail callback if evaluation failed
            if not passed and self.on_fail:
                try:
                    if iscoroutinefunction(self.on_fail):
                        log_warning(
                            f"Cannot use async on_fail callback with sync evaluation. Use arun() instead. Skipping callback: {self.on_fail.__name__}"
                        )
                    else:
                        self.on_fail(evaluation)
                except Exception as e:
                    logger.warning(f"on_fail callback error: {e}")

            return evaluation
        except Exception as e:
            logger.exception(f"Evaluation failed: {e}")
            return None

    async def _aevaluate(self, input: str, output: str, evaluator_agent: Agent) -> Optional[AgentAsJudgeEvaluation]:
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

            response = await evaluator_agent.arun(prompt, stream=False)  # type: ignore[misc]
            judge_response = response.content
            if not isinstance(judge_response, (NumericJudgeResponse, BinaryJudgeResponse)):
                raise EvalError(f"Invalid response: {judge_response}")

            # Determine pass/fail based on response type
            if isinstance(judge_response, NumericJudgeResponse):
                score = judge_response.score
                passed = score >= self.threshold
            else:  # BinaryJudgeResponse
                score = None
                passed = judge_response.passed

            evaluation = AgentAsJudgeEvaluation(
                input=input,
                output=output,
                criteria=self.criteria,
                score=score,
                reason=judge_response.reason,
                passed=passed,
            )

            # Trigger on_fail callback if evaluation failed
            if not passed and self.on_fail:
                try:
                    if iscoroutinefunction(self.on_fail):
                        await self.on_fail(evaluation)
                    else:
                        self.on_fail(evaluation)
                except Exception as e:
                    logger.warning(f"on_fail callback error: {e}")

            return evaluation
        except Exception as e:
            logger.exception(f"Async evaluation failed: {e}")
            return None

    def _log_eval_to_db(
        self,
        run_id: str,
        result: AgentAsJudgeResult,
        agent_id: Optional[str] = None,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        team_id: Optional[str] = None,
        evaluated_component_name: Optional[str] = None,
    ) -> None:
        """Helper to log evaluation to database."""
        if not self.db:
            return

        log_eval_run(
            db=self.db,  # type: ignore
            run_id=run_id,
            run_data=asdict(result),
            eval_type=EvalType.AGENT_AS_JUDGE,
            agent_id=agent_id,
            model_id=model_id,
            model_provider=model_provider,
            name=self.name,
            team_id=team_id,
            evaluated_component_name=evaluated_component_name,
            eval_input={
                "criteria": self.criteria,
                "scoring_strategy": self.scoring_strategy,
                "threshold": self.threshold if self.scoring_strategy == "numeric" else None,
                "additional_guidelines": self.additional_guidelines,
            },
        )

    async def _async_log_eval_to_db(
        self,
        run_id: str,
        result: AgentAsJudgeResult,
        agent_id: Optional[str] = None,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        team_id: Optional[str] = None,
        evaluated_component_name: Optional[str] = None,
    ) -> None:
        """Helper to log evaluation to database asynchronously."""
        if not self.db:
            return

        await async_log_eval(
            db=self.db,
            run_id=run_id,
            run_data=asdict(result),
            eval_type=EvalType.AGENT_AS_JUDGE,
            agent_id=agent_id,
            model_id=model_id,
            model_provider=model_provider,
            name=self.name,
            team_id=team_id,
            evaluated_component_name=evaluated_component_name,
            eval_input={
                "criteria": self.criteria,
                "scoring_strategy": self.scoring_strategy,
                "threshold": self.threshold if self.scoring_strategy == "numeric" else None,
                "additional_guidelines": self.additional_guidelines,
            },
        )

    def run(
        self,
        *,
        input: Optional[str] = None,
        output: Optional[str] = None,
        cases: Optional[List[Dict[str, str]]] = None,
        print_summary: bool = False,
        print_results: bool = False,
    ) -> Optional[AgentAsJudgeResult]:
        """Evaluate input/output against the criteria.

        Supports both single evaluation and batch evaluation:

        Args:
            input: Input text for single evaluation
            output: Output text for single evaluation
            cases: List of input/output pairs for batch evaluation
            print_summary: Whether to print summary
            print_results: Whether to print detailed results
        """
        # Generate unique run_id for this execution
        run_id = str(uuid4())

        # Validate parameters
        single_mode = input is not None or output is not None
        batch_mode = cases is not None

        if single_mode and batch_mode:
            raise ValueError("Provide either (input, output) OR cases, not both")

        if not single_mode and not batch_mode:
            raise ValueError("Must provide either (input, output) OR cases")

        # Batch mode if cases provided
        if batch_mode and cases is not None:
            return self._run_batch(cases=cases, run_id=run_id, print_summary=print_summary, print_results=print_results)

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
        result = AgentAsJudgeResult(run_id=run_id)

        console = Console()
        with Live(console=console, transient=True) as live_log:
            evaluator = self.get_evaluator_agent()

            status = Status("Running evaluation...", spinner="dots", speed=1.0, refresh_per_second=10)
            live_log.update(status)

            evaluation = self._evaluate(input=input, output=output, evaluator_agent=evaluator)

            if evaluation:
                result.results.append(evaluation)
                result.compute_stats()

            status.stop()

        # Save result to file
        if self.file_path_to_save_results:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                result=result,
                eval_id=run_id,
                name=self.name,
            )

        # Print results
        if self.print_results or print_results:
            result.print_results(console)
        if self.print_summary or print_summary:
            result.print_summary(console)

        # evaluator model info
        model_id = self.model.id if self.model is not None else None
        model_provider = self.model.provider if self.model is not None else None
        # Log to DB
        self._log_eval_to_db(run_id=run_id, result=result, model_id=model_id, model_provider=model_provider)

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, create_eval_run_telemetry

            create_eval_run_telemetry(
                eval_run=EvalRunCreate(
                    run_id=run_id, eval_type=EvalType.AGENT_AS_JUDGE, data=self._get_telemetry_data(result)
                )
            )

        return result

    async def arun(
        self,
        *,
        input: Optional[str] = None,
        output: Optional[str] = None,
        cases: Optional[List[Dict[str, str]]] = None,
        print_summary: bool = False,
        print_results: bool = False,
    ) -> Optional[AgentAsJudgeResult]:
        """Evaluate input/output against the criteria asynchronously.

        Supports both single evaluation and batch evaluation:

        Args:
            input: Input text for single evaluation
            output: Output text for single evaluation
            cases: List of input/output pairs for batch evaluation
            print_summary: Whether to print summary
            print_results: Whether to print detailed results
        """
        # Generate unique run_id for this execution
        run_id = str(uuid4())

        # Validate parameters
        single_mode = input is not None or output is not None
        batch_mode = cases is not None

        if single_mode and batch_mode:
            raise ValueError("Provide either (input, output) OR cases, not both")

        if not single_mode and not batch_mode:
            raise ValueError("Must provide either (input, output) OR cases")

        # Batch mode if cases provided
        if batch_mode and cases is not None:
            return await self._arun_batch(
                cases=cases, run_id=run_id, print_summary=print_summary, print_results=print_results
            )

        # Validate single mode has both input and output
        if input is None or output is None:
            raise ValueError("Both input and output are required for single evaluation")

        # Single evaluation logic
        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        result = AgentAsJudgeResult(run_id=run_id)

        console = Console()
        with Live(console=console, transient=True) as live_log:
            evaluator = self.get_evaluator_agent()

            status = Status("Running evaluation...", spinner="dots", speed=1.0, refresh_per_second=10)
            live_log.update(status)

            evaluation = await self._aevaluate(input=input, output=output, evaluator_agent=evaluator)

            if evaluation:
                result.results.append(evaluation)
                result.compute_stats()

            status.stop()

        # Save result to file
        if self.file_path_to_save_results:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                result=result,
                eval_id=run_id,
                name=self.name,
            )

        # Print results
        if self.print_results or print_results:
            result.print_results(console)
        if self.print_summary or print_summary:
            result.print_summary(console)

        # evaluator model info
        model_id = self.model.id if self.model is not None else None
        model_provider = self.model.provider if self.model is not None else None
        # Log to DB
        await self._async_log_eval_to_db(run_id=run_id, result=result, model_id=model_id, model_provider=model_provider)

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, async_create_eval_run_telemetry

            await async_create_eval_run_telemetry(
                eval_run=EvalRunCreate(
                    run_id=run_id, eval_type=EvalType.AGENT_AS_JUDGE, data=self._get_telemetry_data(result)
                )
            )

        return result

    def _run_batch(
        self,
        cases: List[Dict[str, str]],
        run_id: str,
        *,
        print_summary: bool = True,
        print_results: bool = False,
    ) -> Optional[AgentAsJudgeResult]:
        """Private helper: Evaluate multiple input/output pairs.

        Args:
            cases: List of dicts with 'input' and 'output' keys
            run_id: Unique ID for this evaluation run
        """
        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("Use arun() with async DB.")

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        result = AgentAsJudgeResult(run_id=run_id)

        console = Console()
        with Live(console=console, transient=True) as live_log:
            evaluator = self.get_evaluator_agent()

            for i, case in enumerate(cases):
                status = Status(f"Evaluating {i + 1}/{len(cases)}...", spinner="dots")
                live_log.update(status)

                evaluation = self._evaluate(input=case["input"], output=case["output"], evaluator_agent=evaluator)
                if evaluation:
                    result.results.append(evaluation)
                    result.compute_stats()

            status.stop()

        # Save result to file
        if self.file_path_to_save_results:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                result=result,
                eval_id=run_id,
                name=self.name,
            )

        # Print results
        if self.print_results or print_results:
            result.print_results(console)
        if self.print_summary or print_summary:
            result.print_summary(console)

        # evaluator model info
        model_id = self.model.id if self.model is not None else None
        model_provider = self.model.provider if self.model is not None else None
        # Log to DB
        self._log_eval_to_db(run_id=run_id, result=result, model_id=model_id, model_provider=model_provider)

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, create_eval_run_telemetry

            create_eval_run_telemetry(
                eval_run=EvalRunCreate(
                    run_id=run_id, eval_type=EvalType.AGENT_AS_JUDGE, data=self._get_telemetry_data(result)
                )
            )

        return result

    async def _arun_batch(
        self,
        cases: List[Dict[str, str]],
        run_id: str,
        *,
        print_summary: bool = True,
        print_results: bool = False,
    ) -> Optional[AgentAsJudgeResult]:
        """Private helper: Evaluate multiple input/output pairs asynchronously.

        Args:
            cases: List of dicts with 'input' and 'output' keys
            run_id: Unique ID for this evaluation run
        """
        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        result = AgentAsJudgeResult(run_id=run_id)

        console = Console()
        with Live(console=console, transient=True) as live_log:
            evaluator = self.get_evaluator_agent()

            for i, case in enumerate(cases):
                status = Status(f"Evaluating {i + 1}/{len(cases)}...", spinner="dots")
                live_log.update(status)

                evaluation = await self._aevaluate(
                    input=case["input"], output=case["output"], evaluator_agent=evaluator
                )
                if evaluation:
                    result.results.append(evaluation)
                    result.compute_stats()

                status.stop()

        # Save result to file
        if self.file_path_to_save_results:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                result=result,
                eval_id=run_id,
                name=self.name,
            )

        # Print results
        if self.print_results or print_results:
            result.print_results(console)
        if self.print_summary or print_summary:
            result.print_summary(console)

        # evaluator model info
        model_id = self.model.id if self.model is not None else None
        model_provider = self.model.provider if self.model is not None else None
        # Log to DB
        await self._async_log_eval_to_db(run_id=run_id, result=result, model_id=model_id, model_provider=model_provider)

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, async_create_eval_run_telemetry

            await async_create_eval_run_telemetry(
                eval_run=EvalRunCreate(
                    run_id=run_id, eval_type=EvalType.AGENT_AS_JUDGE, data=self._get_telemetry_data(result)
                )
            )

        return result

    def _get_telemetry_data(self, result: Optional[AgentAsJudgeResult] = None) -> Dict[str, Any]:
        return {
            "criteria_length": len(self.criteria) if self.criteria else 0,
            "scoring_strategy": self.scoring_strategy,
            "threshold": self.threshold if self.scoring_strategy == "numeric" else None,
            "num_results": len(result.results) if result else 0,
        }

    # BaseEval hook methods
    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        raise ValueError("Pre-hooks are not supported")

    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        raise ValueError("Pre-hooks are not supported")

    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Perform sync post-check to evaluate agent output."""
        input_str = run_output.input.input_content_string() if run_output.input else ""
        output_str = str(run_output.content) if run_output.content else ""

        # Temporarily disable DB logging
        original_db = self.db
        self.db = None

        # Run evaluation and capture result
        result = self.run(
            input=input_str, output=output_str, print_results=self.print_results, print_summary=self.print_summary
        )

        # Restore DB and log with context from run_output
        self.db = original_db

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("post_check() requires sync DB. Use async_post_check() with async DB.")

        # Extract metadata from run_output
        if isinstance(run_output, RunOutput):
            agent_id = run_output.agent_id
            team_id = None
        elif isinstance(run_output, TeamRunOutput):
            agent_id = None
            team_id = run_output.team_id

        # evaluator model info
        model_id = self.model.id if self.model is not None else None
        model_provider = self.model.provider if self.model is not None else None
        # Log to DB if we have a valid result
        if result:
            self._log_eval_to_db(
                run_id=result.run_id,
                result=result,
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

        # Run evaluation and capture result
        result = await self.arun(
            input=input_str, output=output_str, print_results=self.print_results, print_summary=self.print_summary
        )

        # Restore DB and log with context from run_output
        self.db = original_db

        # Extract metadata from run_output
        if isinstance(run_output, RunOutput):
            agent_id = run_output.agent_id
            team_id = None
        elif isinstance(run_output, TeamRunOutput):
            agent_id = None
            team_id = run_output.team_id

        # evaluator model info
        model_id = self.model.id if self.model is not None else None
        model_provider = self.model.provider if self.model is not None else None
        # Log to DB if we have a valid result
        if result:
            await self._async_log_eval_to_db(
                run_id=result.run_id,
                result=result,
                agent_id=agent_id,
                model_id=model_id,
                model_provider=model_provider,
                team_id=team_id,
            )
