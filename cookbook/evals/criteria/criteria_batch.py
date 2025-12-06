"""Batch CriteriaEval usage example."""

from typing import Optional

from agno.eval.criteria import CriteriaEval, CriteriaResult
from agno.models.openai import OpenAIChat

evaluation = CriteriaEval(
    name="Geography Knowledge",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be accurate and complete",
    threshold=7,
    num_iterations=2,
)

result: Optional[CriteriaResult] = evaluation.run_batch(
    cases=[
        {"input": "What is the capital of France?", "output": "Paris"},
        {"input": "What is the capital of Japan?", "output": "Tokyo"},
        {"input": "What is the capital of Brazil?", "output": "Brasília"},
    ],
    print_results=True,
    print_summary=True,
)
assert result is not None, "Evaluation should return a result"
