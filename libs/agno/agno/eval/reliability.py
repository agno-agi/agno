from dataclasses import asdict, dataclass
from os import getenv
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional
from uuid import uuid4

if TYPE_CHECKING:
    from rich.console import Console

from agno.run.response import RunResponse
from agno.utils.log import logger, set_log_level_to_debug, set_log_level_to_info


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


@dataclass
class ReliabilityEval:
    """Evaluate the reliability of a model by checking the tool calls"""

    # Evaluation name
    name: Optional[str] = None

    # Evaluation UUID (autogenerated if not set)
    eval_id: Optional[str] = None

    # Agent response
    agent_response: Optional[RunResponse] = None

    # Expected tool calls
    expected_tool_calls: Optional[List[str]] = None

    # Result of the evaluation
    result: Optional[ReliabilityResult] = None

    # Print summary of results
    print_summary: bool = False
    # Print detailed results
    print_results: bool = False
    # Save the result to a file
    save_result_to_file: Optional[str] = None

    # debug_mode=True enables debug logs
    debug_mode: bool = False

    def set_eval_id(self) -> str:
        if self.eval_id is None:
            self.eval_id = str(uuid4())
        logger.debug(f"*********** Evaluation ID: {self.eval_id} ***********")
        return self.eval_id

    def set_debug_mode(self) -> None:
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
            logger.debug("Debug logs enabled")
        else:
            set_log_level_to_info()

    def run(self, *, print_summary: bool = False, print_results: bool = False) -> Optional[ReliabilityResult]:
        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        self.set_eval_id()
        self.set_debug_mode()
        self.print_results = print_results
        self.print_summary = print_summary

        # Add a spinner while running the evaluations
        console = Console()
        with Live(console=console, transient=True) as live_log:
            status = Status("Running evaluation...", spinner="dots", speed=1.0, refresh_per_second=10)
            live_log.update(status)

            actual_tool_calls = None
            if self.agent_response is not None:
                for message in reversed(self.agent_response.messages):  # type: ignore
                    if message.tool_calls:
                        if actual_tool_calls is None:
                            actual_tool_calls = message.tool_calls
                    else:
                        actual_tool_calls.append(message.tool_calls[0])  # type: ignore

            failed_tool_calls = []
            passed_tool_calls = []
            for tool_call in actual_tool_calls:  # type: ignore
                if tool_call.get("function", {}).get("name") not in self.expected_tool_calls:  # type: ignore
                    failed_tool_calls.append(tool_call.get("function", {}).get("name"))
                else:
                    passed_tool_calls.append(tool_call.get("function", {}).get("name"))

            self.result = ReliabilityResult(
                eval_status="PASSED" if len(failed_tool_calls) == 0 else "FAILED",
                failed_tool_calls=failed_tool_calls,
                passed_tool_calls=passed_tool_calls,
            )

        # -*- Save result to file if save_result_to_file is set
        if self.save_result_to_file is not None and self.result is not None:
            try:
                import json

                fn_path = Path(self.save_result_to_file.format(name=self.name, eval_id=self.eval_id))
                if not fn_path.parent.exists():
                    fn_path.parent.mkdir(parents=True, exist_ok=True)
                fn_path.write_text(json.dumps(asdict(self.result), indent=4))
            except Exception as e:
                logger.warning(f"Failed to save result to file: {e}")

        # Show results
        if self.print_summary or self.print_results:
            self.result.print_eval(console)

        logger.debug(f"*********** Evaluation End: {self.eval_id} ***********")
        return self.result
