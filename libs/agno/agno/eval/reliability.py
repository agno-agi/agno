from dataclasses import asdict, dataclass, field
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Union
from uuid import uuid4

from agno.db.base import AsyncBaseDb, BaseDb
from agno.models.response import ToolExecution
from agno.run.team import TeamRunOutput

if TYPE_CHECKING:
    from rich.console import Console

from agno.agent import RunOutput
from agno.db.schemas.evals import EvalType
from agno.eval.utils import async_log_eval, log_eval_run, spinner_live, store_result_in_file
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
        # The result rides in the assert message: when CI goes red under execution
        # matching (new in 2.8.0), the annotated entries say in one read whether the
        # eval was wrong or the agent was.
        assert self.eval_status == "PASSED", f"ReliabilityEval failed: {self}"


def _collect_member_evidence(response: Any, executions: List[ToolExecution], messages: list) -> None:
    """Collect tools and messages from a response and every nested member response.

    Only TeamRunOutput carries member_responses; a member RunOutput is a leaf. Inner
    team leaders' own executions (e.g. delegate_task_to_member) surface at every depth,
    matching what a depth-0 leader already reports today.
    """
    executions += list(response.tools or [])
    if response.messages is not None:
        messages += response.messages
    for member_response in getattr(response, "member_responses", None) or []:
        _collect_member_evidence(member_response, executions, messages)


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
    # Render the transient progress spinner. Embedders that must not write to the
    # console (e.g. the suite runner) disable it.
    show_spinner: bool = True
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
        """Core evaluation logic: tool evidence comes from executions, not requests.

        New in 2.8.0: an expectation is satisfied only by a clean execution -- an entry
        in `tools` whose `tool_call_error` is not true (`None` counts as clean; runs
        rehydrated from storage carry `None` for success). Request-side matching
        counted calls that were refused, errored, or given junk arguments, which made
        the eval satisfiable without the tool ever doing work. Evals that passed that
        way now fail, and their `missing_tool_calls` entries say why.
        """
        executions: List[ToolExecution] = []
        messages: list = []
        if self.agent_response is not None:
            executions = list(self.agent_response.tools or [])
            messages = list(self.agent_response.messages or [])
        elif self.team_response is not None:
            # Union the members' executions at every nesting depth: delegated tool
            # calls live on member responses, members can themselves be teams, and a
            # flat read would report a grandchild's clean execution as missing.
            _collect_member_evidence(self.team_response, executions, messages)

        # Message-side REQUESTS are kept only to annotate failures: a call refused by
        # tool_call_limit never produces an execution, so the request is the only
        # evidence it was attempted at all. Prior-turn messages injected by
        # add_history_to_context carry tool_calls this run never made, so they are
        # excluded -- yesterday's tools must not fail today's strict eval.
        requested_names: Set[str] = set()
        for message in messages:
            if getattr(message, "from_history", False):
                continue
            for tool_call in message.tool_calls or []:
                func = tool_call.get("function")
                tool_name = func.get("name") if isinstance(func, dict) else None
                if tool_name:
                    requested_names.add(tool_name)

        failed_tool_calls: List[str] = []
        passed_tool_calls: List[str] = []
        additional_tool_calls: List[str] = []
        missing_tool_calls: List[str] = []
        failed_argument_checks: List[str] = []
        passed_argument_checks: List[str] = []

        clean_executions = [t for t in executions if t.tool_name and not t.tool_call_error and not t.is_paused]
        clean_names = {t.tool_name for t in clean_executions}
        attempted_names = {t.tool_name for t in executions if t.tool_name} | requested_names

        # Classify every execution, one entry per call (the per-call shape is part of
        # the contract: this payload is logged to the db).
        for tool in executions:
            tool_name = tool.tool_name
            if not tool_name:
                continue
            if self.expected_tool_calls is not None and tool_name not in self.expected_tool_calls:
                if self.allow_additional_tool_calls:
                    additional_tool_calls.append(tool_name)
                else:
                    # Strict mode polices the attempt, not its success: an unexpected
                    # call that errored or was refused still fails the eval.
                    failed_tool_calls.append(tool_name)
            elif not tool.tool_call_error and not tool.is_paused:
                passed_tool_calls.append(tool_name)
            # An errored execution of an EXPECTED tool is neither passed nor failed by
            # itself: it cannot satisfy the expectation, and the failure surfaces as
            # the annotated missing entry below when no clean execution exists -- so a
            # retry that eventually succeeds still passes.

        # Request-only names: a call refused by tool_call_limit never produces an
        # execution, so the message-side request is its only trace. An unexpected
        # refused request is still the agent attempting an unexpected tool -- strict
        # mode fails it, lenient mode keeps it visible as an additional call. A
        # refused EXPECTED tool instead surfaces as the annotated missing entry.
        if self.expected_tool_calls is not None:
            executed_names = {t.tool_name for t in executions if t.tool_name}
            for requested in sorted(requested_names - executed_names):
                if requested in self.expected_tool_calls:
                    continue
                if self.allow_additional_tool_calls:
                    additional_tool_calls.append(requested)
                else:
                    failed_tool_calls.append(requested)

        # Missing: expected names with no clean execution. When the tool was requested
        # or attempted but every execution was refused/errored, the entry says so --
        # a red CI gate must be readable as "the eval was wrong, not the agent".
        missing_names: Set[str] = set()
        if self.expected_tool_calls:
            for expected_tool in self.expected_tool_calls:
                if expected_tool not in clean_names:
                    missing_names.add(expected_tool)
                    if expected_tool in attempted_names:
                        missing_tool_calls.append(
                            f"{expected_tool} (requested but refused/errored — execution matching, new in 2.8.0)"
                        )
                    else:
                        missing_tool_calls.append(expected_tool)

        # Argument checks read ToolExecution.tool_args -- already parsed, None -> {} --
        # and are satisfied only by clean executions: message-side requests can carry
        # arguments for calls that never did work.
        if self.expected_tool_call_arguments:
            for arg_tool_name, expected_args_raw in self.expected_tool_call_arguments.items():
                # Skip argument checks for tools already tracked as missing
                if arg_tool_name in missing_names:
                    continue

                # Normalize: single dict becomes a one-element list
                arg_specs = expected_args_raw if isinstance(expected_args_raw, list) else [expected_args_raw]

                parsed_args_list: List[Dict[str, Any]] = [
                    dict(t.tool_args or {}) for t in clean_executions if t.tool_name == arg_tool_name
                ]
                if not parsed_args_list:
                    failed_argument_checks.append(arg_tool_name)
                    continue

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
        from rich.status import Status

        # Generate unique run_id for this execution (don't modify self.eval_id due to concurrency)
        run_id = str(uuid4())

        # Add a spinner while running the evaluations
        console = Console()
        with spinner_live(console, self.show_spinner) as live_log:
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
        from rich.status import Status

        # Generate unique run_id for this execution (don't modify self.eval_id due to concurrency)
        run_id = str(uuid4())

        # Add a spinner while running the evaluations
        console = Console()
        with spinner_live(console, self.show_spinner) as live_log:
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
