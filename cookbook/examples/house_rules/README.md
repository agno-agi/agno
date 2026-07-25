# House Rules

Write down the three routing rules your team learned the hard way, then measure what they are worth: the same agent, the same four tickets, before and after the rules land in its knowledge base.

## The claim

A chat app cannot do this because it cannot show you the number. It cannot run your tasks k times with a rule absent, k times with it present, score both with a criterion you wrote, and prove the two runs were comparable.

To be fair about what chat apps can do: you can paste rules into a custom GPT or a project prompt and the answers usually do get better. What you cannot get is 0.25 and 1.00 under an identical environment fingerprint with a per-task diff, which is the difference between feeling that it improved and knowing what each rule bought you.

## Run it

From the repo root, with `OPENAI_API_KEY` set (the only key needed):

```bash
cd cookbook/examples/house_rules
../../../.venvs/demo/bin/python house_rules.py
```

This makes 32 live model calls (4 tasks x k=4, twice) and takes a few minutes.

## What you will see

Observed live, identical across three consecutive runs:

```
pass rate without the rules: 0.25
pass rate with the rules:    1.0

ticket-routing       baseline -> current      (env identical, policy identical)
  big-refund        0/4 -> 4/4    +1.00   improved
  chargeback        0/4 -> 4/4    +1.00   improved
  new-account       0/4 -> 4/4    +1.00   improved
  loud-overcharge   4/4 -> 4/4    +0.00
```

The before rate is not always exactly 0.25: `chargeback` occasionally guesses `fraud` unaided, and one verification run measured 0.3125. The after rate has been 1.0 on every observed run. The `(env identical, policy identical)` header is the point: `diff()` refuses to compare two runs whose environment fingerprints differ, so a printed diff is itself proof that the tasks, the scorer and the prompt were held fixed. The control task `loud-overcharge` stayed 4/4, showing the rules did not break what already worked.

## For production

Keep the pattern, grow the inputs: your real tickets as `Task` rows (or `Task.from_jsonl`), your real acceptance criterion in the `CodeScorer` function, and a larger `k` when you want tighter numbers. When the rules graduate from an experiment to a live knowledge base, back `Knowledge` with a persistent vector store such as PgVector; for the measurement itself, the ephemeral collection is the right tool (see below).

## Known limits

- The environment fingerprint hashes the tasks, the scorer, the tools and every prompt-shaping field. It does not hash `knowledge` or the vector database contents. It proves the prompt, tasks and grader were held fixed; it cannot detect that the knowledge base changed, which in this example is precisely the change you are making on purpose.
- `ChromaDb` here runs in-process and ephemeral (`persistent_client` defaults to `False`). That is deliberate: it is what makes the "before" run honestly empty on every invocation. Pointing this file at a persistent collection would silently destroy the before/after on the second run.
- The before number wobbles with the model's unaided guesses (observed 0.25 to 0.3125 across runs). k=4 is enough to show the effect; raise k if you need the number rather than the direction.
