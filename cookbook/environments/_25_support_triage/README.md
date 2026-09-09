# Support Triage

Route tickets by active impact, precedence, and requested action. Quoted,
hypothetical, negated, and resolved issues must not steal the queue.

## Files

- `basic.py` — applies a queue precedence ladder to mixed tickets.
- `precedence_rules.py` — derives queue, severity, and response target together.
- `ambiguous_tickets.py` — separates the requested action from safety overrides.

## When to use

Use this pattern when production routing rules are explicit enough to encode in
the policy and verify as typed fields. Include multi-issue and non-operative
evidence: clean one-intent tickets commonly produce a useless full grid.

This follows typed reconciliation in
[`_24_structured_extraction/`](../_24_structured_extraction/). Continue to
[`_26_multi_step_tools/`](../_26_multi_step_tools/) when successful routing
depends on a sequence of read-only tool executions.

## Run

```bash
python cookbook/environments/_25_support_triage/basic.py
python cookbook/environments/_25_support_triage/precedence_rules.py
python cookbook/environments/_25_support_triage/ambiguous_tickets.py
```

Requires `OPENAI_API_KEY`. Every model call uses `OpenAIResponses` with
`gpt-5.5`.
