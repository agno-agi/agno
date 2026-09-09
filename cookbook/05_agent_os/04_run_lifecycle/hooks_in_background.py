"""
Run AgentOS hooks in the background
===================================

Show both levels of background-hook control without conflating their behavior:
the ``global`` server mode applies ``run_hooks_in_background=True`` to every
non-guardrail hook, while the ``mixed`` mode keeps one blocking evaluator and
marks selected hooks and a second evaluator for background execution.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/hooks_in_background.py --mode global
Try: Restart with --mode mixed and compare when the response returns
"""

import argparse
import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.hooks import hook
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.run.agent import RunInput, RunOutput

# ---------------------------------------------------------------------------
# Create Background Hooks
# ---------------------------------------------------------------------------


def log_request(run_input: RunInput, agent: Agent) -> None:
    """Log a request; global mode schedules this plain hook in the background."""
    print(f"Request received by {agent.id}: {run_input.input_content}")


async def record_global_result(run_output: RunOutput, agent: Agent) -> None:
    """Simulate a post-run write controlled by the AgentOS-wide switch."""
    await asyncio.sleep(1)
    print(f"Global background hook stored run {run_output.run_id} for {agent.id}")


def record_blocking_result(run_output: RunOutput, agent: Agent) -> None:
    """Represent work that must finish before mixed mode returns its response."""
    print(f"Blocking hook checked run {run_output.run_id} for {agent.id}")


@hook(run_in_background=True)
async def send_notification(run_output: RunOutput, agent: Agent) -> None:
    """Represent non-critical work selected with the per-hook decorator."""
    await asyncio.sleep(1)
    print(f"Background notification sent for run {run_output.run_id} by {agent.id}")


global_db = SqliteDb(
    id="global-background-hooks-db",
    db_file="tmp/agent_os_global_background_hooks.db",
)

global_hooks_agent = Agent(
    id="global-hooks-agent",
    name="Global Hooks Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=global_db,
    pre_hooks=[log_request],
    post_hooks=[record_global_result],
)

global_agent_os = AgentOS(
    id="global-background-hooks-os",
    agents=[global_hooks_agent],
    run_hooks_in_background=True,
)
global_app = global_agent_os.get_app()

mixed_db = SqliteDb(
    id="mixed-background-hooks-db",
    db_file="tmp/agent_os_mixed_background_hooks.db",
)

blocking_eval = AgentAsJudgeEval(
    name="Blocking completeness check",
    model=OpenAIResponses(id="gpt-5.5"),
    db=mixed_db,
    criteria="The response directly and completely answers the request.",
    print_summary=True,
    telemetry=False,
)

background_eval = AgentAsJudgeEval(
    name="Background clarity check",
    model=OpenAIResponses(id="gpt-5.5"),
    db=mixed_db,
    criteria="The response is concise, clear, and easy to act on.",
    print_summary=True,
    run_in_background=True,
    telemetry=False,
)

mixed_hooks_agent = Agent(
    id="mixed-hooks-agent",
    name="Mixed Hooks Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=mixed_db,
    post_hooks=[
        record_blocking_result,
        blocking_eval,
        send_notification,
        background_eval,
    ],
)

mixed_agent_os = AgentOS(
    id="mixed-background-hooks-os",
    agents=[mixed_hooks_agent],
)
mixed_app = mixed_agent_os.get_app()

# Keep a conventional app export for module runners; it is the global example.
app = global_app


# ---------------------------------------------------------------------------
# Run Background Hooks AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("global", "mixed"),
        default="global",
        help="Serve the global switch example or the mixed per-hook example.",
    )
    args = parser.parse_args()

    selected_os = global_agent_os if args.mode == "global" else mixed_agent_os
    selected_app = global_app if args.mode == "global" else mixed_app
    selected_os.serve(app=selected_app)
