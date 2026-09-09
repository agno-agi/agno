"""
Code Fixes - Basic
==================

Choose a constrained patch for a subtle bug, then score the patch id. Closed
choices keep verification deterministic without executing model-written code.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class FixChoice(BaseModel):
    patch_id: str = Field(description="The single selected patch id")
    test_ids: list[str] = Field(
        description="Minimal regression-test ids in lexical order"
    )
    reason: str = Field(description="Why it satisfies every stated constraint")


def patch_matches(run, expected) -> bool:
    return (
        isinstance(run.content, FixChoice)
        and run.content.patch_id == expected["patch_id"]
        and run.content.test_ids == expected["test_ids"]
    )


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=FixChoice,
    instructions=(
        "Act as a Python maintainer. Select exactly one listed patch. Prefer the "
        "smallest patch that satisfies every stated invariant. Also select the "
        "smallest listed regression-test set covering every named invariant. Return "
        "test ids in lexical order; do not invent code or tests."
    ),
)

environment = Environment(
    name="safe-code-fix-selection",
    agent=agent,
    tasks=(
        Task(
            id="shared-task-cancellation",
            input=(
                "A cache stores one asyncio.Task per key. Callers return `await task`. "
                "One cancelled waiter currently cancels the shared load, and failed "
                "loads poison the cache. Successful loads must remain cached; a caller "
                "cancellation must not cancel the shared task; a failed or cancelled "
                "shared task must be removed for retry. Choose: A=`await shield(task)` "
                "only. B=shield and pop in `finally`. C=attach a done callback that "
                "pops only when `done.cancelled()` or `done.exception() is not None`, "
                "then await `shield(task)`. D=catch `Exception`, pop, then await task. "
                "Tests: T1=cancel one waiter while another receives the value and a "
                "later call reuses it; T2=failed owner wakes all waiters and the next "
                "call retries; T3=single successful caller; T4=different keys overlap; "
                "T5=cancel the shared task itself, verify every waiter observes "
                "cancellation, then verify the next call retries."
            ),
            expected={"patch_id": "C", "test_ids": ["T1", "T2", "T5"]},
        ),
        Task(
            id="race-safe-path-open",
            input=(
                "Linux 5.6+ service opens an untrusted relative path below an already "
                "opened root directory. Intermediate symlinks may change concurrently. "
                "Relative symlinks that remain below root are allowed, but escaping "
                "root and procfs-style magic links must be impossible without a "
                "check-then-open race. Choose: A=`Path.resolve()`, verify "
                "`is_relative_to(root)`, then ordinary open. B=`os.open` with "
                "`dir_fd=root_fd|O_NOFOLLOW` on the final component. C=Linux `openat2` "
                "relative to root_fd with `RESOLVE_BENEATH|RESOLVE_NO_MAGICLINKS`. "
                "D=`openat2` with `RESOLVE_NO_SYMLINKS`, rejecting even safe internal "
                "relative symlinks. Tests: T1=racing intermediate symlink cannot "
                "escape; T2=safe internal relative symlink still opens; T3=procfs magic "
                "link is rejected; T4=ordinary file opens."
            ),
            expected={"patch_id": "C", "test_ids": ["T1", "T2", "T3", "T4"]},
        ),
        Task(
            id="dst-fold-timeline",
            input=(
                "`start` is 2026-11-01 01:30 in America/New_York with `fold=0`. "
                "Return an aware datetime in the same zone exactly 3600 elapsed seconds "
                "later; wall-clock addition must not skip the repeated hour. Choose: "
                "A=`start + timedelta(hours=1)`. B=`datetime.fromtimestamp("
                "start.timestamp() + 3600, start.tzinfo)`. C=`start.replace(fold=1) + "
                "timedelta(hours=1)`. D=strip tzinfo, add an hour, then reattach it. "
                "Tests: T1=assert timestamp delta is 3600, local result is 01:30 with "
                "fold=1, and tzinfo remains America/New_York; T2=ordinary noon plus one "
                "hour; T3=naive input raises; T4=spring-forward day."
            ),
            expected={"patch_id": "B", "test_ids": ["T1"]},
        ),
        Task(
            id="canonical-caseless-key",
            input=(
                "A user-id key must make canonically equivalent Unicode spellings and "
                "case variants compare equal, including multi-character case folds, "
                "but must preserve compatibility distinctions such as circled 1 versus "
                "ASCII 1 and fullwidth A versus ASCII A. Choose: A=`s.lower()`. "
                "B=`NFC(s).casefold()`. C=`NFC(NFD(s).casefold())`. "
                "D=`NFKC(s).casefold()`. Tests: T1=composed é equals decomposed "
                "e+combining-acute; T2=Straße equals STRASSE; T3=circled 1 differs "
                "from 1 and fullwidth A differs from A; T4=ASCII mixed case matches."
            ),
            expected={"patch_id": "C", "test_ids": ["T1", "T2", "T3"]},
        ),
        Task(
            id="weakref-finalizer-capture",
            input=(
                "`weakref.finalize(resource, resource.close)` never fires because the "
                "bound callback strongly retains the resource. The OS fd must close "
                "when the last reference disappears, explicit close must remain "
                "idempotent with no later double-close, and the finalizer must not "
                "capture the resource. Choose: A=use a lambda closing resource. "
                "B=use `weakref.proxy(resource).close`. C=capture only the integer fd "
                "in `finalize(resource, os.close, fd)` and have explicit close invoke "
                "that finalizer once. D=replace it with `resource.__del__`. Tests: "
                "T1=drop last reference and observe one fd close; T2=explicit close "
                "then GC still closes once; T3=inspect callback references and find no "
                "resource; T4=ordinary construction leaves fd open."
            ),
            expected={"patch_id": "C", "test_ids": ["T1", "T2", "T3"]},
        ),
    ),
    scorer=CodeScorer(patch_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=6, concurrency=6)
    print(results)
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
