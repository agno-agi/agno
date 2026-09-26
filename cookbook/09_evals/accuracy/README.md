# Accuracy Eval Cookbooks

Accuracy examples evaluate how well responses match expected outputs.

## Files

- `accuracy_basic.py` - Sync and async calculator accuracy evaluations.
- `accuracy_9_11_bigger_or_9_99.py` - Numeric comparison accuracy evaluation.
- `accuracy_team.py` - Team language-routing accuracy evaluation.
- `accuracy_with_given_answer.py` - Accuracy scoring for a provided output string.
- `accuracy_with_tools.py` - Accuracy evaluation for a tool-using agent.
- `db_logging.py` - Accuracy evaluation with PostgreSQL result logging.
- `evaluator_agent.py` - Accuracy evaluation using a custom evaluator agent.
- `accuracy_eval_metrics.py` - Eval model metrics accumulated into agent run_output under "eval_model" detail key.
- `jev_accuracy_with_given_answer.py` - Score a paraphrase, an incomplete answer, and a contradiction using Jev.
- `jev_accuracy_async.py` - Score those three categories concurrently with one native async SDK client.
- `jev_accuracy_suite.py` - Generate answers once per case and score them against references through the eval suite.

## Jev accuracy scoring

`JevAccuracyScorer` asks one yes/no question about semantic correctness and
completeness relative to the supplied reference. Equivalent paraphrases are
accepted by the rubric; contradictions and missing essential information are
not. Additional guidelines can require particular wording or formatting.

Install on Python 3.10 or newer, from the repository root:

```sh
pip install -e 'libs/agno[typesafe]'
```

Set `TYPESAFE_API_KEY`. The supplied-answer and async examples only use Jev.
For the suite and the [model introduction](../../90_models/typesafe/accuracy_eval.py),
also install `agno[openai]` and set `OPENAI_API_KEY`.

```python
from agno.run.agent import RunInput, RunOutput
from agno.run.base import RunStatus
from agno.scorer.typesafe import JevAccuracyScorer

scorer = JevAccuracyScorer(pass_threshold=0.8)
run = RunOutput(
    input=RunInput(input_content="What are the refund requirements?"),
    content="Provide your receipt and request the refund within 30 days of purchase.",
    status=RunStatus.completed,
)
score = scorer.score(
    run, expected="Request a refund within 30 days of purchase and provide the receipt."
)
# Async equivalent: score = await scorer.ascore(run, expected=reference)
```

The scorer accepts completed Agent or Team runs with text, JSON-compatible, or
Pydantic content. An expected reference is required. Original input is included
when available; optional `additional_context` supplies supporting material and
`additional_guidelines` accepts a string or list of strings. Reference and
response content are treated as data, not scoring instructions.

- `score.value` is the unchanged correctness probability in `[0, 1]`.
- `score.passed` uses `value >= pass_threshold`. The default **0.8** is a
  starting point to calibrate against your own labeled examples.
- `score.reason` describes the threshold decision; Jev does not generate an explanation.
- `score.detail` retains the threshold and provider metadata, including available
  usage and request ID.

A probability for one answer is not dataset accuracy. Report pass counts across
cases separately; do not label the mean probability as measured accuracy.
Provider errors propagate as scoring errors rather than becoming zero scores.

The scorer uses native sync/async SDK clients. Configure `model`, `api_key`,
`base_url`, or `timeout`, or supply caller-owned `client`/`async_client` instances.
Reuse the scorer across calls. Its `digest()` fingerprints the scoring rule and
configured endpoint while excluding credentials, clients, and runtime state.

Run the examples:

```sh
python cookbook/09_evals/accuracy/jev_accuracy_with_given_answer.py
python cookbook/09_evals/accuracy/jev_accuracy_async.py
python cookbook/09_evals/accuracy/jev_accuracy_suite.py --list
python cookbook/09_evals/accuracy/jev_accuracy_suite.py --tag smoke
python cookbook/09_evals/accuracy/jev_accuracy_suite.py --json-output tmp/jev-evals.json
```

The suite uses `Case(scorer=scorer, expected=...)`, calls the async scorer after
each agent response, and exits nonzero if a case fails. JSON reports contain
`score_value`, `score_passed`, and `score_reason`; full provider metadata remains
on each in-memory `CaseResult.score.detail`.

The CLI displays each correctness probability and threshold decision after the
response, plus a `Score` column in the summary. A `FAIL` with a score below `0.8`
is a threshold decision, not a generated explanation of what was wrong.

This is a custom scorer integration. `AccuracyEval(model=Jev())` remains
unsupported because its evaluator requires a 1–10 integer grade and generated
reasoning. Existing accuracy evaluators and AgentOS eval endpoints are unchanged.
