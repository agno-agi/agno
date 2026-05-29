"""
Run Evals
=========

python -m evals                # run all cases (concise UI)
python -m evals --case <name>  # run one case
python -m evals -v             # stream the agent's run with full panels

Each case runs the agent once, then optionally checks the response with
`AgentAsJudgeEval` (when `criteria` is set) and `ReliabilityEval` (when
`expected_tool_calls` is set).

Both log to Postgres through `eval_db`. Connect AgentOS at os.agno.com to see history.

Exit 0 on all-pass, non-zero on any failure or error.
"""

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import typer
from agents.code_search import code_search_provider
from agents.git_wiki import git_wiki_provider
from agents.local_wiki import local_wiki_provider
from agents.web_search import web_provider
from agno.eval import AgentAsJudgeEval, ReliabilityEval
from agno.run.agent import RunOutput
from rich.console import Console
from rich.live import Live
from rich.status import Status
from rich.table import Table

from evals.cases import CASES, Case, eval_db

app = typer.Typer(
    add_completion=False, no_args_is_help=False, pretty_exceptions_show_locals=False
)
console = Console()


@dataclass
class CaseOutcome:
    name: str
    judge_passed: bool | None = None
    reliability_passed: bool | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        if self.error:
            return False
        checks = [
            c for c in (self.judge_passed, self.reliability_passed) if c is not None
        ]
        return bool(checks) and all(checks)


async def _run_case_async(case: Case, *, verbose: bool) -> CaseOutcome:
    judge_passed: bool | None = None
    rel_passed: bool | None = None
    judge_err: str | None = None
    rel_err: str | None = None

    session_id = f"eval-{case.name}-{uuid4().hex[:8]}"

    response: RunOutput | None
    try:
        if verbose:
            await case.agent.aprint_response(
                input=case.input,
                stream=True,
                session_id=session_id,
                markdown=True,
            )
            response = await case.agent.aget_last_run_output(session_id=session_id)
        else:
            response = await _run_with_live_spinner(case, session_id)
        if response is None:
            return CaseOutcome(name=case.name, error="agent: no run output recorded")
    except Exception as exc:
        return CaseOutcome(
            name=case.name, error=f"agent.arun: {type(exc).__name__}: {exc}"
        )

    output_str = str(response.content) if response.content else ""

    if not verbose:
        _print_response_concise(response, output_str)

    if case.criteria is not None:
        try:
            judge = await AgentAsJudgeEval(
                name=case.name,
                criteria=case.criteria,
                scoring_strategy="binary",
                db=eval_db,
            ).arun(input=case.input, output=output_str, print_results=verbose)
        except Exception as exc:
            judge_err = f"judge: {type(exc).__name__}: {exc}"
        else:
            if judge and judge.results:
                judge_passed = judge.results[0].passed
                if not verbose:
                    _print_judge_verdict(judge.results[0])
            else:
                judge_err = "judge: returned no result"

    if case.expected_tool_calls is not None:
        try:
            rel = ReliabilityEval(
                name=case.name,
                agent_response=response,
                expected_tool_calls=list(case.expected_tool_calls),
                allow_additional_tool_calls=case.allow_additional_tool_calls,
                db=eval_db,
            ).run(print_results=verbose)
        except Exception as exc:
            rel_err = f"reliability: {type(exc).__name__}: {exc}"
        else:
            if rel is None:
                rel_err = "reliability: returned no result"
            else:
                rel_passed = rel.eval_status == "PASSED"
                if not verbose:
                    _print_reliability_verdict(rel, case.expected_tool_calls)

    return CaseOutcome(
        name=case.name,
        judge_passed=judge_passed,
        reliability_passed=rel_passed,
        error="; ".join(e for e in (judge_err, rel_err) if e) or None,
    )


async def _run_with_live_spinner(case: Case, session_id: str) -> RunOutput | None:
    """Stream the agent's run with a single-line spinner that updates per tool call."""
    base_label = f"[bold]running[/bold] {case.agent.id}…"
    spinner = Status(base_label, spinner="dots")

    response: RunOutput | None = None
    with Live(spinner, console=console, transient=True, refresh_per_second=10):
        async for event in case.agent.arun(
            input=case.input,
            stream=True,
            stream_events=True,
            yield_run_output=True,
            session_id=session_id,
        ):
            if isinstance(event, RunOutput):
                response = event
                continue
            event_type = getattr(event, "event", None)
            if event_type == "ToolCallStarted":
                tool = getattr(event, "tool", None)
                tool_name = getattr(tool, "tool_name", None)
                if tool_name:
                    spinner.update(
                        f"[bold]running[/bold] {case.agent.id} → [cyan]{tool_name}[/cyan]…"
                    )
            elif event_type == "ToolCallCompleted":
                spinner.update(base_label)

    return response


def _print_response_concise(response: RunOutput, output_str: str) -> None:
    console.print()
    console.print("[bold]Response[/bold]")
    console.print(output_str or "[dim](empty)[/dim]")

    tools = response.tools or []
    if tools:
        names = ", ".join(t.tool_name or "?" for t in tools)
        console.print(f"\n[dim]tools fired:[/dim] {names}")


def _print_judge_verdict(eval_result: object) -> None:
    passed: bool = bool(getattr(eval_result, "passed", False))
    reason: str = str(getattr(eval_result, "reason", "") or "")
    style = "green" if passed else "red"
    tag = "PASS" if passed else "FAIL"
    console.print(f"\n[bold]Judge:[/bold] [{style}]{tag}[/{style}]")
    if reason:
        console.print(f"[dim]  {reason}[/dim]")


def _print_reliability_verdict(
    rel_result: object, expected_tools: tuple[str, ...]
) -> None:
    passed = getattr(rel_result, "eval_status", "") == "PASSED"
    style = "green" if passed else "red"
    tag = "PASS" if passed else "FAIL"
    expected = ", ".join(expected_tools)
    console.print(
        f"\n[bold]Reliability:[/bold] [{style}]{tag}[/{style}]  [dim]expected: {expected}[/dim]"
    )


def _check_cell(passed: bool | None) -> str:
    if passed is None:
        return "[dim]—[/dim]"
    style = "green" if passed else "red"
    tag = "PASS" if passed else "FAIL"
    return f"[{style}]{tag}[/{style}]"


async def _close_providers() -> None:
    """Release MCP sessions held by the context providers."""
    await local_wiki_provider.aclose()
    await web_provider.aclose()
    await code_search_provider.aclose()
    if git_wiki_provider is not None:
        await git_wiki_provider.aclose()


async def _amain(cases: list[Case], *, verbose: bool) -> list[CaseOutcome]:
    try:
        outcomes: list[CaseOutcome] = []
        for i, c in enumerate(cases, 1):
            console.rule(
                f"[bold]{c.name}[/bold]  [dim]{c.agent.id} · {i}/{len(cases)}[/dim]"
            )
            outcomes.append(await _run_case_async(c, verbose=verbose))
        return outcomes
    finally:
        await _close_providers()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    case: str = typer.Option(None, "--case", help="Run only this case by name"),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Stream the full agent run with rich panels (Message → Tool Calls → Response).",
    ),
) -> None:
    """Run the eval suite, or one case with --case <name>."""
    if ctx.invoked_subcommand is not None:
        return

    cases = list(CASES)
    if case:
        cases = [c for c in cases if c.name == case]
        if not cases:
            console.print(f"[red]no case named[/red] {case!r}")
            console.print(f"  [dim]available:[/dim] {', '.join(c.name for c in CASES)}")
            raise typer.Exit(2)

    outcomes = asyncio.run(_amain(cases, verbose=verbose))

    table = Table(
        title="Eval Summary",
        title_style="bold sky_blue1",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Case", overflow="fold")
    table.add_column("Judge")
    table.add_column("Reliability")
    table.add_column("Status")
    for o in outcomes:
        status = "[green]PASS[/green]" if o.passed else "[red]FAIL[/red]"
        table.add_row(
            o.name,
            _check_cell(o.judge_passed),
            _check_cell(o.reliability_passed),
            status,
        )

    console.print()
    console.print(table)

    passed = sum(1 for o in outcomes if o.passed)
    failed = len(outcomes) - passed
    summary = f"[green]{passed}/{len(outcomes)} passed[/green]"
    if failed:
        summary += f", [red]{failed} failed[/red]"
    console.print(f"\n{summary}")

    for o in outcomes:
        if o.error:
            console.print(f"  [dim]{o.name}:[/dim] [red]{o.error}[/red]")

    raise typer.Exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    app()
