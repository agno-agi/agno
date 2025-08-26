from dataclasses import asdict, dataclass, field
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

from agno.db.base import BaseDb

if TYPE_CHECKING:
    from rich.console import Console

from agno.agent import RunOutput
from agno.db.schemas.evals import EvalType
from agno.eval.utils import async_log_eval, log_eval_run, store_result_in_file
from agno.run.team import TeamRunOutput
from agno.utils.log import logger


@dataclass
class ReliabilityResult:
    eval_status: str
    failed_tool_calls: List[str]
    passed_tool_calls: List[str]

    def print_eval(self, console: Optional["Console"] = None):
        from rich.console import Console
        from rich.table import Table

        if console is None:
            console = Console()

        results_table = Table(title="Reliability Summary", show_header=True, header_style="bold magenta")
        results_table.add_row("Evaluation Status", self.eval_status)
        results_table.add_row("Failed Tool Calls", str(self.failed_tool_calls))
        results_table.add_row("Passed Tool Calls", str(self.passed_tool_calls))
        console.print(results_table)

    def assert_passed(self):
        assert self.eval_status == "PASSED"


@dataclass
class ReliabilityEval:
    """Evaluate the reliability of a model by checking the tool calls"""

    # Evaluation name
    name: Optional[str] = None
    # Evaluation UUID
    eval_id: str = field(default_factory=lambda: str(uuid4()))

    # Agent response
    agent_response: Optional[RunOutput] = None
    # Team response
    team_response: Optional[TeamRunOutput] = None
    # Expected tool calls
    expected_tool_calls: Optional[List[str]] = None
    # Result of the evaluation
    result: Optional[ReliabilityResult] = None

    # Print detailed results
    print_results: bool = False
    # If set, results will be saved in the given file path
    file_path_to_save_results: Optional[str] = None
    # Enable debug logs
    debug_mode: bool = getenv("AGNO_DEBUG", "false").lower() == "true"
    # The database to store Evaluation results
    db: Optional[BaseDb] = None

    # Telemetry settings
    # telemetry=True logs minimal telemetry for analytics
    # This helps us improve our Evals and provide better support
    telemetry: bool = True

    def run(self, *, print_results: bool = False) -> Optional[ReliabilityResult]:
        if self.agent_response is None and self.team_response is None:
            raise ValueError("You need to provide 'agent_response' or 'team_response' to run the evaluation.")

        if self.agent_response is not None and self.team_response is not None:
            raise ValueError(
                "You need to provide only one of 'agent_response' or 'team_response' to run the evaluation."
            )

        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        # Add a spinner while running the evaluations
        console = Console()
        with Live(console=console, transient=True) as live_log:
            status = Status("Running evaluation...", spinner="dots", speed=1.0, refresh_per_second=10)
            live_log.update(status)

            actual_tool_calls = None
            if self.agent_response is not None:
                messages = self.agent_response.messages
            elif self.team_response is not None:
                messages = self.team_response.messages or []
                for member_response in self.team_response.member_responses:
                    if member_response.messages is not None:
                        messages += member_response.messages

            for message in reversed(messages):  # type: ignore
                if message.tool_calls:
                    if actual_tool_calls is None:
                        actual_tool_calls = message.tool_calls
                    else:
                        actual_tool_calls.append(message.tool_calls[0])  # type: ignore

            failed_tool_calls = []
            passed_tool_calls = []
            if not actual_tool_calls:
                failed_tool_calls = self.expected_tool_calls or []
            else:
                for tool_call in actual_tool_calls:  # type: ignore
                    tool_name = tool_call.get("function", {}).get("name")
                    if not tool_name:
                        continue
                    else:
                        if tool_name not in self.expected_tool_calls:  # type: ignore
                            failed_tool_calls.append(tool_call.get("function", {}).get("name"))
                        else:
                            passed_tool_calls.append(tool_call.get("function", {}).get("name"))

            self.result = ReliabilityResult(
                eval_status="PASSED" if len(failed_tool_calls) == 0 else "FAILED",
                failed_tool_calls=failed_tool_calls,
                passed_tool_calls=passed_tool_calls,
            )

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
            self.result.print_eval(console)

        # Log results to the Agno platform if requested
        if self.db:
            if self.agent_response is not None:
                agent_id = self.agent_response.agent_id
                team_id = None
                model_id = self.agent_response.model
                model_provider = self.agent_response.model_provider
            elif self.team_response is not None:
                agent_id = None
                team_id = self.team_response.team_id
                model_id = self.team_response.model
                model_provider = self.team_response.model_provider

            eval_input = {
                "expected_tool_calls": self.expected_tool_calls,
            }

            log_eval_run(
                db=self.db,
                run_id=self.eval_id,  # type: ignore
                run_data=asdict(self.result),
                eval_type=EvalType.RELIABILITY,
                name=self.name if self.name is not None else None,
                agent_id=agent_id,
                team_id=team_id,
                model_id=model_id,
                model_provider=model_provider,
                eval_input=eval_input,
            )

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, create_eval_run_telemetry

            create_eval_run_telemetry(
                eval_run=EvalRunCreate(
                    run_id=self.eval_id,
                    eval_type=EvalType.RELIABILITY,
                    data=self._get_telemetry_data(),
                ),
            )

        logger.debug(f"*********** Evaluation End: {self.eval_id} ***********")
        return self.result

    async def arun(self, *, print_results: bool = False) -> Optional[ReliabilityResult]:
        if self.agent_response is None and self.team_response is None:
            raise ValueError("You need to provide 'agent_response' or 'team_response' to run the evaluation.")

        if self.agent_response is not None and self.team_response is not None:
            raise ValueError(
                "You need to provide only one of 'agent_response' or 'team_response' to run the evaluation."
            )

        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        # Add a spinner while running the evaluations
        console = Console()
        with Live(console=console, transient=True) as live_log:
            status = Status("Running evaluation...", spinner="dots", speed=1.0, refresh_per_second=10)
            live_log.update(status)

            actual_tool_calls = None
            if self.agent_response is not None:
                messages = self.agent_response.messages
            elif self.team_response is not None:
                messages = self.team_response.messages or []
                for member_response in self.team_response.member_responses:
                    if member_response.messages is not None:
                        messages += member_response.messages

            for message in reversed(messages):  # type: ignore
                if message.tool_calls:
                    if actual_tool_calls is None:
                        actual_tool_calls = message.tool_calls
                    else:
                        actual_tool_calls.append(message.tool_calls[0])  # type: ignore

            failed_tool_calls = []
            passed_tool_calls = []
            for tool_call in actual_tool_calls:  # type: ignore
                tool_name = tool_call.get("function", {}).get("name")
                if not tool_name:
                    continue
                else:
                    if tool_name not in self.expected_tool_calls:  # type: ignore
                        failed_tool_calls.append(tool_call.get("function", {}).get("name"))
                    else:
                        passed_tool_calls.append(tool_call.get("function", {}).get("name"))

            self.result = ReliabilityResult(
                eval_status="PASSED" if len(failed_tool_calls) == 0 else "FAILED",
                failed_tool_calls=failed_tool_calls,
                passed_tool_calls=passed_tool_calls,
            )

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
            self.result.print_eval(console)

        # Log results to the Agno platform if requested
        if self.db:
            if self.agent_response is not None:
                agent_id = self.agent_response.agent_id
                team_id = None
                model_id = self.agent_response.model
                model_provider = self.agent_response.model_provider
            elif self.team_response is not None:
                agent_id = None
                team_id = self.team_response.team_id
                model_id = self.team_response.model
                model_provider = self.team_response.model_provider

            eval_input = {
                "expected_tool_calls": self.expected_tool_calls,
            }

            await async_log_eval(
                db=self.db,
                run_id=self.eval_id,  # type: ignore
                run_data=asdict(self.result),
                eval_type=EvalType.RELIABILITY,
                name=self.name if self.name is not None else None,
                agent_id=agent_id,
                team_id=team_id,
                model_id=model_id,
                model_provider=model_provider,
                eval_input=eval_input,
            )

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, async_create_eval_run_telemetry

            await async_create_eval_run_telemetry(
                eval_run=EvalRunCreate(
                    run_id=self.eval_id,
                    eval_type=EvalType.RELIABILITY,
                    data=self._get_telemetry_data(),
                ),
            )

        logger.debug(f"*********** Evaluation End: {self.eval_id} ***********")
        return self.result

    def _get_telemetry_data(self) -> Dict[str, Any]:
        """Get the telemetry data for the evaluation"""
        return {
            "team_id": self.team_response.team_id if self.team_response else None,
            "agent_id": self.agent_response.agent_id if self.agent_response else None,
            "model_id": self.agent_response.model if self.agent_response else None,
            "model_provider": self.agent_response.model_provider if self.agent_response else None,
        }
