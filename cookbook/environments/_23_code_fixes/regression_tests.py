"""
Code Fixes - Regression Tests
=============================

Choose the smallest exact test set that proves a patch fixes the reported bug
without weakening a neighboring invariant.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class TestSelection(BaseModel):
    test_ids: list[str] = Field(description="Selected test ids in lexical order")
    reason: str


def tests_match(run, expected) -> bool:
    return isinstance(run.content, TestSelection) and run.content.test_ids == expected


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=TestSelection,
    instructions=(
        "Select the smallest listed regression-test set that fails before the patch, "
        "passes after it, and directly protects every named neighboring invariant. "
        "Return test ids in lexical order and do not add general smoke tests."
    ),
)

environment = Environment(
    name="minimal-regression-tests",
    agent=agent,
    tasks=(
        Task(
            id="cursor-boundary-tests",
            input=(
                "Patch adds a `(created_at,id)` cursor to stop skipping equal-time "
                "rows. Protect both boundary completeness and absence of duplicates "
                "when a row is inserted after page one. Candidates: T1=two rows share "
                "the boundary timestamp; T2=insert a later-id row at that same timestamp "
                "between pages; T3=empty table; T4=page size validation. Select the "
                "smallest exact set."
            ),
            expected=["T1", "T2"],
        ),
        Task(
            id="single-flight-tests",
            input=(
                "Patch introduces a Future placeholder. Protect same-key deduplication, "
                "different-key concurrency, and retry after an owner exception. "
                "Candidates: T1=ten callers same key invoke compute once; T2=two keys "
                "overlap in time; T3=failed owner wakes both waiters and next call "
                "recomputes; T4=one successful call; T5=cache length after success. "
                "Select the smallest exact set."
            ),
            expected=["T1", "T2", "T3"],
        ),
        Task(
            id="atomic-write-tests",
            input=(
                "Patch moves temp creation beside the destination. Protect cross-device "
                "publish and cleanup without adding redundant happy-path coverage. "
                "Candidates: T1=mock `/tmp` and target with different device ids and "
                "assert replace receives same-filesystem paths; T2=force replace failure "
                "and assert temp removal; T3=ordinary successful write; T4=permission "
                "error opening the final file; T5=reader sees old or new full content, "
                "never a partial copy. Select the smallest set that covers the named "
                "cross-device, cleanup, and atomic-reader invariants."
            ),
            expected=["T1", "T2", "T5"],
        ),
        Task(
            id="overlapping-coverage",
            input=(
                "A concurrency repair has 20 required regression invariants I1-I20. "
                "Select the unique smallest candidate-test set whose union covers all "
                "20; extra tests fail review. Coverage: T01={I3,I6,I7,I11}; "
                "T02={I5,I7,I9,I13,I18}; T03={I3,I7,I9,I10}; "
                "T04={I1,I7,I11,I16}; T05={I2,I3,I4,I13,I19}; "
                "T06={I2,I11,I12,I16,I17}; "
                "T07={I6,I8,I10,I11,I12,I14,I18}; "
                "T08={I7,I8,I12,I13,I18}; T09={I1,I5,I6,I19}; "
                "T10={I1,I12,I15,I17,I18}; T11={I6,I7,I8,I12,I20}; "
                "T12={I3,I11,I18,I20}; T13={I4,I9,I17,I18,I19}; "
                "T14={I2,I7,I10,I13,I16}; T15={I2,I14,I15,I17}; "
                "T16={I2,I3,I4,I7,I11,I17}; "
                "T17={I1,I7,I11,I13,I19,I20}; T18={I3,I12,I16,I20}; "
                "T19={I7,I8,I18,I19,I20}; T20={I2,I9,I11,I14}; "
                "T21={I1,I12,I14,I19}; T22={I3,I13,I16,I17,I18}; "
                "T23={I5,I6,I7,I14}; T24={I1,I4,I5,I20}; "
                "T25={I13,I17,I18,I19}."
            ),
            expected=["T02", "T05", "T07", "T10", "T18"],
        ),
    ),
    scorer=CodeScorer(tests_match),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=8, concurrency=6)
    print(results)
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
