from dataclasses import asdict, dataclass, field
from os import getenv
from typing import TYPE_CHECKING, List, Optional, Union
from uuid import uuid4

if TYPE_CHECKING:
    from rich.console import Console

from typing import Any

from agno.agent import RunResponse
from agno.api.schemas.evals import EvalType
from agno.eval.utils import async_log_eval_run, log_eval_run, store_result_in_file
from agno.run.team import TeamRunResponse
from agno.utils.log import logger


@dataclass
class ExpectedToolCall:
    tool_name: str
    tool_call_args: dict[str, Any]


@dataclass
class ToolCallEvaluation:
    tool_name: str
    is_passed: bool
    expected_args: Optional[dict[str, Any]] = None
    used_args: Optional[dict[str, Any]] = None
    failure_reason: Optional[str] = None

    def __str__(self):
        if self.is_passed:
            return f"{self.tool_name}"
        elif self.used_args is not None and self.expected_args is not None and self.used_args != self.expected_args:
            return f"{self.tool_name} failed with: {self.failure_reason}. Actual args: {self.used_args}. Expected args: {self.expected_args}"
        else:
            return f"{self.tool_name} failed with: {self.failure_reason}"


@dataclass
class ReliabilityResult:
    eval_status: str
    tool_call_evaluations: List[ToolCallEvaluation]

    def print_eval(self, console: Optional["Console"] = None):
        from rich.console import Console
        from rich.table import Table

        if console is None:
            console = Console()

        results_table = Table(title="Reliability Summary", show_header=True, header_style="bold magenta")
        results_table.add_row("Evaluation Status", self.eval_status)
        results_table.add_row(
            "Passed Tool Calls",
            str([str(evaluation) for evaluation in self.tool_call_evaluations if evaluation.is_passed]),
        )
        results_table.add_row(
            "Failed Tool Calls",
            str([str(evaluation) for evaluation in self.tool_call_evaluations if not evaluation.is_passed]),
        )
        console.print(results_table)

    def assert_passed(self):
        assert self.eval_status == "PASSED"


@dataclass
class ReliabilityEval:
    """Evaluate the reliability of an Agent or Team, by checking it has called the expected tools"""

    # Expected tool calls
    expected_tool_calls: Union[List[str], List[ExpectedToolCall]]
    # If True, we check if the provided arguments are equalt to the used arguments.
    # If False, we just check if the provided arguments were used.
    strict_args_check: bool = False

    # Evaluation name
    name: Optional[str] = None
    # Evaluation UUID
    eval_id: str = field(default_factory=lambda: str(uuid4()))
    # Agent response
    agent_response: Optional[RunResponse] = None
    # Team response
    team_response: Optional[TeamRunResponse] = None
    # Result of the evaluation
    result: Optional[ReliabilityResult] = None

    # Print detailed results
    print_results: bool = False
    # If set, results will be saved in the given file path
    file_path_to_save_results: Optional[str] = None
    # Enable debug logs
    debug_mode: bool = getenv("AGNO_DEBUG", "false").lower() == "true"
    # Log the results to the Agno platform. On by default.
    monitoring: bool = getenv("AGNO_MONITOR", "true").lower() == "true"

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

            actual_tool_calls: list[dict[str, Any]] = []
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

            tool_call_evaluations: list[ToolCallEvaluation] = []

            # If expected_tool_calls is a list of function names, we check if the functions were called
            if isinstance(self.expected_tool_calls[0], str):
                called_expected_tools = set()
                for tool_call in actual_tool_calls:
                    function_name = tool_call.get("function", {}).get("name")
                    if not function_name:
                        continue

                    if function_name in self.expected_tool_calls:
                        called_expected_tools.add(function_name)
                        tool_call_evaluations.append(ToolCallEvaluation(tool_name=function_name, is_passed=True))
                    else:
                        tool_call_evaluations.append(
                            ToolCallEvaluation(
                                tool_name=function_name,
                                is_passed=False,
                                failure_reason="Unexpected tool call",
                            )
                        )
                # Handle expected tool calls that were not made
                for tool_name in self.expected_tool_calls:
                    if tool_name not in called_expected_tools:  # type: ignore
                        tool_call_evaluations.append(
                            ToolCallEvaluation(
                                tool_name=tool_name,  # type: ignore
                                is_passed=False,
                                failure_reason="Expected call was not made",
                            )
                        )

            # If expected_tool_calls is a list of ToolCall, we check if the functions were called with the expected arguments
            elif isinstance(self.expected_tool_calls[0], ExpectedToolCall):
                called_expected_tools = set()
                for tool_call in actual_tool_calls:
                    function_name = tool_call.get("function", {}).get("name")
                    if not function_name:
                        continue

                    # 1. Check the function was called
                    expected_tool_call = None
                    for expected in self.expected_tool_calls:
                        if expected.tool_name == function_name:  # type: ignore
                            called_expected_tools.add(function_name)
                            expected_tool_call = expected
                            break
                    if not expected_tool_call:
                        tool_call_evaluations.append(
                            ToolCallEvaluation(
                                tool_name=function_name,
                                is_passed=False,
                                failure_reason="Unexpected tool call",
                            )
                        )
                        continue

                    # 2. Check the function was called with the expected arguments
                    used_args = tool_call.get("function", {}).get("arguments", {})
                    expected_args = expected_tool_call.tool_call_args  # type: ignore
                    import json

                    # Strict check: we check if the provided arguments are equal to the used arguments
                    if self.strict_args_check is True:
                        parsed_used_args = json.loads(used_args)
                        if parsed_used_args == expected_args:
                            tool_call_evaluations.append(
                                ToolCallEvaluation(
                                    tool_name=function_name,
                                    is_passed=True,
                                    used_args=parsed_used_args,
                                    expected_args=expected_args,
                                )
                            )

                        else:
                            tool_call_evaluations.append(
                                ToolCallEvaluation(
                                    tool_name=function_name,
                                    is_passed=False,
                                    used_args=parsed_used_args,
                                    expected_args=expected_args,
                                    failure_reason="Unexpected arguments",
                                )
                            )
                    # Non-strict check: we check if the provided arguments were used
                    else:
                        parsed_used_args = json.loads(used_args)
                        if all(
                            key in parsed_used_args and parsed_used_args[key] == value
                            for key, value in expected_args.items()
                        ):
                            tool_call_evaluations.append(
                                ToolCallEvaluation(
                                    tool_name=function_name,
                                    is_passed=True,
                                    used_args=parsed_used_args,
                                    expected_args=expected_args,
                                )
                            )
                        else:
                            tool_call_evaluations.append(
                                ToolCallEvaluation(
                                    tool_name=function_name,
                                    is_passed=False,
                                    used_args=used_args,
                                    expected_args=expected_args,
                                    failure_reason="Missing expected arguments",
                                )
                            )

                # Handle expected tool calls that were not made
                for expected in self.expected_tool_calls:
                    if expected.tool_name not in called_expected_tools:  # type: ignore
                        tool_call_evaluations.append(
                            ToolCallEvaluation(
                                tool_name=expected.tool_name,  # type: ignore
                                expected_args=expected.tool_call_args,  # type: ignore
                                is_passed=False,
                                failure_reason="Expected call was not made",
                            )
                        )

            self.result = ReliabilityResult(
                eval_status="FAILED"
                if any(not evaluation.is_passed for evaluation in tool_call_evaluations)
                else "PASSED",
                tool_call_evaluations=tool_call_evaluations,
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
        if self.monitoring:
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

            log_eval_run(
                run_id=self.eval_id,  # type: ignore
                run_data=asdict(self.result),
                eval_type=EvalType.RELIABILITY,
                name=self.name if self.name is not None else None,
                agent_id=agent_id,
                team_id=team_id,
                model_id=model_id,
                model_provider=model_provider,
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

            actual_tool_calls: list[dict[str, Any]] = []
            if self.agent_response is not None:
                messages = self.agent_response.messages
            elif self.team_response is not None:
                messages = self.team_response.messages or []
                for member_response in self.team_response.member_responses:
                    if member_response.messages is not None:
                        messages += member_response.messages

            for message in reversed(messages):  # type: ignore
                if message.tool_calls:
                    actual_tool_calls.append(message.tool_calls[0])  # type: ignore

            tool_call_evaluations: list[ToolCallEvaluation] = []

            # If expected_tool_calls is a list of function names, we check if the functions were called
            if isinstance(self.expected_tool_calls[0], str):
                called_expected_tools = set()
                for tool_call in actual_tool_calls:
                    function_name = tool_call.get("function", {}).get("name")
                    if not function_name:
                        continue

                    if function_name in self.expected_tool_calls:
                        called_expected_tools.add(function_name)
                        tool_call_evaluations.append(ToolCallEvaluation(tool_name=function_name, is_passed=True))
                    else:
                        tool_call_evaluations.append(
                            ToolCallEvaluation(
                                tool_name=function_name,
                                is_passed=False,
                                failure_reason="Unexpected tool call",
                            )
                        )
                # Handle expected tool calls that were not made
                for tool_name in self.expected_tool_calls:
                    if tool_name not in called_expected_tools:  # type: ignore
                        tool_call_evaluations.append(
                            ToolCallEvaluation(
                                tool_name=tool_name,  # type: ignore
                                is_passed=False,
                                failure_reason="Expected call was not made",
                            )
                        )

            # If expected_tool_calls is a list of ToolCall, we check if the functions were called with the expected arguments
            elif isinstance(self.expected_tool_calls[0], ExpectedToolCall):
                called_expected_tools = set()
                for tool_call in actual_tool_calls:
                    function_name = tool_call.get("function", {}).get("name")
                    if not function_name:
                        continue

                    # 1. Check the function was called
                    expected_tool_call = None
                    for expected in self.expected_tool_calls:
                        if expected.tool_name == function_name:  # type: ignore
                            called_expected_tools.add(function_name)
                            expected_tool_call = expected
                            break
                    if not expected_tool_call:
                        tool_call_evaluations.append(
                            ToolCallEvaluation(
                                tool_name=function_name,
                                is_passed=False,
                                failure_reason="Unexpected tool call",
                            )
                        )
                        continue

                    # 2. Check the function was called with the expected arguments
                    used_args = tool_call.get("function", {}).get("arguments", {})
                    expected_args = expected_tool_call.tool_call_args  # type: ignore
                    import json

                    # Strict check: we check if the provided arguments are equal to the used arguments
                    if self.strict_args_check is True:
                        parsed_used_args = json.loads(used_args)
                        if parsed_used_args == expected_args:
                            tool_call_evaluations.append(
                                ToolCallEvaluation(
                                    tool_name=function_name,
                                    is_passed=True,
                                    used_args=parsed_used_args,
                                    expected_args=expected_args,
                                )
                            )

                        else:
                            tool_call_evaluations.append(
                                ToolCallEvaluation(
                                    tool_name=function_name,
                                    is_passed=False,
                                    used_args=parsed_used_args,
                                    expected_args=expected_args,
                                    failure_reason="Unexpected arguments",
                                )
                            )
                    # Non-strict check: we check if the provided arguments were used
                    else:
                        parsed_used_args = json.loads(used_args)
                        if all(
                            key in parsed_used_args and parsed_used_args[key] == value
                            for key, value in expected_args.items()
                        ):
                            tool_call_evaluations.append(
                                ToolCallEvaluation(
                                    tool_name=function_name,
                                    is_passed=True,
                                    used_args=parsed_used_args,
                                    expected_args=expected_args,
                                )
                            )
                        else:
                            tool_call_evaluations.append(
                                ToolCallEvaluation(
                                    tool_name=function_name,
                                    is_passed=False,
                                    used_args=used_args,
                                    expected_args=expected_args,
                                    failure_reason="Missing expected arguments",
                                )
                            )

                # Handle expected tool calls that were not made
                for expected in self.expected_tool_calls:
                    if expected.tool_name not in called_expected_tools:  # type: ignore
                        tool_call_evaluations.append(
                            ToolCallEvaluation(
                                tool_name=expected.tool_name,  # type: ignore
                                expected_args=expected.tool_call_args,  # type: ignore
                                is_passed=False,
                                failure_reason="Expected call was not made",
                            )
                        )

            self.result = ReliabilityResult(
                eval_status="FAILED"
                if any(not evaluation.is_passed for evaluation in tool_call_evaluations)
                else "PASSED",
                tool_call_evaluations=tool_call_evaluations,
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
        if self.monitoring:
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

            await async_log_eval_run(
                run_id=self.eval_id,  # type: ignore
                run_data=asdict(self.result),
                eval_type=EvalType.RELIABILITY,
                name=self.name if self.name is not None else None,
                agent_id=agent_id,
                team_id=team_id,
                model_id=model_id,
                model_provider=model_provider,
            )

        logger.debug(f"*********** Evaluation End: {self.eval_id} ***********")
        return self.result
