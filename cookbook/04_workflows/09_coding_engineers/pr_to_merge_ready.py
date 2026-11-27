"""
Pull Request To Merge-Ready
===========================

Takes one GitHub pull request through review rounds until nothing real is left to fix.

Each round:
1. A Claude engineer and a Codex engineer review the pull request at the same time, each in its
   own Docker sandbox, without seeing the other's review.
2. A triage agent keeps only the points that are real problems a user would hit. Nitpicks are dropped.
3. If nothing is kept, the pull request is merge-ready and the workflow stops.
4. Otherwise one engineer fixes the kept points in its own sandbox checkout, and the next round
   reviews the pull request with that fix applied.

It stops after three rounds. The result is a plain report: per round, what each reviewer found, what
triage kept and why, what was fixed, and the fix as a diff. Nothing is pushed and nothing is posted
to GitHub: the sandboxes get no GitHub token that can write.

Prerequisites: Docker, the sandbox runtime image (cookbook/frameworks/sandbox/build_image.py),
PostgreSQL (./cookbook/scripts/run_pgvector.sh), ANTHROPIC_API_KEY and OPENAI_API_KEY.
Run: .venvs/demo/bin/python cookbook/04_workflows/09_coding_engineers/pr_to_merge_ready.py https://github.com/agno-agi/agno/pull/11950
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.request import Request, urlopen

from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.sandbox import Repository
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from agno.workflow import Condition, Loop, Parallel, Step, Workflow
from agno.workflow.types import StepInput, StepOutput
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# The engineers' sandboxes check out this repository. The workflow accepts pull requests of this repository only.
REPOSITORY_URL = os.getenv("REVIEW_REPOSITORY_URL", "https://github.com/agno-agi/agno")
REPOSITORY_BRANCH = os.getenv("REVIEW_REPOSITORY_BRANCH", "main")
MAX_ROUNDS = 3
# The most of a pull request's diff that is pasted into a brief. The engineers read the rest in their checkout.
DIFF_LIMIT = 60000

db = PostgresDb(
    id="merge-ready-db",
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)
repository = Repository(url=REPOSITORY_URL, branch=REPOSITORY_BRANCH)
checkpoints = FileCheckpointStore(Path.home() / ".agno" / "sandbox" / "checkpoints")


def sandbox(namespace: str) -> DockerSandbox:
    """One Docker sandbox per engineer. No GitHub token is passed in, so an engineer can read a public repository and nothing more."""
    return DockerSandbox(
        os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
        namespace=namespace,
        network="isolated",
        # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
        subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
        memory_mb=2048,
        workspace_mb=2048,
        execution_timeout=1800,
        checkpoints=checkpoints,
    )


# ---------------------------------------------------------------------------
# Create the Engineers and the Triage Agent
# ---------------------------------------------------------------------------

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
CODEX_MODEL = os.getenv("CODEX_MODEL", "gpt-5.6-luna")

# The Docker container is the boundary, so each engineer may run any command inside it without asking.
claude_reviewer = ClaudeAgent(
    id="merge-ready-claude-reviewer",
    name="Claude Reviewer",
    model=CLAUDE_MODEL,
    db=db,
    sandbox=sandbox("merge-ready-claude-reviewer"),
    repository=repository,
    permission_mode="bypassPermissions",
)
codex_reviewer = CodexAgent(
    id="merge-ready-codex-reviewer",
    name="Codex Reviewer",
    model=CODEX_MODEL,
    db=db,
    sandbox=sandbox("merge-ready-codex-reviewer"),
    repository=repository,
    sandbox_mode="full-access",
    approval_policy="never",
)
# The engineer that fixes. Swap in a CodexAgent to have Codex fix instead.
fixer = ClaudeAgent(
    id="merge-ready-fixer",
    name="Fixing Engineer",
    model=CLAUDE_MODEL,
    db=db,
    sandbox=sandbox("merge-ready-fixer"),
    repository=repository,
    permission_mode="bypassPermissions",
)


class KeptPoint(BaseModel):
    title: str = Field(..., description="The problem in one sentence")
    location: str = Field(..., description="File and line, or the function")
    raised_by: str = Field(..., description="Claude, Codex or both")
    why_it_matters: str = Field(
        ..., description="What a user of this code would see go wrong"
    )
    fix: str = Field(..., description="What to change, in one or two sentences")


class DroppedPoint(BaseModel):
    title: str
    raised_by: str
    reason: str = Field(
        ...,
        description="Why it is dropped: wrong, not caused by this pull request, or a nitpick",
    )


class Triage(BaseModel):
    kept: List[KeptPoint] = Field(
        default_factory=list, description="Real problems a user would hit"
    )
    dropped: List[DroppedPoint] = Field(default_factory=list)


triage_agent = Agent(
    id="merge-ready-triage",
    name="Review Triage",
    model=OpenAIResponses(id=os.getenv("TRIAGE_MODEL", "gpt-5.6-luna")),
    output_schema=Triage,
    instructions=[
        "You are given a pull request and two independent reviews of it.",
        "Decide which review points must be fixed before the pull request merges.",
        "Keep a point only when all three hold: the diff shows it is true; this pull request causes it; and a person using the code would hit it, as a wrong result, an error, lost data, a security hole or a broken public interface.",
        "Drop everything else and say why: style, naming, wording, missing comments, refactors, 'consider' suggestions, more tests for code that works, and problems that were there before this pull request.",
        "Do not nitpick. When unsure whether a point is real, drop it and say what you could not confirm.",
        "Two reviewers raising the same problem is one point.",
        "An empty kept list means the pull request is merge-ready.",
    ],
)

# ---------------------------------------------------------------------------
# Steps that prepare each brief and record each round
# ---------------------------------------------------------------------------

PULL_REQUEST_URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)")
NEVER_PUBLISH = "Never push, never comment on the pull request and never open a pull request. Your work stays in this checkout."


def github(path: str, accept: str) -> str:
    """Read from the GitHub API. GITHUB_READ_TOKEN is optional and only raises the rate limit for a public repository."""
    headers = {"Accept": accept, "User-Agent": "agno-cookbook"}
    token = os.getenv("GITHUB_READ_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    with urlopen(
        Request("https://api.github.com" + path, headers=headers), timeout=30
    ) as response:
        return response.read().decode("utf-8", errors="replace")


def read_pull_request(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """Read the pull request once, on this host, and keep it for every later step."""
    match = PULL_REQUEST_URL.search(step_input.get_input_as_string() or "")
    if match is None:
        return StepOutput(
            content="Give a GitHub pull request URL, such as https://github.com/owner/name/pull/123.",
            success=False,
            stop=True,
        )
    owner, name, number = match.groups()
    if f"https://github.com/{owner}/{name}".lower() != REPOSITORY_URL.lower():
        return StepOutput(
            content=f"This workflow reviews pull requests of {REPOSITORY_URL} only.",
            success=False,
            stop=True,
        )
    path = f"/repos/{owner}/{name}/pulls/{number}"
    details = json.loads(github(path, "application/vnd.github+json"))
    diff = github(path, "application/vnd.github.v3.diff")
    if len(diff) > DIFF_LIMIT:
        diff = (
            diff[:DIFF_LIMIT]
            + f"\n[The diff is cut here, at {DIFF_LIMIT} characters. Read the rest in the checkout.]"
        )
    run_context.session_state["pull_request"] = {
        "url": match.group(0),
        "number": int(number),
        "title": details["title"],
        "description": (details.get("body") or "")[:4000],
        "base": details["base"]["ref"],
        "head_commit": details["head"]["sha"],
        "diff": diff,
    }
    run_context.session_state["rounds"] = []
    return StepOutput(
        content=f"Read pull request {number}: {details['title']} ({details['head']['sha'][:10]})"
    )


def describe(pr: Dict[str, Any]) -> str:
    return (
        f"Pull request: {pr['url']}\nTitle: {pr['title']}\nBase branch: {pr['base']}\nHead commit: {pr['head_commit']}\n\n"
        f"Description:\n{pr['description'] or '(none)'}\n\nDiff:\n```diff\n{pr['diff']}\n```"
    )


def checkout_steps(pr: Dict[str, Any]) -> str:
    return (
        "Your checkout is in the current directory. Put the pull request's code in it first, unless you did so in an earlier turn:\n"
        f"  git fetch --depth=200 origin {pr['base']} pull/{pr['number']}/head\n"
        f"  git checkout --detach {pr['head_commit']}"
    )


def review_brief(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """What both reviewers are asked this round. From the second round on it carries the fix made so far."""
    state = run_context.session_state
    pr, rounds = state["pull_request"], state["rounds"]
    rounds.append({"round": len(rounds) + 1})
    brief = [
        f"Review this pull request adversarially. This is review round {len(rounds)} of at most {MAX_ROUNDS}.",
        describe(pr),
        checkout_steps(pr),
    ]
    patch = state.get("fix_patch")
    if patch:
        brief.append(
            "After the earlier review round an engineer changed the pull request. Their whole change since the head commit is the "
            "patch below. Save it to a file and apply it with `git apply` on top of the head commit (run `git checkout -- .` first "
            "if an older patch is applied). If it does not apply, read it as text.\n"
            f"```diff\n{patch}\n```"
        )
        brief.append(
            "The problems that change was meant to fix:\n"
            + earlier_points(rounds[:-1])
            + "\nThis round, check two things: that each of those problems is really fixed, and that the engineer's change "
            "broke nothing. Do not go over the rest of the pull request again for smaller points."
        )
    brief.append(
        "Look for what would go wrong for a person using this code: wrong results, errors, lost data, security holes, broken public "
        "interfaces, and cases the change misses. Read the code around the diff and run things in the checkout to prove a point "
        "when you can. Leave out style, naming and wording. For each problem give the file and line, what goes wrong, and how you "
        "know. If you find no real problem, say exactly: No real problems found.\n"
        + NEVER_PUBLISH
    )
    return StepOutput(content="\n\n".join(brief))


def earlier_points(rounds: List[Dict[str, Any]]) -> str:
    """The points triage kept in earlier rounds, one per line."""
    lines = [
        f"- Round {entry['round']}: {point['title']} [{point['location']}]"
        for entry in rounds
        for point in (entry.get("triage") or {}).get("kept") or []
    ]
    return "\n".join(lines) or "- (none)"


def review_text(step_input: StepInput, step_name: str) -> str:
    output = step_input.get_step_output(step_name)
    if output is None:
        return "(no review)"
    if output.success is False:
        return f"(the review failed: {output.error or output.content})"
    return str(output.content or "(empty review)")


def triage_brief(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """Record both reviews and hand them to triage with the pull request."""
    state = run_context.session_state
    current = state["rounds"][-1]
    current["claude_review"] = review_text(step_input, "Claude review")
    current["codex_review"] = review_text(step_input, "Codex review")
    brief = [describe(state["pull_request"])]
    if state.get("fix_patch"):
        brief.append(
            f"Changes an engineer made after earlier review rounds, on top of the diff above:\n```diff\n{state['fix_patch']}\n```"
        )
        brief.append(
            f"This is round {current['round']}. The engineer's changes were meant to fix these points from earlier rounds:\n"
            + earlier_points(state["rounds"][:-1])
            + "\nIn this round keep a point only when one of these holds: an earlier point is still not fixed; the "
            "engineer's changes broke something; or it is a problem you would block the merge on by itself. "
            "A new, smaller point about the original pull request is dropped: the rounds must end."
        )
    brief.append(f"Review by Claude:\n{current['claude_review']}")
    brief.append(f"Review by Codex:\n{current['codex_review']}")
    return StepOutput(content="\n\n".join(brief))


def kept_points(run_context: RunContext) -> List[Dict[str, Any]]:
    rounds = run_context.session_state.get("rounds") or []
    return (rounds[-1].get("triage") or {}).get("kept") or [] if rounds else []


def record_triage(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """Keep what triage decided for this round, so the fix step, the loop and the report can read it."""
    decision = step_input.previous_step_content
    if not isinstance(decision, Triage):
        return StepOutput(
            content=f"Triage returned no decision: {decision}", success=False, stop=True
        )
    run_context.session_state["rounds"][-1]["triage"] = decision.model_dump()
    return StepOutput(
        content=f"Triage kept {len(decision.kept)} and dropped {len(decision.dropped)}."
    )


def fix_needed(step_input: StepInput, run_context: RunContext) -> bool:
    return bool(kept_points(run_context))


def fix_brief(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """What the fixing engineer is asked: the kept points and nothing else."""
    pr = run_context.session_state["pull_request"]
    points = "\n".join(
        f"{index}. {point['title']}\n   Where: {point['location']}\n   Why it matters: {point['why_it_matters']}\n   Fix: {point['fix']}"
        for index, point in enumerate(kept_points(run_context), start=1)
    )
    return StepOutput(
        content=(
            "Fix the review points below in this pull request, and only those. Make the smallest change that fixes each one. "
            "Do not refactor and do not fix anything else.\n\n"
            f"{describe(pr)}\n\n{checkout_steps(pr)}\n\n"
            f"Points to fix:\n{points}\n\n"
            "Do not commit. When you are done, run the tests that cover what you changed if you can, then end your reply with:\n"
            "1. One line per point: what you changed, or why you could not fix it.\n"
            f"2. The exact output of `git diff {pr['head_commit']}` in one ```diff block, complete and unedited. It is handed "
            "to the next reviewers as a patch.\n" + NEVER_PUBLISH
        )
    )


def record_fix(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """Keep the engineer's report and the patch it printed. The patch is the fixer's whole change since the head commit."""
    state = run_context.session_state
    reply = str(step_input.previous_step_content or "")
    patches = re.findall(r"```diff\n(.*?)```", reply, flags=re.DOTALL)
    state["rounds"][-1]["fix_report"] = reply
    if patches:
        state["fix_patch"] = patches[-1]
    return StepOutput(
        content="Recorded the fix."
        if patches
        else "The engineer printed no diff; the fix is not recorded."
    )


def nothing_left_to_fix(outputs: List[StepOutput]) -> bool:
    """End the loop when triage kept nothing this round."""
    for output in outputs:
        if output.step_name == "Triage" and isinstance(output.content, Triage):
            return not output.content.kept
    return False


def report(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """The plain report. The result and each round's triage come first, so a reader who sees only the start has the answer."""
    state = run_context.session_state
    pr, rounds = state["pull_request"], state["rounds"]
    last = (rounds[-1].get("triage") or {}) if rounds else {}
    if rounds and "triage" in rounds[-1] and not last.get("kept"):
        result = (
            f"Merge-ready after {len(rounds)} round(s): the last triage kept nothing."
        )
    else:
        result = f"Not confirmed merge-ready after {len(rounds)} round(s): the last round's fix has not been reviewed."
    if not state.get("fix_patch"):
        result += " No change was made to the pull request."
    lines = [
        f"# Merge-ready report: {pr['title']}",
        f"{pr['url']} at {pr['head_commit'][:10]}",
        f"\n## Result\n{result} Nothing was pushed or posted.",
    ]
    for entry in rounds:
        triage = entry.get("triage") or {}
        lines.append(f"\n## Round {entry['round']}: what triage kept and dropped")
        for point in triage.get("kept") or []:
            lines.append(
                f"- KEPT ({point['raised_by']}): {point['title']} [{point['location']}]. {point['why_it_matters']}"
            )
        for point in triage.get("dropped") or []:
            lines.append(
                f"- Dropped ({point['raised_by']}): {point['title']}. {point['reason']}"
            )
        if not triage.get("kept") and not triage.get("dropped"):
            lines.append("- Neither reviewer raised a point.")
    if state.get("fix_patch"):
        lines.append(
            "\n## Final diff\nEverything the fixing engineer changed on top of the pull request's head commit, as the engineer "
            f"printed it.\n```diff\n{state['fix_patch']}```"
        )
    for entry in rounds:
        lines.append(f"\n## Round {entry['round']} in full")
        lines.append(f"\n### Claude's review\n{entry.get('claude_review', '(none)')}")
        lines.append(f"\n### Codex's review\n{entry.get('codex_review', '(none)')}")
        if entry.get("fix_report"):
            lines.append(
                f"\n### What the fixing engineer reported\n{entry['fix_report']}"
            )
    return StepOutput(content="\n".join(lines))


# ---------------------------------------------------------------------------
# Create the Workflow
# ---------------------------------------------------------------------------

workflow = Workflow(
    id="pr-to-merge-ready",
    name="PR to merge-ready",
    description="Two engineers review a pull request, triage keeps the real problems, one engineer fixes them; at most three rounds.",
    db=db,
    steps=[
        Step(name="Read pull request", executor=read_pull_request),
        Loop(
            name="Review rounds",
            max_iterations=MAX_ROUNDS,
            end_condition=nothing_left_to_fix,
            steps=[
                Step(name="Review brief", executor=review_brief),
                Parallel(
                    Step(name="Claude review", agent=claude_reviewer),
                    Step(name="Codex review", agent=codex_reviewer),
                    name="Independent reviews",
                ),
                Step(name="Triage brief", executor=triage_brief),
                Step(name="Triage", agent=triage_agent),
                Step(name="Record triage", executor=record_triage),
                Condition(
                    name="Fix what triage kept",
                    evaluator=fix_needed,
                    steps=[
                        Step(name="Fix brief", executor=fix_brief),
                        Step(name="Fix", agent=fixer),
                        Step(name="Record fix", executor=record_fix),
                    ],
                ),
            ],
        ),
        Step(name="Report", executor=report),
    ],
)

# ---------------------------------------------------------------------------
# Run the Workflow
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pull_request_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://github.com/agno-agi/agno/pull/11950"
    )
    # Sandboxed engineers run asynchronously.
    result = asyncio.run(workflow.arun(input=pull_request_url))
    print(result.content)
