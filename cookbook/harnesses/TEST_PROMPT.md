# Reproduce the harness cookbook checks

Run from the repository root. Record the source commit (including whether the
tree is dirty), imported Agno path, Python, SDK/CLI versions, model IDs and auth
method in the test logs. Never record credential values or private transcripts.

## 1. Static checks

Use the development environment:

```bash
source .venv/bin/activate
python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/harnesses/claude
python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/harnesses/codex
python -m compileall -q cookbook/harnesses
ruff check cookbook/harnesses libs/agno/tests/integration/agents/test_harness_cookbooks.py
```

The pattern checker targets runnable agent examples, not the shipping source
fixture. Importing an example must not start a model call or HTTP server.

## 2. Adapter API regressions

```bash
python -m pytest libs/agno/tests/unit/agents -q
```

These cover keyword-only constructors, configuration overrides, media input
validation, sync/async printers and stored/API metadata. With mypy installed,
the suite also checks inferred return types and rejects positional construction.
The runtime constructor tests also run on Python 3.9 without native SDKs; this
does not imply the native SDK packages support that Python version.

## 3. Live scripts, one provider at a time

Follow the provider README, then run `basic.py`, `native_sdk.py` and `tools.py`
individually. Check:

- Basic and SDK examples both answer the inclusive threshold question with zero shipping.
- Native and wrapped examples use the same prompt/model; compare their result objects and IDs.
- Tools emit started/completed events and include real fixture contents.
- The final explanation covers `small=8`, `boundary=0` and `large=0`.
- All runs complete successfully and the fixture is unchanged.
- An invalid model makes the script exit unsuccessfully, not print a false pass.
  Claude uses a literal model ID: temporarily edit it for this check and restore
  it afterward; there is no `CLAUDE_MODEL` environment override.

Do not judge success by exact prose or response speed. Keep failed attempts in
the log. Do not retry silently; classify authentication, environment, provider,
example or adapter failure before rerunning.

## 4. Live HTTP acceptance

Install pytest and pytest-asyncio (required by the repository's integration
fixtures) in the same environment as the examples. The integration tests
launch the actual `agent_os.py` servers, on separate loopback ports with
temporary SQLite directories. They make real model calls; they are skipped
unless explicitly enabled.

```bash
uv pip install pytest pytest-asyncio
AGNO_TEST_CLAUDE_SDK=1 python -m pytest \
  libs/agno/tests/integration/agents/test_harness_cookbooks.py -k claude -q
AGNO_TEST_CODEX_SDK=1 python -m pytest \
  libs/agno/tests/integration/agents/test_harness_cookbooks.py -k codex -q
```

Each provider has three script cases and an HTTP case with two model runs.
Claude also has a case that reuses the native SDK options directly in Agno.
Enable both flags to run all nine cases. Allow several minutes;
a script exceeding 180 seconds or HTTP read exceeding 120 seconds fails.
The native examples also enforce a 120-second total wait.

The HTTP case checks health and agent discovery, then non-streaming and SSE
tool runs. It retrieves both terminal runs through the API and verifies stored
tool results. It saves server output, event JSON and persisted results under
pytest's temporary directory. With `--basetemp`, choose a disposable directory:
pytest clears it. Do not put credentials in prompts or fixture files.

This does not close the stream early, kill a worker, restart the server, verify
native resume, or exercise production authorization. Do not label it as a
disconnect, recovery or multi-replica test.

Interactive servers must not be included in an unattended recursive cookbook
runner. Use the explicit script list or this lifecycle-managed test suite.

## 5. Submission gates

Run the repository-required checks in the development environment:

```bash
./scripts/format.sh
./scripts/validate.sh
git diff --check
```

Keep formatting changes scoped to this PR. Update each provider's TEST_LOG and
the root summary with commands, versions, observed results, failures and limits.
A skipped live test is unverified, not a pass.
