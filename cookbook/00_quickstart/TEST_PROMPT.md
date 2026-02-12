# Prompt: Improve Agno Test Suite

You are improving the test suite for the **Agno** AI agent framework. Your primary goal is to **eliminate flaky tests** (mostly caused by API rate limits in integration tests) and **add new unit tests** for coverage gaps.

---

## Environment Setup

Run these commands at the start of every session, in order:

```bash
# 1. Load environment variables (API keys, etc.)
direnv allow
eval "$(direnv export bash 2>/dev/null)"

# 2. Activate the test virtual environment
source .venv/bin/activate

# 3. If .venv doesn't exist, create it first:
#    ./scripts/test_setup.sh

# 4. Install any missing libraries as needed:
#    uv pip install <package>
```

---

## Running Tests

```bash
# Full unit test suite with coverage
./scripts/test.sh

# Single subdirectory
pytest libs/agno/tests/unit/<subdir> -v

# Single file
pytest libs/agno/tests/unit/<path>/test_file.py -v

# Single test
pytest libs/agno/tests/unit/<path>/test_file.py::TestClass::test_name -v

# With output visible
pytest ... -s

# Stop on first failure
pytest ... -x

# Integration tests (require API keys via direnv)
pytest libs/agno/tests/integration/<subdir> -v

# Coverage for a specific module
pytest libs/agno/tests/unit/<subdir> --cov=libs/agno/agno/<module> --cov-report=term-missing -v
```

---

## Test Suite Structure

```
libs/agno/tests/
├── unit/           # ~240 files, fully mocked, no real API calls
├── integration/    # ~360 files, real API calls, real databases
└── system/         # ~24 files, end-to-end with running services
```

**Pytest config** is in `libs/agno/pyproject.toml`:
```toml
[tool.pytest.ini_options]
log_cli = true
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

**Key fixtures** live in:
- `libs/agno/tests/integration/conftest.py` — shared DB fixtures, async client reset
- `libs/agno/tests/unit/*/conftest.py` — per-module fixtures

---

## The Flakiness Problem

**Root cause:** Integration tests make real API calls to 35+ LLM providers. Rate limits (HTTP 429) cause intermittent failures that are NOT bugs in the code.

### Current State of Rate Limit Protection

**Only 4 out of 35 model providers have rate-limit protection:**
- `libs/agno/tests/integration/models/google/conftest.py`
- `libs/agno/tests/integration/models/groq/conftest.py`
- `libs/agno/tests/integration/models/cerebras/conftest.py`
- `libs/agno/tests/integration/models/sambanova/conftest.py`

**31 providers have ZERO protection**, including the most heavily used ones: OpenAI, Anthropic, Azure, AWS, Meta, Deepseek, Mistral, Cohere, xAI, etc.

The protection pattern is a `conftest.py` pytest hook that converts rate-limit failures into skips:

```python
import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Skip tests that hit <Provider> rate limits (429) instead of failing."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        if call.excinfo is not None:
            error_msg = str(call.excinfo.value)
            full_repr = str(report.longrepr) if report.longrepr else ""
            sections_text = " ".join(content for _, content in report.sections)
            combined = (error_msg + full_repr + sections_text).lower()
            if any(p in combined for p in ["429", "rate limit", "rate_limit", "quota", "resource_exhausted"]):
                report.outcome = "skipped"
                report.longrepr = ("", -1, "Skipped: <Provider> rate limit (429)")
```

### Additional Issue: No Retry/Backoff on Most Tests

Google integration tests configure retry/backoff on the Agent:
```python
agent = Agent(
    model=Gemini(id="gemini-2.0-flash"),
    exponential_backoff=True,
    delay_between_retries=5,
)
```

But OpenAI, Anthropic, and most other provider tests do NOT:
```python
# No backoff — a single 429 = test failure
agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), telemetry=False)
```

---

## Task 1: Add Rate-Limit Protection to All Integration Model Tests

**For every provider directory under `libs/agno/tests/integration/models/` that does NOT already have a `conftest.py` with the rate-limit hook**, create one.

The full list of provider directories to check:
```
aimlapi, anthropic, aws, azure, cerebras*, cohere, cometapi, dashscope,
deepinfra, deepseek, fireworks, google*, groq*, huggingface, ibm, langdb,
litellm, litellm_openai, lmstudio, meta, mistral, nebius, nvidia, ollama,
openai, openrouter, perplexity, portkey, sambanova*, together, vercel,
vertexai, vllm, xai

(* = already has protection)
```

**For each unprotected directory:**

1. Check if a `conftest.py` already exists in that directory
2. If it exists, ADD the `pytest_runtest_makereport` hook to it (don't overwrite existing fixtures)
3. If it doesn't exist, CREATE a new `conftest.py` with just the hook
4. Use the provider name in the skip message (e.g., `"Skipped: OpenAI rate limit (429)"`)

**Also add the hook to these non-model integration test directories** that make real API calls:
- `libs/agno/tests/integration/agent/` (uses OpenAI)
- `libs/agno/tests/integration/teams/` (uses OpenAI)
- `libs/agno/tests/integration/workflows/` (uses OpenAI)
- `libs/agno/tests/integration/embedder/` (uses OpenAI)
- `libs/agno/tests/integration/reranker/`

For these, use a generic message: `"Skipped: rate limit (429)"`.

---

## Task 2: Add Retry/Backoff to Integration Tests That Lack It

For integration tests that create real Agent instances without retry config, add `retries` and `exponential_backoff`:

**Before:**
```python
agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), telemetry=False)
```

**After:**
```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    retries=3,
    delay_between_retries=2,
    exponential_backoff=True,
    telemetry=False,
)
```

**Scope:** Apply this to tests under:
- `libs/agno/tests/integration/models/openai/`
- `libs/agno/tests/integration/models/anthropic/`
- `libs/agno/tests/integration/models/azure/`
- `libs/agno/tests/integration/models/aws/`
- `libs/agno/tests/integration/models/deepseek/`
- `libs/agno/tests/integration/models/mistral/`
- `libs/agno/tests/integration/models/cohere/`
- `libs/agno/tests/integration/models/xai/`
- `libs/agno/tests/integration/models/together/`
- `libs/agno/tests/integration/models/meta/`
- Any other provider tests that instantiate Agents without retry config
- `libs/agno/tests/integration/agent/` (all agent integration tests)
- `libs/agno/tests/integration/teams/` (all team integration tests)
- `libs/agno/tests/integration/workflows/` (all workflow integration tests)

**Use fixtures where possible.** If a file already has a model fixture like:
```python
@pytest.fixture(scope="module")
def openai_model():
    return OpenAIChat(id="gpt-4o-mini")
```

Then add retry config to the Agent creation, not the model fixture. The Agent-level config is preferred.

**For tests that create Agents inline** (not via fixture), add the retry params directly.

**Do NOT add retries to:**
- Tests that specifically test error handling (e.g., `test_exception_handling`)
- Tests that explicitly test retry behavior (e.g., `test_retries.py`)
- Unit tests (they're all mocked)

---

## Task 3: Fix or Remove Genuinely Flaky Unit Tests

Run the full unit test suite and fix any failures:

```bash
pytest libs/agno/tests/unit/ -v 2>&1
```

**IMPORTANT: Only modify test files, not production code in `libs/agno/agno/`.**

### Known Failure Patterns (fix these first)

**1. Environment variable leaking into default arguments**

A tool class uses `getenv("SOME_KEY")` as a default parameter value in `__init__`. Default args are evaluated at import time, so any value set by direnv gets baked in permanently. Tests that manipulate `os.environ` at runtime can't override it.

Example: `libs/agno/agno/tools/jina.py`:
```python
def __init__(self, api_key: Optional[str] = getenv("JINA_API_KEY"), ...):
```

Fix: In the test, pass the value explicitly and don't rely on the default. Or use `monkeypatch.setattr` to patch the module-level default before construction. Or use `monkeypatch.delenv` / `monkeypatch.setenv` combined with re-importing.

Known files: `libs/agno/tests/unit/tools/test_jina.py`

**2. `time.time` mock exhaustion (StopIteration)**

Tests mock `time.time` with `side_effect=[list of values]`, but Python's `logging` module calls `time.time()` internally in `LogRecord.__init__`. These hidden calls consume values from the mock, causing `StopIteration`.

Fix: Use a callable that never exhausts instead of a finite list:
```python
# Instead of: mock_time.side_effect = [0, 0, 1, 2, 3, 4, 5, 6]
# Use:
call_count = 0
def fake_time():
    nonlocal call_count
    call_count += 1
    return call_count * 0.5

mock_time.side_effect = fake_time
```

Or use `itertools.count()` or a generator that never exhausts.

Known files: `libs/agno/tests/unit/tools/test_opencv.py`

**3. Patching the class being tested (no-op patches)**

Tests do `with patch("agno.tools.jina.JinaReaderTools"):` but then call `JinaReaderTools()` using the already-imported reference. This patch does nothing useful.

Fix: Remove these no-op patches entirely.

Known files: `libs/agno/tests/unit/tools/test_jina.py`

**4. Rate limit / network issues in unit tests**

Tests making real HTTP calls may fail due to rate limits or network issues.

Fix: Ensure all external calls are properly mocked. Unit tests should never hit the network.

### General Flakiness Patterns

| Pattern | Fix |
|---------|-----|
| Tests that depend on execution order | Add proper fixtures / setup |
| Tests with hardcoded file paths | Use `tmp_path` or `tempfile` fixtures |
| Async tests with event loop conflicts | The `reset_async_client` autouse fixture in integration conftest handles this; check if unit tests need similar |
| Tests that mock interfaces that have changed | Update mock to match current signature |
| Import errors from optional dependencies | Add `@pytest.mark.skipif` guards |

**If a test is fundamentally unreliable and cannot be made deterministic, remove it** and note what it was testing so a replacement can be written.

---

## Task 4: Add New Unit Tests for Coverage Gaps

After stabilizing existing tests, check coverage:

```bash
pytest libs/agno/tests/unit/ --cov=libs/agno/agno --cov-report=term-missing -v
```

Focus new tests on **core modules** with the most impact:

1. **`agno/agent/`** — Agent initialization, run lifecycle, tool dispatch, error handling
2. **`agno/models/base.py`** — Retry logic, error classification, backoff calculation
3. **`agno/team/`** — Team coordination, member routing, delegation
4. **`agno/memory/`** — Memory storage, retrieval, summarization
5. **`agno/knowledge/`** — Knowledge base loading, chunking, retrieval

### Test Writing Guidelines

- Follow existing patterns in neighboring test files
- Use class-based organization: `class TestFeatureName:`
- Use `@pytest.mark.parametrize` for multiple inputs
- Mock ALL external dependencies — unit tests must never make network calls
- Write both sync AND async variants for public methods
- Use descriptive names: `test_<what>_<condition>_<expected_result>`
- Don't use f-strings where there are no variables
- Don't use emojis in test output or comments

---

## Task 5: Verify Everything Passes

After all changes, run:

```bash
# Full unit test suite
./scripts/test.sh

# Integration tests (expect some skips from rate limits — that's the point)
pytest libs/agno/tests/integration/ -v 2>&1 | tail -50

# Formatting and validation
./scripts/format.sh
./scripts/validate.sh
```

**Success criteria:**
- All unit tests pass (zero failures)
- Integration test failures are ONLY from missing API keys or services, never from rate limits (those should be skipped)
- `format.sh` and `validate.sh` pass clean

---

## Rules

- **Only modify test files** — do not change production code in `libs/agno/agno/`
- Keep fixes minimal and targeted
- Don't add unnecessary dependencies
- Run `format.sh` and `validate.sh` after making changes

---

## Working Order

Process tasks in this order:

1. **Task 1** first (rate-limit conftest hooks) — biggest bang for buck, purely additive
2. **Task 2** next (retry/backoff on agents) — reduces rate-limit hits in the first place
3. **Task 3** then (fix broken unit tests) — stabilize the base
4. **Task 4** last (new unit tests) — build on a stable foundation
5. **Task 5** final verification

---

## Output

Maintain a running log at `.context/test-improvement-log.md` with:

```markdown
## Rate-Limit Protection Added
- [ ] provider_name — conftest.py created/updated

## Retry/Backoff Added
- [ ] path/to/test_file.py — N agents updated

## Tests Fixed
- [ ] path/to/test_file.py::test_name — description of fix

## Tests Removed
- [ ] path/to/test_file.py::test_name — reason for removal

## Tests Added
- [ ] path/to/test_file.py::test_name — what gap it fills

## Final Status
- Unit tests: PASS/FAIL (N passed, N failed, N skipped)
- Integration tests: PASS/FAIL (N passed, N failed, N skipped)
- format.sh: PASS/FAIL
- validate.sh: PASS/FAIL
```
