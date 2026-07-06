# Eval Suite Cookbooks

Suite examples run multiple eval cases as one aggregated suite with tag selection, per-case timeouts, a JSON report, and CI exit codes.

## Files

- `suite_basic.py` - Two cases (judge + reliability checks) run through the built-in `cli()`.
- `suite_team_scoring.py` - A Team run through the suite (the leader delegates to a calculator member and a writer member); reliability sees the members' tool calls, and every answer is graded by a numeric 1-10 judge.

## Usage

```bash
python cookbook/09_evals/suite/suite_basic.py                 # run all cases
python cookbook/09_evals/suite/suite_basic.py --list          # list cases without running
python cookbook/09_evals/suite/suite_basic.py --tag smoke     # run a tagged subset
python cookbook/09_evals/suite/suite_basic.py --name factorial_uses_calculator
python cookbook/09_evals/suite/suite_basic.py --json-output tmp/evals.json
python cookbook/09_evals/suite/suite_basic.py -v              # full run panels per case
```

For programmatic use (CI workflows, embedding), call `run_cases(CASES)` or `await arun_cases(CASES)` instead and read `SuiteResult.to_dict()` - the runner does no console I/O.
