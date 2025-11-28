from dataclasses import asdict, dataclass, field
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union
from uuid import uuid4

from agno.db.base import AsyncBaseDb, BaseDb

if TYPE_CHECKING:
    from rich.console import Console

from agno.db.schemas.evals import EvalType
from agno.eval.base import BaseEvalHook
from agno.eval.utils import async_log_eval, log_eval_run, store_result_in_file
from agno.run.agent import RunInput, RunOutput
from agno.run.team import TeamRunInput, TeamRunOutput
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
class ReliabilityEval(BaseEvalHook):
    """Evaluate the reliability of a model by checking the tool calls"""

    # Evaluation name
    name: Optional[str] = None
    # Evaluation UUID that will be same across runs
    eval_id: str = field(default_factory=lambda: str(uuid4()))
    # Run UUID that will be different across runs
    run_id: Optional[str] = None
    # Parent run ID to link this eval to the agent/team run
    parent_run_id: Optional[str] = None
    # Parent session ID to link this eval to the agent/team session
    parent_session_id: Optional[str] = None

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
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None

    # Telemetry settings
    # telemetry=True logs minimal telemetry for analytics
    # This helps us improve our Evals and provide better support
    telemetry: bool = True

    def _log_eval_to_db(
        self,
        run_id: str,
        parent_run_id: Optional[str] = None,
        parent_session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
    ) -> None:
        """Helper method to log eval results to database"""
        if not self.db:
            return

        eval_input = {
            "expected_tool_calls": self.expected_tool_calls,
        }

        log_eval_run(
            db=self.db,  # type: ignore[arg-type]
            run_id=run_id,
            eval_id=self.eval_id,
            run_data=asdict(self.result) if self.result else {},
            eval_type=EvalType.RELIABILITY,
            name=self.name if self.name is not None else None,
            agent_id=agent_id,
            team_id=team_id,
            model_id=model_id,
            model_provider=model_provider,
            eval_input=eval_input,
            parent_run_id=parent_run_id or self.parent_run_id,
            parent_session_id=parent_session_id or self.parent_session_id,
        )

    async def _async_log_eval_to_db(
        self,
        run_id: str,
        parent_run_id: Optional[str] = None,
        parent_session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
    ) -> None:
        """Helper method to asynchronously log eval results to database"""
        if not self.db:
            return

        eval_input = {
            "expected_tool_calls": self.expected_tool_calls,
        }

        await async_log_eval(
            db=self.db,  # type: ignore[arg-type]
            run_id=run_id,
            eval_id=self.eval_id,
            run_data=asdict(self.result) if self.result else {},
            eval_type=EvalType.RELIABILITY,
            name=self.name if self.name is not None else None,
            agent_id=agent_id,
            team_id=team_id,
            model_id=model_id,
            model_provider=model_provider,
            eval_input=eval_input,
            parent_run_id=parent_run_id or self.parent_run_id,
            parent_session_id=parent_session_id or self.parent_session_id,
        )

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
                        if self.expected_tool_calls is not None and tool_name not in self.expected_tool_calls:  # type: ignore
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
        # Generate a run_id for this run allowing the same eval object to be run multiple times
        self.run_id = str(uuid4())

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

            self._log_eval_to_db(
                run_id=self.run_id,
                agent_id=agent_id,
                team_id=team_id,
                model_id=model_id,
                model_provider=model_provider,
            )

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, create_eval_run_telemetry

            create_eval_run_telemetry(
                eval_run=EvalRunCreate(
                    run_id=self.run_id,
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
                    if self.expected_tool_calls is not None and tool_name not in self.expected_tool_calls:  # type: ignore
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
        # Generate a run_id for this run allowing the same eval object to be run multiple times
        self.run_id = str(uuid4())

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

            await self._async_log_eval_to_db(
                run_id=self.run_id,
                agent_id=agent_id,
                team_id=team_id,
                model_id=model_id,
                model_provider=model_provider,
            )

        if self.telemetry:
            from agno.api.evals import EvalRunCreate, async_create_eval_run_telemetry

            await async_create_eval_run_telemetry(
                eval_run=EvalRunCreate(
                    run_id=self.run_id,
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

    def pre_check(self, run_input: Union[RunInput, TeamRunInput], session=None) -> None:
        """Perform sync pre-evals check."""
        pass

    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput], session=None) -> None:
        """Perform async pre-evals check."""
        pass

    def _evaluate_from_run_output(self, run_output: Union[RunOutput, TeamRunOutput]) -> ReliabilityResult:
        """Extract and evaluate tool calls from run output."""
        # Extract tool calls from messages
        messages = run_output.messages or []
        if isinstance(run_output, TeamRunOutput):
            for member_response in run_output.member_responses:
                if member_response.messages is not None:
                    messages += member_response.messages

        actual_tool_calls = None
        for message in reversed(messages):
            if message.tool_calls:
                if actual_tool_calls is None:
                    actual_tool_calls = message.tool_calls
                else:
                    actual_tool_calls.append(message.tool_calls[0])

        failed_tool_calls = []
        passed_tool_calls = []
        if not actual_tool_calls:
            failed_tool_calls = self.expected_tool_calls or []
        else:
            for tool_call in actual_tool_calls:
                tool_name = tool_call.get("function", {}).get("name")
                if not tool_name:
                    continue
                else:
                    if self.expected_tool_calls is not None and tool_name not in self.expected_tool_calls:
                        failed_tool_calls.append(tool_call.get("function", {}).get("name"))
                    else:
                        passed_tool_calls.append(tool_call.get("function", {}).get("name"))

        return ReliabilityResult(
            eval_status="PASSED" if len(failed_tool_calls) == 0 else "FAILED",
            failed_tool_calls=failed_tool_calls,
            passed_tool_calls=passed_tool_calls,
        )

    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Perform sync post-evals check and tie eval to the parent run."""
        # Use helper method to evaluate
        self.result = self._evaluate_from_run_output(run_output)

        if not self.db:
            return

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("post_check() is not supported with an async DB. Use async_post_check() instead.")

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
        else:
            raise TypeError(f"run_output must be RunOutput or TeamRunOutput, got {type(run_output)}")

        # Generate a run_id for this run allowing the same eval object to be run multiple times
        self.run_id = str(uuid4())

        self._log_eval_to_db(
            run_id=self.run_id,
            parent_run_id=run_output.run_id,
            parent_session_id=run_output.session_id,
            agent_id=agent_id,
            team_id=team_id,
            model_id=model_id,
            model_provider=model_provider,
        )

    async def async_post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Perform async post-evals check and tie eval to the parent run."""
        # Use helper method to evaluate
        self.result = self._evaluate_from_run_output(run_output)

        if not self.db:
            return

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
        else:
            raise TypeError(f"run_output must be RunOutput or TeamRunOutput, got {type(run_output)}")

         # Generate a run_id for this run allowing the same eval object to be run multiple times
        self.run_id = str(uuid4())

        await self._async_log_eval_to_db(
            run_id=self.run_id,
            parent_run_id=run_output.run_id,
            parent_session_id=run_output.session_id,
            agent_id=agent_id,
            team_id=team_id,
            model_id=model_id,
            model_provider=model_provider,
        )
