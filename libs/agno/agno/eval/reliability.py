import json
from dataclasses import asdict, dataclass, field
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union
from uuid import uuid4

from agno.db.base import AsyncBaseDb, BaseDb
from agno.run.team import TeamRunOutput

if TYPE_CHECKING:
    from rich.console import Console

from agno.agent import RunOutput
from agno.db.schemas.evals import EvalType
from agno.eval.utils import async_log_eval, log_eval_run, store_result_in_file
from agno.utils.log import logger


@dataclass
class ReliabilityResult:
    eval_status: str
    failed_tool_calls: List[str]
    passed_tool_calls: List[str]
    additional_tool_calls: List[str] = field(default_factory=list)
    missing_tool_calls: List[str] = field(default_factory=list)
    failed_argument_checks: List[str] = field(default_factory=list)
    passed_argument_checks: List[str] = field(default_factory=list)

    def print_eval(self, console: Optional["Console"] = None):
        from rich.console import Console
        from rich.table import Table

        if console is None:
            console = Console()

        results_table = Table(title="Reliability Summary", show_header=True, header_style="bold magenta")
        results_table.add_row("Evaluation Status", self.eval_status)
        results_table.add_row("Failed Tool Calls", str(self.failed_tool_calls))
        results_table.add_row("Passed Tool Calls", str(self.passed_tool_calls))
        if self.additional_tool_calls:
            results_table.add_row("Additional Tool Calls", str(self.additional_tool_calls))
        if self.missing_tool_calls:
            results_table.add_row("Missing Tool Calls", str(self.missing_tool_calls))
        if self.failed_argument_checks:
            results_table.add_row("Failed Argument Checks", str(self.failed_argument_checks))
        if self.passed_argument_checks:
            results_table.add_row("Passed Argument Checks", str(self.passed_argument_checks))
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
    # When True, tool calls not in expected_tool_calls are allowed (subset matching)
    allow_additional_tool_calls: bool = False
    # Expected arguments for specific tool calls
    # Single check: {"multiply": {"a": 10, "b": 5}}
    # Multiple checks: {"add": [{"a": 2, "b": 2}, {"a": 3, "b": 3}]}
    expected_tool_call_arguments: Optional[Dict[str, Union[Dict[str, Any], List[Dict[str, Any]]]]] = None
    # Result of the evaluation
    result: Optional[ReliabilityResult] = None

    # Print detailed results
    print_results: bool = False
    # If set, results will be saved in the given file path
    file_path_to_save_results: Optional[str] = None
    # Enable debug logs
    debug_mode: bool = getenv("AGNO_DEBUG", "false").lower() == "true"
    # The database to store Evaluation results
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None

    # Telemetry settings
    # telemetry=True logs minimal telemetry for analytics
    # This helps us improve our Evals and provide better support
    telemetry: bool = True

    def _evaluate(self) -> ReliabilityResult:
        """Core evaluation logic for checking tool calls and arguments."""
        messages: list = []
        if self.agent_response is not None:
            messages = self.agent_response.messages or []
        elif self.team_response is not None:
            messages = list(self.team_response.messages or [])
            for member_response in self.team_response.member_responses:
                if member_response.messages is not None:
                    messages += member_response.messages

        # Collect all tool calls across all messages (without mutating originals)
        actual_tool_calls: List[Dict[str, Any]] = []
        for message in messages:  # type: ignore
            if message.tool_calls:
                actual_tool_calls.extend(message.tool_calls)

        failed_tool_calls: List[str] = []
        passed_tool_calls: List[str] = []
        additional_tool_calls: List[str] = []
        missing_tool_calls: List[str] = []
        failed_argument_checks: List[str] = []
        passed_argument_checks: List[str] = []

        if not actual_tool_calls:
            missing_tool_calls = list(self.expected_tool_calls) if self.expected_tool_calls else []
            if self.expected_tool_call_arguments:
                for arg_tool_name in self.expected_tool_call_arguments:
                    if arg_tool_name not in missing_tool_calls:
                        failed_argument_checks.append(arg_tool_name)
        else:
            actual_tool_names: set = set()
            for tool_call in actual_tool_calls:
                func = tool_call.get("function")
                tool_name = func.get("name") if isinstance(func, dict) else None
                if not tool_name:
                    continue
                actual_tool_names.add(tool_name)

                if self.expected_tool_calls is not None and tool_name not in self.expected_tool_calls:
                    if self.allow_additional_tool_calls:
                        additional_tool_calls.append(tool_name)
                    else:
                        failed_tool_calls.append(tool_name)
                else:
                    passed_tool_calls.append(tool_name)

            # Check for missing expected tool calls
            if self.expected_tool_calls:
                for expected_tool in self.expected_tool_calls:
                    if expected_tool not in actual_tool_names:
                        missing_tool_calls.append(expected_tool)

            # Check tool call arguments (partial match)
            if self.expected_tool_call_arguments:
                for arg_tool_name, expected_args_raw in self.expected_tool_call_arguments.items():
                    # Skip argument checks for tools already tracked as missing
                    if arg_tool_name in missing_tool_calls:
                        continue

                    # Normalize: single dict becomes a one-element list
                    arg_specs = expected_args_raw if isinstance(expected_args_raw, list) else [expected_args_raw]

                    matching_calls = [
                        tc
                        for tc in actual_tool_calls
                        if isinstance(tc.get("function"), dict) and tc["function"].get("name") == arg_tool_name
                    ]
                    if not matching_calls:
                        failed_argument_checks.append(arg_tool_name)
                        continue

                    # Parse actual arguments from all matching calls
                    parsed_args_list: List[Dict[str, Any]] = []
                    for tc in matching_calls:
                        func = tc.get("function")
                        actual_args_raw = func.get("arguments", "{}") if isinstance(func, dict) else "{}"
                        try:
                            actual_args = (
                                json.loads(actual_args_raw) if isinstance(actual_args_raw, str) else actual_args_raw
                            )
                        except (json.JSONDecodeError, TypeError):
                            actual_args = {}
                        if not isinstance(actual_args, dict):
                            actual_args = {}
                        parsed_args_list.append(actual_args)

                    # Each spec must match at least one call
                    all_specs_matched = True
                    for spec in arg_specs:
                        if not any(
                            all(key in actual and actual[key] == value for key, value in spec.items())
                            for actual in parsed_args_list
                        ):
                            all_specs_matched = False
                            break

                    if all_specs_matched:
                        passed_argument_checks.append(arg_tool_name)
                    else:
                        failed_argument_checks.append(arg_tool_name)

        eval_passed = len(failed_tool_calls) == 0 and len(missing_tool_calls) == 0 and len(failed_argument_checks) == 0

        return ReliabilityResult(
            eval_status="PASSED" if eval_passed else "FAILED",
            failed_tool_calls=failed_tool_calls,
            passed_tool_calls=passed_tool_calls,
            additional_tool_calls=additional_tool_calls,
            missing_tool_calls=missing_tool_calls,
            failed_argument_checks=failed_argument_checks,
            passed_argument_checks=passed_argument_checks,
        )

    def _get_telemetry_data(self) -> Dict[str, Any]:
        """Get the telemetry data for the evaluation"""
        response = self.agent_response or self.team_response
        return {
            "team_id": self.team_response.team_id if self.team_response else None,
            "agent_id": self.agent_response.agent_id if self.agent_response else None,
            "model_id": response.model if response else None,  # type: ignore
            "model_provider": response.model_provider if response else None,  # type: ignore
        }

    def run(self, *, print_results: bool = False) -> Optional[ReliabilityResult]:
        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("run() is not supported with an async DB. Please use arun() instead.")

        if self.agent_response is None and self.team_response is None:
            raise ValueError("You need to provide 'agent_response' or 'team_response' to run the evaluation.")

        if self.agent_response is not None and self.team_response is not None:
            raise ValueError(
                "You need to provide only one of 'agent_response' or 'team_response' to run the evaluation."
            )

        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        # Generate unique run_id for this execution (don't modify self.eval_id due to concurrency)
        run_id = str(uuid4())

        # Add a spinner while running the evaluations
        console = Console()
        with Live(console=console, transient=True) as live_log:
            status = Status("Running evaluation...", spinner="dots", speed=1.0, refresh_per_second=10)
            live_log.update(status)

            self.result = self._evaluate()

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
                "allow_additional_tool_calls": self.allow_additional_tool_calls,
                "expected_tool_call_arguments": self.expected_tool_call_arguments,
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

        logger.debug(f"*********** Evaluation End: {run_id} ***********")
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

        # Generate unique run_id for this execution (don't modify self.eval_id due to concurrency)
        run_id = str(uuid4())

        # Add a spinner while running the evaluations
        console = Console()
        with Live(console=console, transient=True) as live_log:
            status = Status("Running evaluation...", spinner="dots", speed=1.0, refresh_per_second=10)
            live_log.update(status)

            self.result = self._evaluate()

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
                "allow_additional_tool_calls": self.allow_additional_tool_calls,
                "expected_tool_call_arguments": self.expected_tool_call_arguments,
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

        logger.debug(f"*********** Evaluation End: {run_id} ***********")
        return self.result
