# Filesystem benchmark execution log

## Pilot: all eight storage adapters

**Status:** PASS after correcting benchmark adapters.

**Description:** Ten files, three timed iterations. Real files and real storage
SDKs; mocked provider responses for agent tool dispatch.

**Result:** Initial harness run exposed two adapter issues: Mastra's installed
contained provider requires relative paths, and the Python baseline's text-mode
read normalized CRLF. Both adapters were corrected; affected pilots then passed.
No framework implementation was modified. Pilot timing is excluded from results.

## Main comparison

**Status:** PASS.

**Description:** 100 and 1,000 files, three fresh-process repetitions, 20 timed
samples per operation after three warm-ups. Eight storage configurations and
four native mocked-agent configurations.

**Result:** All 48 jobs completed. All 576 basic contract checks passed, including
the fresh-process persistence checks. The run collected 6,720 direct-operation
latency samples plus 480 mocked-agent samples, excluding warm-ups. Results and
versions are in `results/main/manifest.json` and `RESULTS.md`.

## Agno case-insensitive search edge cases

**Status:** FAIL (reproduced existing backend behavior).

**Description:** Six fixtures per backend: ASCII folding, accented text, Japanese,
Kelvin-sign folding, literal SQL wildcard characters, and absent text.

**Result:** Agno LocalFileSystem passed 6/6. Agno SQLite passed 5/6: query `kelvin`
did not return the file containing `Kelvin`. This is the known ASCII SQL prefilter
gap documented in the current implementation. No framework code was changed.

## Real-model accuracy

**Status:** NOT RUN.

**Description:** Retrieval, missing information, multi-file answers, persistence,
memory updates, citations and token usage under an identical Responses loop.

**Result:** Initial Anthropic access probe returned HTTP 401. User selected OpenAI.
The final OpenAI runner preflight exited with `OPENAI_API_KEY is not configured`;
no task calls were made. Semantic answer/recall accuracy and tokens are unmeasured.

## Harness checks

**Status:** PASS.

**Description:** Scoped Ruff formatting/lint, Node syntax check, and diff whitespace
check. Existing development `.venv` was used for Ruff; benchmarks used an isolated
environment to preserve its dependencies.

**Result:** Scoped checks passed. No full repository test suite, build, PostgreSQL
benchmark, or real-model validation ran.
