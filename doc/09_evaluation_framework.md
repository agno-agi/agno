# Evaluation Framework

Agno ships with a built-in evaluation framework for testing and benchmarking agent quality. Run evaluations in CI, before deploying changes, or as part of ongoing monitoring.

**Directory:** `libs/agno/agno/eval/`
**Cookbook:** `cookbook/09_evals/`

---

## Four evaluation types

| Type | Class | Measures |
|------|-------|---------|
| Accuracy | `AccuracyEval` | Semantic correctness of responses (LLM-as-judge) |
| Agent-as-Judge | `AgentAsJudgeEval` | Use a specialised agent to evaluate another agent |
| Performance | `PerformanceEval` | Latency, throughput, time-to-first-token |
| Reliability | `ReliabilityEval` | Consistency, expected tool calls, error rates |

---

## AccuracyEval

**File:** `libs/agno/agno/eval/accuracy.py`
**Cookbook:** `cookbook/09_evals/accuracy/`

Uses a separate **judge model** (typically `o4-mini` or `gpt-4o`) to score how well the agent's response matches the expected output on a scale of 0–10.

### Basic usage

```python
from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

evaluation = AccuracyEval(
    name="Calculator Evaluation",
    model=OpenAIChat(id="o4-mini"),        # judge model
    agent=Agent(
        model=OpenAIChat(id="gpt-4o"),     # agent under test
        tools=[CalculatorTools()],
    ),
    input="What is 10 * 5, then to the power of 2? Do it step by step.",
    expected_output="2500",
    additional_guidelines="Response should include the steps and final answer.",
    num_iterations=3,                      # run 3 times, average the score
)

result: AccuracyResult = evaluation.run(print_results=True)
print(f"Average score: {result.avg_score}/10")
assert result.avg_score >= 8
```

### Async evaluation

```python
import asyncio

result = asyncio.run(evaluation.arun(print_results=True))
```

### Multiple test cases

```python
test_cases = [
    AccuracyEval(
        model=OpenAIChat(id="o4-mini"),
        agent=my_agent,
        input=question,
        expected_output=answer,
        num_iterations=2,
    )
    for question, answer in [
        ("What is the capital of France?", "Paris"),
        ("Who wrote Hamlet?", "William Shakespeare"),
        ("What is 7 * 8?", "56"),
    ]
]

results = [eval.run() for eval in test_cases]
passing = sum(1 for r in results if r.avg_score >= 7)
print(f"Passed: {passing}/{len(results)}")
```

### With tool use

```python
from agno.eval.accuracy import AccuracyEval

evaluation = AccuracyEval(
    model=OpenAIChat(id="o4-mini"),
    agent=Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[DuckDuckGoTools()],
    ),
    input="What is the current Python version?",
    expected_output="The latest stable Python version",
    additional_guidelines=(
        "The agent must search the web and return the correct version number. "
        "Accept any response that correctly identifies the latest stable release."
    ),
)
```

### With a given answer (reference answer)

When you have a ground-truth answer to compare against:

```python
from agno.eval.accuracy import AccuracyEval

eval = AccuracyEval(
    model=OpenAIChat(id="o4-mini"),
    agent=my_agent,
    input="What are the main causes of inflation?",
    expected_output="Demand-pull inflation, cost-push inflation, built-in inflation",
    additional_guidelines="Award full marks if all three types are mentioned accurately.",
    num_iterations=1,
)
```

### AccuracyResult fields

```python
result: AccuracyResult

result.avg_score          # float 0-10, average across num_iterations
result.scores             # list[float] — one per iteration
result.run_results        # full RunResponse for each iteration
result.name               # evaluation name
```

---

## AgentAsJudgeEval

**File:** `libs/agno/agno/eval/agent_as_judge.py`
**Cookbook:** `cookbook/09_evals/agent_as_judge/`

Use a specialised evaluator agent to judge responses. More flexible than `AccuracyEval` because you can give the judge agent specific expertise, tools, and instructions.

```python
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.agent import Agent
from agno.models.openai import OpenAIChat

judge_agent = Agent(
    name="Code Quality Judge",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a senior software engineer evaluating code quality.",
        "Score on: correctness (0-4), readability (0-3), efficiency (0-3).",
        "Return a total score out of 10 with detailed justification.",
    ],
)

eval = AgentAsJudgeEval(
    judge=judge_agent,
    agent=Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[CodingTools()],
    ),
    input="Write a Python function to find all prime numbers up to N using the Sieve of Eratosthenes.",
    expected_output="A correct, readable implementation of the Sieve of Eratosthenes",
    num_iterations=2,
)

result = eval.run(print_results=True)
```

---

## PerformanceEval

**File:** `libs/agno/agno/eval/performance.py`
**Cookbook:** `cookbook/09_evals/performance/`

Measures execution speed and resource usage — not response quality.

```python
from agno.eval.performance import PerformanceEval
from agno.agent import Agent
from agno.models.openai import OpenAIChat

perf_eval = PerformanceEval(
    agent=Agent(model=OpenAIChat(id="gpt-4o")),
    input="Explain quantum entanglement in simple terms.",
    num_iterations=5,
)

result = perf_eval.run(print_results=True)
print(f"Average latency:          {result.avg_latency_ms:.0f}ms")
print(f"Time to first token:      {result.avg_ttft_ms:.0f}ms")
print(f"Average input tokens:     {result.avg_input_tokens}")
print(f"Average output tokens:    {result.avg_output_tokens}")
print(f"Average cost per run:     ${result.avg_cost:.4f}")
```

### Performance regression testing

```python
# Ensure response time stays under 3 seconds
result = perf_eval.run()
assert result.avg_latency_ms < 3000, f"Too slow: {result.avg_latency_ms}ms"
```

---

## ReliabilityEval

**File:** `libs/agno/agno/eval/reliability.py`
**Cookbook:** `cookbook/09_evals/reliability/`

Checks whether the agent behaves consistently and calls the expected tools.

```python
from agno.eval.reliability import ReliabilityEval
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools

reliability_eval = ReliabilityEval(
    agent=Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[YFinanceTools(stock_price=True)],
    ),
    input="What is Apple's current stock price?",
    expected_tool_calls=["get_stock_price"],   # must call this tool
    num_iterations=5,
)

result = reliability_eval.run(print_results=True)
print(f"Tool call success rate: {result.tool_call_success_rate:.0%}")
print(f"Error rate:             {result.error_rate:.0%}")
```

---

## Combining evaluations in CI

```python
import sys
from agno.eval.accuracy import AccuracyEval
from agno.eval.performance import PerformanceEval

def run_eval_suite(agent):
    accuracy = AccuracyEval(
        model=OpenAIChat(id="o4-mini"),
        agent=agent,
        input="What is 2+2?",
        expected_output="4",
        num_iterations=3,
    ).run()

    performance = PerformanceEval(
        agent=agent,
        input="Summarise this sentence in one word: 'The sky is blue.'",
        num_iterations=5,
    ).run()

    failures = []
    if accuracy.avg_score < 8:
        failures.append(f"Accuracy too low: {accuracy.avg_score:.1f}/10")
    if performance.avg_latency_ms > 5000:
        failures.append(f"Too slow: {performance.avg_latency_ms:.0f}ms")

    if failures:
        print("EVALUATION FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All evaluations passed.")

run_eval_suite(my_agent)
```

---

## Logging evaluation results to a database

```python
from agno.eval.accuracy import AccuracyEval
from agno.db.postgres import PostgresDb

eval = AccuracyEval(
    model=OpenAIChat(id="o4-mini"),
    agent=my_agent,
    input="...",
    expected_output="...",
    db=PostgresDb(table_name="eval_runs", db_url=DB_URL),  # persist results
)
result = eval.run()
```

---

## Summary

| Evaluator | Key metric | Typical judge model |
|-----------|-----------|---------------------|
| `AccuracyEval` | `avg_score` (0–10) | `o4-mini` |
| `AgentAsJudgeEval` | `avg_score` (0–10) | Custom agent |
| `PerformanceEval` | `avg_latency_ms` | N/A |
| `ReliabilityEval` | `tool_call_success_rate` | N/A |
