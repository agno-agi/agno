import re
from dataclasses import asdict, dataclass, field
from inspect import iscoroutinefunction
from os import getenv
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Union
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


@dataclass
class PatternResult:
    """Result of a single pattern match check."""

    pattern: str
    match_type: str  # "binary" or "occurrence"
    actual_count: int = 0
    expected_count: Optional[int] = None
    score: float = 0.0


def _check_patterns(
    text: str,
    patterns: Optional[List[str]] = None,
    occurrence_patterns: Optional[Dict[str, int]] = None,
) -> List[PatternResult]:
    """Check patterns against text and return results."""
    results: List[PatternResult] = []

    # Binary patterns (must be present)
    if patterns:
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            count = len(matches)
            results.append(
                PatternResult(
                    pattern=pattern,
                    match_type="binary",
                    actual_count=count,
                    expected_count=1,
                    score=1.0 if count >= 1 else 0.0,
                )
            )

    # Occurrence patterns (expected count)
    if occurrence_patterns:
        for pattern, expected in occurrence_patterns.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            count = len(matches)
            score = min(count / expected, 1.0) if expected > 0 else 1.0
            results.append(
                PatternResult(
                    pattern=pattern,
                    match_type="occurrence",
                    actual_count=count,
                    expected_count=expected,
                    score=score,
                )
            )

    return results


class ContextEvalResponse(BaseModel):
    """Response schema for context/system message evaluation."""

    score: int = Field(..., ge=1, le=10, description="Overall score from 1-10.")
    reason: str = Field(..., description="Overall reasoning for the evaluation.")
    aspect_scores: Dict[str, int] = Field(
        ..., description="Individual scores for each aspect identified in the system message."
    )
    aspect_feedback: Dict[str, str] = Field(..., description="Individual feedback for each aspect.")


@dataclass
class ContextEvaluation:
    """Result of a system message evaluation."""

    input: str
    output: str
    system_message: str
    score: int
    reason: str
    aspect_scores: Dict[str, int]
    aspect_feedback: Dict[str, str]
    passed: bool
    pattern_results: List[PatternResult] = field(default_factory=list)
    pattern_score: Optional[float] = None

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
            title="[ Context Evaluation ]",
            title_style="bold sky_blue1",
            title_justify="center",
        )
        results_table.add_row("Input", self.input[:200] + "..." if len(self.input) > 200 else self.input)
        results_table.add_row("Output", self.output[:200] + "..." if len(self.output) > 200 else self.output)
        results_table.add_row("Score", f"{self.score}/10")
        results_table.add_row("Status", f"[{status_style}]{status_text}[/{status_style}]")
        results_table.add_row("Reason", Markdown(self.reason))

        # Add aspect scores and feedback separately
        if self.aspect_scores:
            score_lines = [f"{aspect}: {score}/10" for aspect, score in self.aspect_scores.items()]
            results_table.add_row("Aspect Scores", "\n".join(score_lines))

        if self.aspect_feedback:
            feedback_lines = [f"{aspect}: {feedback}" for aspect, feedback in self.aspect_feedback.items()]
            results_table.add_row("Aspect Feedback", "\n".join(feedback_lines))

        # Add pattern results if any
        if self.pattern_results:
            results_table.add_row("Pattern Score", f"{self.pattern_score:.2f}" if self.pattern_score else "N/A")
            pattern_lines = []
            for pr in self.pattern_results:
                if pr.match_type == "binary":
                    pattern_lines.append(f"{pr.pattern}: {pr.actual_count}")
                else:
                    pattern_lines.append(f"{pr.pattern}: {pr.actual_count}/{pr.expected_count}")
            results_table.add_row("Patterns", "\n".join(pattern_lines))

        console.print(results_table)


@dataclass
class ContextResult:
    """Aggregated results from context evaluations."""

    run_id: str
    results: List[ContextEvaluation] = field(default_factory=list)
    avg_score: Optional[float] = field(init=False)
    min_score: Optional[float] = field(init=False)
    max_score: Optional[float] = field(init=False)
    std_dev_score: Optional[float] = field(init=False)
    pass_rate: float = field(init=False)
    avg_pattern_score: Optional[float] = field(init=False)

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

            # Compute pattern score average
            pattern_scores = [r.pattern_score for r in self.results if r.pattern_score is not None]
            self.avg_pattern_score = statistics.mean(pattern_scores) if pattern_scores else None
        else:
            self.avg_score = None
            self.min_score = None
            self.max_score = None
            self.std_dev_score = None
            self.pass_rate = 0.0
            self.avg_pattern_score = None

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
            title="[ Context Evaluation Summary ]",
            title_style="bold sky_blue1",
            title_justify="center",
            padding=(0, 2),
            min_width=45,
        )

        num_results = len(self.results)
        summary_table.add_row("Number of Evaluations", f"{num_results}")
        summary_table.add_row("Pass Rate", f"{self.pass_rate:.1f}%")

        if self.avg_score is not None:
            if num_results == 1:
                summary_table.add_row("Score", f"{self.avg_score:.2f}/10")
            elif num_results > 1:
                summary_table.add_row("Average Score", f"{self.avg_score:.2f}/10")
                summary_table.add_row("Min Score", f"{self.min_score:.2f}/10")
                summary_table.add_row("Max Score", f"{self.max_score:.2f}/10")
                if self.std_dev_score and self.std_dev_score > 0:
                    summary_table.add_row("Std Deviation", f"{self.std_dev_score:.2f}")

        if self.avg_pattern_score is not None:
            summary_table.add_row("Pattern Score", f"{self.avg_pattern_score:.2f}")

        console.print(summary_table)

    def print_results(self, console: Optional["Console"] = None):
        for result in self.results:
            result.print_eval(console)


@dataclass
class ContextEval(BaseEval):
    """Evaluate how well an agent follows its system message/instructions.

    Evaluates multiple aspects: role adherence, instruction following, tone, scope, etc.
    Supports pattern matching for binary checks and occurrence counting.
    """

    # The system message to evaluate against (extracted from agent if not provided)
    system_message: str = ""

    # Pattern matching configuration
    patterns: Optional[List[str]] = None  # Binary patterns (must be present)
    occurrence_patterns: Optional[Dict[str, int]] = None  # Patterns with expected counts
    pattern_target: str = "output"  # "output", "system_message", or "all"

    # Evaluation configuration
    threshold: int = 7
    on_fail: Optional[Callable[["ContextEvaluation"], None]] = None
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
        if not 1 <= self.threshold <= 10:
            raise ValueError(f"threshold must be between 1 and 10, got {self.threshold}")

    def get_evaluator_agent(self) -> Agent:
        """Return the evaluator agent for context evaluation."""
        if self.evaluator_agent is not None:
            self.evaluator_agent.output_schema = ContextEvalResponse
            return self.evaluator_agent

        model = self.model
        if model is None:
            try:
                from agno.models.openai import OpenAIChat

                model = OpenAIChat(id="gpt-4o-mini")
            except (ModuleNotFoundError, ImportError) as e:
                logger.exception(e)
                raise EvalError("Agno uses `openai` as the default model provider. Please run `pip install openai`.")

        instructions_parts = [
            "## Your Task",
            "Evaluate how well the agent's response follows its system message/context.",
            "",
            "## How to Identify Aspects",
            "Analyze the system message and evaluate ONLY the parts that are present.",
            "Look for these sections in the system message:",
            "",
            "- **description**: Text at the beginning describing the agent's persona (evaluate if present)",
            "- **role**: Content inside `<your_role>` tags (evaluate if present)",
            "- **instructions**: Content inside `<instructions>` tags (evaluate if present)",
            "- **expected_output**: Content inside `<expected_output>` tags (evaluate if present)",
            "- **memories**: Content inside `<memories_from_previous_interactions>` tags - was this info used? (evaluate if present)",
            "- **session_summary**: Content inside `<summary_of_previous_interactions>` tags - was context maintained? (evaluate if present)",
            "- **knowledge**: If `<knowledge>` section is present in the prompt, evaluate: Did the agent correctly use the provided knowledge/references in its response?",
            "- **tools**: If `<tools>` section is present in the prompt, evaluate: Did the agent use appropriate tools? Did the response incorporate the tool results correctly?",
            "",
            "## Important",
            "- Only create aspects for sections that EXIST in the system message",
            "- If `<memories_from_previous_interactions>` is NOT in the system message, do NOT include 'memories' aspect",
            "- If `<your_role>` is NOT in the system message, do NOT include 'role' aspect",
            "",
            "## Scoring (1-10)",
            "- 1-2: Completely ignores this aspect",
            "- 3-4: Major deviations",
            "- 5-6: Partial adherence with issues",
            "- 7-8: Mostly follows with minor issues",
            "- 9-10: Fully adheres to this aspect",
            "",
            "## Feedback Format",
            "For each aspect you evaluate, provide a brief reason explaining the score.",
        ]

        if self.additional_guidelines:
            instructions_parts.append("")
            instructions_parts.append("## Additional Guidelines")
            if isinstance(self.additional_guidelines, str):
                instructions_parts.append(self.additional_guidelines)
            else:
                for guideline in self.additional_guidelines:
                    instructions_parts.append(f"- {guideline}")

        instructions_parts.append("")
        instructions_parts.append("Be objective and thorough in your evaluation.")

        return Agent(
            model=model,
            description="You are an expert evaluator assessing how well an agent follows its system message.",
            instructions="\n".join(instructions_parts),
            output_schema=ContextEvalResponse,
        )

    def _evaluate(
        self,
        input: str,
        output: str,
        system_message: str,
        evaluator_agent: Optional[Agent] = None,
        knowledge_context: Optional[str] = None,
        tool_context: Optional[str] = None,
    ) -> Optional[ContextEvaluation]:
        """Evaluate a single input/output pair against the system message."""
        try:
            # Check patterns based on pattern_target
            pattern_results: List[PatternResult] = []
            pattern_score: Optional[float] = None
            if self.patterns or self.occurrence_patterns:
                if self.pattern_target == "output":
                    target_text = output
                elif self.pattern_target == "system_message":
                    target_text = system_message
                else:  # "all"
                    target_text = f"{system_message}\n{output}"
                pattern_results = _check_patterns(target_text, self.patterns, self.occurrence_patterns)
                if pattern_results:
                    pattern_score = sum(pr.score for pr in pattern_results) / len(pattern_results)

            # LLM evaluation (optional)
            if evaluator_agent is not None:
                knowledge_section = f"<knowledge>\n{knowledge_context}\n</knowledge>\n\n" if knowledge_context else ""
                tool_section = f"<tools>\n{tool_context}\n</tools>\n\n" if tool_context else ""
                prompt = f"""<system_message>
{system_message}
</system_message>

<user_input>
{input}
</user_input>

{knowledge_section}{tool_section}<agent_response>
{output}
</agent_response>"""

                response = evaluator_agent.run(prompt, stream=False)
                eval_response = response.content

                if not isinstance(eval_response, ContextEvalResponse):
                    raise EvalError(f"Invalid response: {eval_response}")

                score = eval_response.score
                reason = eval_response.reason
                aspect_scores = eval_response.aspect_scores
                aspect_feedback = eval_response.aspect_feedback
                passed = score >= self.threshold
            else:
                # Pattern-only mode: use pattern_score as the score
                score = int(pattern_score * 10) if pattern_score is not None else 0
                reason = "Pattern-only evaluation"
                aspect_scores = {}
                aspect_feedback = {}
                passed = pattern_score >= (self.threshold / 10) if pattern_score is not None else False

            evaluation = ContextEvaluation(
                input=input,
                output=output,
                system_message=system_message[:500] + "..." if len(system_message) > 500 else system_message,
                score=score,
                reason=reason,
                aspect_scores=aspect_scores,
                aspect_feedback=aspect_feedback,
                passed=passed,
                pattern_results=pattern_results,
                pattern_score=pattern_score,
            )

            # Trigger on_fail callback if evaluation failed
            if not passed and self.on_fail:
                try:
                    if iscoroutinefunction(self.on_fail):
                        log_warning(
                            f"Cannot use async on_fail with sync evaluation. Use arun(). Skipping: {self.on_fail.__name__}"
                        )
                    else:
                        self.on_fail(evaluation)
                except Exception as e:
                    logger.warning(f"on_fail callback error: {e}")

            return evaluation
        except Exception as e:
            logger.exception(f"Context evaluation failed: {e}")
            return None

    async def _aevaluate(
        self,
        input: str,
        output: str,
        system_message: str,
        evaluator_agent: Optional[Agent] = None,
        knowledge_context: Optional[str] = None,
        tool_context: Optional[str] = None,
    ) -> Optional[ContextEvaluation]:
        """Evaluate a single input/output pair asynchronously."""
        try:
            # Check patterns based on pattern_target
            pattern_results: List[PatternResult] = []
            pattern_score: Optional[float] = None
            if self.patterns or self.occurrence_patterns:
                if self.pattern_target == "output":
                    target_text = output
                elif self.pattern_target == "system_message":
                    target_text = system_message
                else:  # "all"
                    target_text = f"{system_message}\n{output}"
                pattern_results = _check_patterns(target_text, self.patterns, self.occurrence_patterns)
                if pattern_results:
                    pattern_score = sum(pr.score for pr in pattern_results) / len(pattern_results)

            # LLM evaluation (optional)
            if evaluator_agent is not None:
                knowledge_section = f"<knowledge>\n{knowledge_context}\n</knowledge>\n\n" if knowledge_context else ""
                tool_section = f"<tools>\n{tool_context}\n</tools>\n\n" if tool_context else ""
                prompt = f"""<system_message>
{system_message}
</system_message>

<user_input>
{input}
</user_input>

{knowledge_section}{tool_section}<agent_response>
{output}
</agent_response>"""

                response = await evaluator_agent.arun(prompt, stream=False)
                eval_response = response.content

                if not isinstance(eval_response, ContextEvalResponse):
                    raise EvalError(f"Invalid response: {eval_response}")

                score = eval_response.score
                reason = eval_response.reason
                aspect_scores = eval_response.aspect_scores
                aspect_feedback = eval_response.aspect_feedback
                passed = score >= self.threshold
            else:
                # Pattern-only mode: use pattern_score as the score
                score = int(pattern_score * 10) if pattern_score is not None else 0
                reason = "Pattern-only evaluation"
                aspect_scores = {}
                aspect_feedback = {}
                passed = pattern_score >= (self.threshold / 10) if pattern_score is not None else False

            evaluation = ContextEvaluation(
                input=input,
                output=output,
                system_message=system_message[:500] + "..." if len(system_message) > 500 else system_message,
                score=score,
                reason=reason,
                aspect_scores=aspect_scores,
                aspect_feedback=aspect_feedback,
                passed=passed,
                pattern_results=pattern_results,
                pattern_score=pattern_score,
            )

            # Trigger on_fail callback
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
            logger.exception(f"Async context evaluation failed: {e}")
            return None

    def run(
        self,
        *,
        input: Optional[str] = None,
        output: Optional[str] = None,
        system_message: Optional[str] = None,
        knowledge_context: Optional[str] = None,
        tool_context: Optional[str] = None,
        run_output: Optional[Union[RunOutput, TeamRunOutput]] = None,
        print_summary: bool = False,
        print_results: bool = False,
    ) -> Optional[ContextResult]:
        """Evaluate how well output follows the system message.

        Args:
            input: The user input (or extracted from run_output)
            output: The agent's response (or extracted from run_output)
            system_message: System message to evaluate against (or extracted from run_output)
            knowledge_context: Knowledge/references from knowledge base
            tool_context: Tool calls and results for evaluation
            run_output: RunOutput from agent.run() - extracts input, output, and system_message automatically
        """
        run_id = str(uuid4())

        # If run_output provided, extract values from it
        if run_output is not None:
            input = run_output.input.input_content_string() if run_output.input else ""
            output = str(run_output.content) if run_output.content else ""
            # Extract system message from messages
            if run_output.messages:
                for msg in run_output.messages:
                    if msg.role == "system" and isinstance(msg.content, str):
                        system_message = msg.content
                        break

        if not input or not output:
            raise ValueError("input and output are required (or provide run_output)")

        sys_msg = system_message or self.system_message
        if not sys_msg and not (self.patterns or self.occurrence_patterns):
            raise ValueError("system_message is required (or provide run_output with system message)")

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("Use arun() with async DB.")

        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        result = ContextResult(run_id=run_id)

        # Only create evaluator agent if model or evaluator_agent is provided
        evaluator: Optional[Agent] = None
        if self.model is not None or self.evaluator_agent is not None:
            evaluator = self.get_evaluator_agent()

        console = Console()
        with Live(console=console, transient=True) as live_log:
            status = Status("Running context evaluation...", spinner="dots")
            live_log.update(status)

            evaluation = self._evaluate(
                input=input,
                output=output,
                system_message=sys_msg or "",
                evaluator_agent=evaluator,
                knowledge_context=knowledge_context,
                tool_context=tool_context,
            )
            if evaluation:
                result.results.append(evaluation)
                result.compute_stats()

            status.stop()

        # Save to file
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

        # Log to DB
        self._log_eval_to_db(run_id=run_id, result=result)

        # Telemetry
        if self.telemetry:
            self._send_telemetry(run_id=run_id, result=result)

        return result

    async def arun(
        self,
        *,
        input: Optional[str] = None,
        output: Optional[str] = None,
        system_message: Optional[str] = None,
        knowledge_context: Optional[str] = None,
        tool_context: Optional[str] = None,
        run_output: Optional[Union[RunOutput, TeamRunOutput]] = None,
        print_summary: bool = False,
        print_results: bool = False,
    ) -> Optional[ContextResult]:
        """Evaluate how well output follows the system message asynchronously."""
        run_id = str(uuid4())

        # If run_output provided, extract values from it
        if run_output is not None:
            input = run_output.input.input_content_string() if run_output.input else ""
            output = str(run_output.content) if run_output.content else ""
            # Extract system message from messages
            if run_output.messages:
                for msg in run_output.messages:
                    if msg.role == "system" and isinstance(msg.content, str):
                        system_message = msg.content
                        break

        if not input or not output:
            raise ValueError("input and output are required (or provide run_output)")

        sys_msg = system_message or self.system_message
        if not sys_msg and not (self.patterns or self.occurrence_patterns):
            raise ValueError("system_message is required (or provide run_output with system message)")

        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        set_log_level_to_debug() if self.debug_mode else set_log_level_to_info()
        result = ContextResult(run_id=run_id)

        # Only create evaluator agent if model or evaluator_agent is provided
        evaluator: Optional[Agent] = None
        if self.model is not None or self.evaluator_agent is not None:
            evaluator = self.get_evaluator_agent()

        console = Console()
        with Live(console=console, transient=True) as live_log:
            status = Status("Running context evaluation...", spinner="dots")
            live_log.update(status)

            evaluation = await self._aevaluate(
                input=input,
                output=output,
                system_message=sys_msg or "",
                evaluator_agent=evaluator,
                knowledge_context=knowledge_context,
                tool_context=tool_context,
            )
            if evaluation:
                result.results.append(evaluation)
                result.compute_stats()

            status.stop()

        # Save to file
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

        # Log to DB
        await self._alog_eval_to_db(run_id=run_id, result=result)

        # Telemetry
        if self.telemetry:
            self._send_telemetry(run_id=run_id, result=result)

        return result

    def _log_eval_to_db(
        self,
        run_id: str,
        result: ContextResult,
        agent_id: Optional[str] = None,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Log evaluation to database."""
        if not self.db:
            return

        log_eval_run(
            db=self.db,  # type: ignore
            run_id=run_id,
            run_data=asdict(result),
            eval_type=EvalType.CONTEXT,
            agent_id=agent_id,
            model_id=model_id,
            model_provider=model_provider,
            name=self.name,
            team_id=team_id,
            eval_input={
                "threshold": self.threshold,
                "additional_guidelines": self.additional_guidelines,
            },
        )

    async def _alog_eval_to_db(
        self,
        run_id: str,
        result: ContextResult,
        agent_id: Optional[str] = None,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Log evaluation to database asynchronously."""
        if not self.db:
            return

        await async_log_eval(
            db=self.db,
            run_id=run_id,
            run_data=asdict(result),
            eval_type=EvalType.CONTEXT,
            agent_id=agent_id,
            model_id=model_id,
            model_provider=model_provider,
            name=self.name,
            team_id=team_id,
            eval_input={
                "threshold": self.threshold,
                "additional_guidelines": self.additional_guidelines,
            },
        )

    def _send_telemetry(self, run_id: str, result: ContextResult) -> None:
        """Send telemetry data."""
        from agno.api.evals import EvalRunCreate, create_eval_run_telemetry

        telemetry_data = {
            "num_evaluations": len(result.results),
            "pass_rate": result.pass_rate,
        }
        if result.avg_pattern_score is not None:
            telemetry_data["avg_pattern_score"] = result.avg_pattern_score

        create_eval_run_telemetry(
            eval_run=EvalRunCreate(
                run_id=run_id,
                eval_type=EvalType.CONTEXT,
                data=telemetry_data,
            )
        )

    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Pre-hooks are not supported for ContextEval."""
        raise ValueError("Pre-hooks are not supported for ContextEval")

    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Pre-hooks are not supported for ContextEval."""
        raise ValueError("Pre-hooks are not supported for ContextEval")

    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Evaluate agent output against its system message."""
        sys_msg = self.system_message
        output_str = str(run_output.content) if run_output.content else ""
        knowledge_refs: Optional[str] = None
        tool_parts: List[str] = []

        # Raw input for display (like AgentAsJudge)
        input_str = run_output.input.input_content_string() if run_output.input else ""

        # Extract system, knowledge (from user), and tools (from assistant/tool)
        if run_output.messages:
            for msg in run_output.messages:
                if msg.role == "system" and not sys_msg and isinstance(msg.content, str):
                    sys_msg = msg.content
                elif msg.role == "user" and isinstance(msg.content, str) and "<references>" in msg.content:
                    match = re.search(r"<references>(.*?)</references>", msg.content, re.DOTALL)
                    if match:
                        knowledge_refs = match.group(1).strip()[:1000]
                elif msg.role == "assistant" and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_parts.append(
                            f"Called: {tc.get('function', {}).get('name', 'unknown')}({tc.get('function', {}).get('arguments', '')})"
                        )
                elif msg.role == "tool" and isinstance(msg.content, str):
                    content = msg.content[:500] if len(msg.content) > 500 else msg.content
                    tool_parts.append(f"Result: {content}")

        tool_context = "\n".join(tool_parts) if tool_parts else None

        if not sys_msg:
            logger.warning("No system_message found in run_output.messages, skipping ContextEval")
            return

        # Temporarily disable DB logging (we'll log with context after)
        original_db = self.db
        self.db = None

        result = self.run(
            input=input_str,
            output=output_str,
            system_message=sys_msg,
            knowledge_context=knowledge_refs,
            tool_context=tool_context,
            print_results=self.print_results,
            print_summary=self.print_summary,
        )

        # Restore DB and log with context
        self.db = original_db

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("post_check() requires sync DB. Use async_post_check().")

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
        """Evaluate agent output against its system message asynchronously."""
        sys_msg = self.system_message
        output_str = str(run_output.content) if run_output.content else ""
        knowledge_refs: Optional[str] = None
        tool_parts: List[str] = []

        # Raw input for display (like AgentAsJudge)
        input_str = run_output.input.input_content_string() if run_output.input else ""

        # Extract system, knowledge (from user), and tools (from assistant/tool)
        if run_output.messages:
            for msg in run_output.messages:
                if msg.role == "system" and not sys_msg and isinstance(msg.content, str):
                    sys_msg = msg.content
                elif msg.role == "user" and isinstance(msg.content, str) and "<references>" in msg.content:
                    match = re.search(r"<references>(.*?)</references>", msg.content, re.DOTALL)
                    if match:
                        knowledge_refs = match.group(1).strip()[:1000]
                elif msg.role == "assistant" and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_parts.append(
                            f"Called: {tc.get('function', {}).get('name', 'unknown')}({tc.get('function', {}).get('arguments', '')})"
                        )
                elif msg.role == "tool" and isinstance(msg.content, str):
                    content = msg.content[:500] if len(msg.content) > 500 else msg.content
                    tool_parts.append(f"Result: {content}")

        tool_context = "\n".join(tool_parts) if tool_parts else None

        if not sys_msg:
            logger.warning("No system_message found in run_output.messages, skipping ContextEval")
            return

        # Temporarily disable DB logging
        original_db = self.db
        self.db = None

        result = await self.arun(
            input=input_str,
            output=output_str,
            system_message=sys_msg,
            knowledge_context=knowledge_refs,
            tool_context=tool_context,
            print_results=self.print_results,
            print_summary=self.print_summary,
        )

        # Restore DB and log with context
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

        if result:
            await self._alog_eval_to_db(
                run_id=result.run_id,
                result=result,
                agent_id=agent_id,
                model_id=model_id,
                model_provider=model_provider,
                team_id=team_id,
            )
