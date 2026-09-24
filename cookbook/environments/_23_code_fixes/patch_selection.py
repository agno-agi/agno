"""
Code Fixes - Patch Selection
============================

Select between patches that all fix the visible symptom but differ on
concurrency, failure, or compatibility guarantees.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class PatchChoice(BaseModel):
    patch_id: str = Field(description="The selected patch id")
    runner_up_id: str = Field(description="The closest rejected patch id")
    rejected_risk: str = Field(description="The key risk in the closest alternative")


def patch_matches(run, expected) -> bool:
    return (
        isinstance(run.content, PatchChoice)
        and run.content.patch_id == expected["patch_id"]
        and run.content.runner_up_id == expected["runner_up_id"]
    )


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=PatchChoice,
    instructions=(
        "Review the constraints as a senior Python maintainer. Select one patch id "
        "from the prompt and identify the closest rejected alternative. Closest means "
        "the option violating the fewest stated invariants; break a tie by the earlier "
        "patch id."
    ),
)

environment = Environment(
    name="competing-patch-selection",
    agent=agent,
    tasks=(
        Task(
            id="single-flight-cache",
            input=(
                "`cache.setdefault(key, compute(key))` runs compute more than once. "
                "Requirements: one in-flight computation per key; different keys run "
                "concurrently; compute may recursively request a different key; all "
                "same-key waiters receive the same value or exception; an exception is "
                "not cached and the next call retries; synchronization state for a "
                "failed never-reused key must not remain forever. Choose: A=global Lock around "
                "compute. B=per-key Lock stored forever. C=under a short lock install a "
                "per-key Future placeholder, let the owner compute outside the lock, "
                "publish value/exception to waiters, and remove the placeholder after "
                "failure. D=keep setdefault but memoize compute with lru_cache."
            ),
            expected={"patch_id": "C", "runner_up_id": "B"},
        ),
        Task(
            id="stream-timeout",
            input=(
                "A wrapper calls `await wait_for(anext(shared_stream), 0.1)`. Timeout "
                "cancels the stream's `__anext__`, corrupting the shared iterator. A "
                "timed-out read must remain pending for the next caller, only one "
                "`__anext__` may be active, and closing the wrapper must cancel it. "
                "Choose: A=shield `anext` inline on every call. B=create one pending "
                "Task, await it through `wait_for(shield(task))`, retain it after "
                "timeout, clear it after completion, cancel it on close. C=catch timeout "
                "and immediately call `anext` again. D=replace wait_for with sleep."
            ),
            expected={"patch_id": "B", "runner_up_id": "A"},
        ),
        Task(
            id="conditional-update",
            input=(
                "An HTTP update uses `if if_match and if_match != current_etag: 412`. "
                "The API contract says a missing If-Match means unconditional update, "
                "but a present empty or malformed value must fail precondition; `*` "
                "matches any existing record. Choose: A=use `if_match is not None`, "
                "handle `*`, otherwise compare exactly. B=use `if bool(if_match)`. "
                "C=strip and treat empty as missing. D=always require equality, making "
                "the header mandatory."
            ),
            expected={"patch_id": "A", "runner_up_id": "B"},
        ),
        Task(
            id="nested-exception-group",
            input=(
                "A TaskGroup may raise a nested ExceptionGroup containing transient "
                "and fatal leaves. Every TransientError leaf must be enqueued once for "
                "retry; all unmatched fatal leaves must propagate with subgroup shape "
                "and tracebacks preserved. Choose: A=catch ExceptionGroup, recursively "
                "walk and enqueue transient leaves, then raise a newly flattened fatal "
                "group. B=use `except* TransientError "
                "as group` to recursively enqueue its transient leaves, followed by "
                "`except* BaseException: raise` so unmatched subgroups propagate. "
                "C=use `contextlib.suppress(TransientError)`. D=catch Exception and "
                "retry the whole original group."
            ),
            expected={"patch_id": "B", "runner_up_id": "A"},
        ),
        Task(
            id="float-cache-key",
            input=(
                "A numeric cache must preserve every finite IEEE-754 float distinction "
                "including +0.0 versus -0.0, but deliberately map all NaN payloads and "
                "NaN signs to one key. Choose: A=`lru_cache(typed=True)` on the float. "
                "B=use `(type(x), x)`. C=if `math.isnan(x)` return a fixed NaN sentinel "
                "key, otherwise key on `x.hex()`. D=key on the raw eight bytes for "
                "every float."
            ),
            expected={"patch_id": "C", "runner_up_id": "D"},
        ),
    ),
    scorer=CodeScorer(patch_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=6, concurrency=6)
    print(results)
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
