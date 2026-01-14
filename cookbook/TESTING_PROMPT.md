# Claude Code Prompt for Cookbook Testing

Use this prompt to test and document any cookbook directory following the golden standard established in `cookbook/15_learning/`.

## Quick Prompt

```
Your task is to test the cookbooks in `cookbook/15_learning`.

1. Read `cookbook/15_learning/README.md` to understand the cookbook structure and purpose.
2. Check `cookbook/15_learning/CLAUDE.md` to understand the testing workflow.
3. Check `cookbook/15_learning/TEST_LOG.md` to understand the past test results log.
4. Confirm the test plan with me.
5. Run all tests and update `cookbook/15_learning/TEST_LOG.md` with the results.
```

## Full Prompt

```
Your task is to test the cookbooks in `cookbook/<FOLDER_NAME>`.

### Step 1: Review
1. Read `cookbook/<FOLDER_NAME>/README.md` (if exists)
2. List all Python files in the directory
3. Read 3-4 representative files to understand:
   - What model they use (Gemini, OpenAI, Claude)
   - What dependencies they need (DB, vector store, API keys)
   - What they're testing

### Step 2: Check CLAUDE.md
1. Read `cookbook/<FOLDER_NAME>/CLAUDE.md` if it exists
2. If missing, ask if I should create one using `cookbook/15_learning/CLAUDE.md` as reference

### Step 3: Check TEST_LOG.md
1. Read `cookbook/<FOLDER_NAME>/TEST_LOG.md` if it exists
2. If missing, create it using `cookbook/15_learning/TEST_LOG.md` as reference

### Step 4: Test Plan
Provide a prioritized test plan with:
- Phases grouped by complexity (basic → advanced)
- Estimated time per test
- Prerequisites (env vars, services, API keys)
- Notes on special requirements (interactive, long-running)

### Step 5: Run Tests
When asked, run tests using:
.venvs/demo/bin/python cookbook/<FOLDER_NAME>/<file>.py

Update TEST_LOG.md after each test with PASS/FAIL and observations.

Do not run tests until I confirm the plan.
```

## Golden Standard

Reference implementations in `cookbook/15_learning/`:
- `CLAUDE.md` — Testing instructions template
- `TEST_LOG.md` — Test log template

## Test Environment

```bash
# Default virtual environment
.venvs/demo/bin/python

# Or create cookbook-specific env
uv venv .venvs/<cookbook-name> --python 3.12
source .venvs/<cookbook-name>/bin/activate
uv pip install -r cookbook/<FOLDER_NAME>/requirements.txt
```
```bash
# PostgreSQL with pgvector (if needed)
./cookbook/scripts/run_pgvector.sh

# SQLite requires no setup
```
