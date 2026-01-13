# CLAUDE_PRIVATE.md — coolm's Coding Standards

**Private file. Never commit.**

---

## Table of Contents

1. [Quick Reference](#quick-reference)
2. [Core Principles](#core-principles)
3. [Workflow Checklists](#workflow-checklists)
4. [Quality Standards](#quality-standards)
5. [Communication Templates](#communication-templates)
6. [Session Learnings](#session-learnings)

---

## Quick Reference

### Pre-Commit Checklist

```bash
□ ./scripts/format.sh          # Format code
□ ./scripts/validate.sh         # Lint + type check
□ pytest path/to/tests -v       # Run relevant tests
□ git diff                      # Review changes
□ Check commit message          # Clear and contextual
□ Verify no debug code          # Clean up temporary code
```

### Red Flags 🚩

**Stop if you see:**
- "This should work" without proof
- Tests pass but behavior not validated
- Commit message: "fix stuff" / "update"
- Bug fix without test
- Comment that just restates code

### Virtual Environment

**Always activate the virtual environment before running any code:**

```bash
# Standard virtual env (recommended)
source .venv/bin/activate

# Or demo environment if available
source .venvs/demo/bin/activate
```

**Why this matters:**
- Module imports fail without proper env (e.g., `agno.cli.credentials` not found)
- Cookbook examples won't run correctly
- Dependencies may be missing or wrong version

**Package management:**
- Always use `uv` not `pip` directly
- Install: `uv pip install package-name`
- Install from requirements: `uv pip install -r requirements.txt`

### Quick Commands

```bash
# Pre-commit validation
./scripts/format.sh && ./scripts/validate.sh

# Run tests
pytest libs/agno/tests/integration/models/openrouter/ -v

# Check what changed
git diff
git log --oneline -5
git show HEAD

# Verify gitignored files
git status --ignored
```

---

## Core Principles

### 1. Quality Over Speed

**Always verify claims with concrete evidence.**

❌ **Bad:** "Tests pass, looks good"
✅ **Good:** "Created monkey-patch to prove reasoning_details flow through message pipeline"

**When something seems too easy, dig deeper.**

Example from Session 2026-01-12:
- First test: "All pass!" but context wasn't preserved
- Questioned: "Did you test properly?"
- Result: Found tests needed history enabled, validation was superficial

### 2. Code Should Tell a Story

**For reviewers who don't know the context:**

```python
# ❌ Bad - restates code
# Add reasoning details to message dict
if msg.provider_data:
    msg_dict["reasoning_details"] = msg.provider_data["reasoning_details"]

# ✅ Good - explains why and what problem it solves
# Include reasoning_details for Gemini models (PR #5856, issue #5849)
# These encrypted blocks preserve Gemini's internal reasoning state across
# conversation turns. Required by OpenRouter's API - without this, multi-turn
# conversations fail with API errors.
if message.role == "assistant" and message.provider_data:
    if message.provider_data.get("reasoning_details"):
        message_dict["reasoning_details"] = message.provider_data["reasoning_details"]
```

### 3. Tests Must Prove the Fix

**Every bug fix needs a test that:**
- Would fail without the fix
- Explains what breaks
- Tests the real scenario (prefer integration)

```python
def test_gemini_multi_turn_with_history():
    """
    Test that multi-turn conversations work with Gemini through OpenRouter.

    **Why this matters:**
    This is the core issue from #5849. Without reasoning_details preservation,
    Gemini would error on the second turn of a conversation, making it unusable
    with OpenRouter.

    **What we validate:**
    1. First turn completes and captures reasoning_details
    2. Second turn receives those details and doesn't error
    3. Context is preserved across turns

    **What would break without the fix:**
    The second agent.run() call would raise an API error because Gemini requires
    reasoning_details from previous turns.
    """
```

---

## Workflow Checklists

### Starting a Bug Fix

**Before writing any code:**

```
□ Read issue + all comments thoroughly
□ Understand root cause, not just symptoms
□ Check if design doc exists (projects/ folder)
□ Look for similar bugs/patterns in codebase
□ Reproduce bug locally if possible
□ Identify exact code location for fix
```

**Questions to ask yourself:**
- What's the actual problem being solved?
- How will I know the fix works?
- What would break without this?
- Are there edge cases to consider?
- What evidence do I have that this works?

### During Implementation

**Investigation pattern:**

```
1. Read relevant code paths
   └─ Use Grep/Glob to find related code

2. Check existing tests for patterns
   └─ libs/agno/tests/.../test_*.py

3. Create minimal reproduction
   └─ Simplest code that shows the problem

4. Implement fix
   └─ Follow existing patterns

5. Verify fix works
   └─ Concrete proof, not assumption

6. Add proper tests
   └─ Integration test for bug scenario
```

**Keep asking:**
- What assumptions am I making?
- Have I verified this actually works?
- Can I prove this to a reviewer?
- Did I test the failure case?

### Before Committing

**Self-review checklist:**

```
□ Run ./scripts/format.sh
□ Run ./scripts/validate.sh
□ Run relevant tests: pytest path/to/tests -v
□ Review git diff for unintended changes
□ Remove any debug code (console.logs, prints)
□ Verify commit message has context
□ Check code comments explain "why"
□ Confirm tests validate the actual fix
```

**Would I approve this PR if I didn't write it?**
- Does commit message give reviewer context?
- Are non-obvious decisions explained?
- Did I test the failure scenario?
- Is the fix minimal and focused?

---

## Quality Standards

### Code Quality Bar

Every change must:

| Requirement | Why |
|-------------|-----|
| Solve a real problem | Not just "nice to have" |
| Include tests | Validate the fix works |
| Have explanatory comments | For complex/non-obvious logic |
| Follow existing patterns | Consistency matters |
| Be reviewable | Someone unfamiliar can understand it |

### Testing Standards

**Test must:**
- ✅ Fail if the fix is removed
- ✅ Explain what it validates in docstring
- ✅ Use descriptive assertions
- ✅ Test real scenario (integration > unit for bugs)

**Test naming:**
```python
# ❌ Bad
def test_thing():
def test_fix():

# ✅ Good
def test_gemini_preserves_reasoning_details_across_turns():
def test_multi_turn_conversation_with_tools():
```

**Test documentation:**
```python
def test_specific_behavior():
    """
    Test that [specific behavior] works correctly.

    **Context:** Issue #1234 - [problem description]

    **Why this matters:** [What breaks without fix]

    **What we validate:**
    1. [First validation point]
    2. [Second validation point]
    3. [Third validation point]
    """
```

### Documentation Requirements

**For bug fixes:**
| Element | Required |
|---------|----------|
| Issue reference | `Fixes #1234` |
| Problem description | What was broken |
| Solution explanation | How the fix works |
| Test validation | What would fail without it |

**For features:**
| Element | Required |
|---------|----------|
| Design doc link | If exists in `projects/` |
| Use case | Why this feature |
| Example usage | Code snippet |
| Edge cases | What to watch for |

---

## Communication Templates

### PR Review Comments

**Rules:**
1. **Line comments only** - Never post general PR comments. Always attach to specific lines.
2. **Concise, human tone** - No verbose LLM-style comments. Write like a colleague, not an essay.
3. **Explain the issue** - Be brief but complete. Say what's wrong and why it matters.

**Command:**
```bash
gh api repos/OWNER/REPO/pulls/PR/comments \
  -f body="Comment" \
  -f path="file.py" \
  -f commit_id="$(gh pr view PR --json headRefOid -q .headRefOid)" \
  -f line=LINE \
  -f side="RIGHT"
```

**Wrong:**
- `gh pr comment` - general comment, not on a line
- `gh pr review --comment` - review summary, not line comment

**Comment style:**

```
❌ Bad (verbose LLM):
"I noticed that this implementation appears to be missing several
important configuration fields. Specifically, the Step dataclass
contains fields such as max_retries, timeout_seconds, and step_id
which are not being copied in this method. This could potentially
lead to issues where..."

✅ Good (human, concise):
"Bug: Missing step_id, max_retries, timeout_seconds.
These get reset to defaults after copy."
```

---

### Commit Message Template

```
type: short description (50 chars max)

Detailed explanation of what changed and why. Reference issue numbers
and explain the problem being solved.

Key changes:
- Change 1: Why this matters
- Change 2: Why this matters

Technical details:
[Optional: Implementation notes, edge cases, decisions made]

Fixes #issue-number
Related: #other-issue
```

**Commit types:**
- `feat:` New feature
- `fix:` Bug fix
- `test:` Add/update tests
- `docs:` Documentation only
- `refactor:` Code restructuring
- `chore:` Tooling/config changes

**Real examples:**

```
✅ Good:
test: add integration tests for Gemini reasoning_details preservation

Validates PR #5856 fix for issue #5849 where Gemini 3 Flash through
OpenRouter would fail on multi-turn conversations.

Tests verify:
- reasoning_details are captured from API responses (lines 838-844)
- reasoning_details are sent back in subsequent requests (lines 374-378)
- Multi-turn conversations complete without errors
- Tool use works with reasoning models

All 4 tests pass. Requires OPENROUTER_API_KEY.

Fixes #5849

❌ Bad:
test: add tests
update tests
fix
```

### PR Description Template

```markdown
## Problem

[Clear description of the issue with context]

**Issue:** #1234
**Impact:** [Who/what is affected]
**Root cause:** [Why this happened]

## Solution

[Explain the approach and key changes]

**Key changes:**
- `path/to/file.py:100-110` - [What changed and why]
- `path/to/test.py:50-75` - [Test coverage]

**Alternative approaches considered:**
- [Approach 1]: [Why not chosen]
- [Approach 2]: [Why not chosen]

## Testing

**Added tests:**
- `path/to/test.py::test_name` - [What it validates]

**Verification:**
```bash
pytest path/to/test.py -v
./scripts/validate.sh
```

**Manual testing:**
- [Scenario 1]: ✅ Works
- [Scenario 2]: ✅ Works

## Checklist

- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] Ran format.sh and validate.sh
- [ ] Verified fix solves the issue
- [ ] No breaking changes OR migration guide added

## References

- Fixes #1234
- Related: #5678
- Docs: [OpenRouter reasoning details](https://openrouter.ai/docs/...)
```

### Code Comment Style

**When to comment:**
- ✅ Non-obvious logic or decisions
- ✅ Why a particular approach was chosen
- ✅ Edge cases being handled
- ✅ External references (issues, docs)

**How to comment:**

```python
# Short explanation of what this section does
# Multiple lines if needed
# Reference: #1234 or https://docs.example.com
code_here()

# For complex sections:
# WHY: Explain the reasoning/problem being solved
# WHAT: High-level description
# HOW: Implementation notes if non-obvious
complex_code()
```

**Examples:**

```python
# ❌ Bad - just restates the code
# Loop through messages
for message in messages:
    process(message)

# ✅ Good - explains why/what problem
# Process messages in batches to avoid memory issues with large datasets
# Batch size of 100 chosen based on profiling (see #1234)
for batch in chunk_messages(messages, batch_size=100):
    process_batch(batch)
```

---

## Session Learnings

### 2026-01-12: PR #5856 - Gemini Reasoning Details

**Issue:** Gemini 3 Flash + OpenRouter broken for multi-turn conversations

**Investigation process:**
1. Checked out PR branch locally
2. Reviewed 20-line fix (3 locations in chat.py)
3. Manual testing showed conversations worked
4. BUT - initial testing was superficial
5. Created monkey-patch to prove reasoning_details actually sent back
6. Learned: Gemini doesn't always return reasoning_details

**Key learnings:**
- Don't accept "tests pass" at face value
- Verify claims with concrete evidence
- Use creative techniques (monkey-patching) to inspect internals
- Tests should handle optional fields gracefully

**Testing insights:**
```python
# Created proof that reasoning_details flow correctly
def inspect_format_message(self, message, compress_tool_results=False):
    result = original_format_message(self, message, compress_tool_results)
    if message.role == "assistant" and "reasoning_details" in result:
        print("✓ FOUND: reasoning_details in outgoing message!")
    return result
```

**Process improvements:**
1. Always ask "did we test properly?" before declaring success
2. Create evidence, don't just assume
3. Integration tests > unit tests for bug fixes
4. Test docstrings should explain what breaks without the fix

**Added to workflow:**
- Question superficial test results
- Look for concrete proof of bidirectional flow
- Handle optional API fields gracefully in tests

---

### 2026-01-13: PR #4151 - Browser Automation Tools

**Issue:** Add BrowserbaseTools and PlaywrightTools for browser automation

**Key learnings:**

1. **Virtual environment is critical**
   - Cookbook examples fail with import errors without proper env
   - Always run `source .venv/bin/activate` first
   - Use `uv pip install` not `pip install`

2. **Error handling consistency matters**
   - BrowserbaseTools pattern: let exceptions propagate, cleanup in catch
   - PlaywrightTools initially returned error JSON - inconsistent
   - Refactored to raise exceptions for consistency

3. **Merge conflicts require careful resolution**
   - Main branch had evolved with async support and feature flags
   - After accepting main's changes, bugs still needed re-fixing
   - Both sync and async methods needed the same fixes

**Bug fixes applied:**
- `.url()` → `.url` (property, not method)
- Redundant ternary `x if x else ""` → `x`
- Context crash when browser is None
- Unused variable lint error

**Testing pattern:**
```python
# Error tests should use pytest.raises, not check JSON
with pytest.raises(Exception, match="error message"):
    playwright_tools.go_back()
```

**Process improvements:**
- Always activate venv before running cookbooks
- Run format + validate before committing
- Keep PR focused - don't include unrelated formatting changes

---

### 2026-01-13: PR #5997 - Gemini GCS and External URL Support

**Issue:** Add direct GCS and external URL support for Gemini file inputs

**Key learnings:**

1. **Always activate virtual environment before testing**
   ```bash
   source .venvs/demo/bin/activate
   .venvs/demo/bin/python cookbook/path/to/example.py
   ```

2. **Always run format.sh and validate.sh before committing**
   ```bash
   ./scripts/format.sh && ./scripts/validate.sh
   ```

3. **Gemini model compatibility varies by feature**
   - External HTTPS URLs: Only work with Gemini 3.x models (not 2.0)
   - GCS URIs: Require Vertex AI (OAuth), work with any model
   - This is poorly documented by Google

4. **Authentication requirements differ by URL type**
   | URL Type | Auth Required |
   |----------|---------------|
   | HTTPS URLs | API key + Gemini 3.x |
   | GCS URIs | Vertex AI (OAuth) |

**Testing workflow:**
```bash
# 1. Activate environment
source .venvs/demo/bin/activate

# 2. Run the cookbook
.venvs/demo/bin/python cookbook/11_models/google/gemini/example.py

# 3. Before committing
./scripts/format.sh && ./scripts/validate.sh
```

**Process improvements:**
- Test with correct model versions (check Google docs for feature support)
- GCS testing requires `gcloud auth application-default login`
- Use real sample files in examples (not placeholders like `your-bucket`)

---

### Template for Future Sessions

**Date:** YYYY-MM-DD
**Topic:** [PR/Issue/Feature]

**Problem:**
[What we were solving]

**Investigation:**
[Key steps taken, dead ends, breakthroughs]

**Solution:**
[What worked and why]

**Key learnings:**
- Learning 1
- Learning 2

**Process improvements:**
- Improvement 1
- Improvement 2

**Code patterns discovered:**
[Useful patterns to reuse]

**Mistakes made:**
[What not to do next time]

---

## Tools & Aliases

### Essential Commands

```bash
# Pre-commit validation
alias check='./scripts/format.sh && ./scripts/validate.sh'

# Testing
alias test-unit='pytest libs/agno/tests/unit/ -v'
alias test-integration='pytest libs/agno/tests/integration/ -v'
alias test-models='pytest libs/agno/tests/integration/models/ -v'
alias test-last='pytest --lf -v'  # Last failed
alias test-verbose='pytest -v -s'  # With output

# Git shortcuts
alias gs='git status'
alias gd='git diff'
alias gds='git diff --staged'
alias gl='git log --oneline -10'
alias gshow='git show --stat'
alias gbranch='git branch -v'

# Code exploration
alias search='rg'  # ripgrep
alias find-test='find . -name "test_*.py" | grep'
```

### Useful Functions

```bash
# Complete pre-commit check
check-before-commit() {
    echo "→ Formatting..."
    ./scripts/format.sh || return 1

    echo "→ Validating..."
    ./scripts/validate.sh || return 1

    echo "→ Git status..."
    git status -s

    echo "→ Recent changes..."
    git diff --stat

    echo "✓ Ready to commit"
}

# Find what changed in a file
what-changed() {
    git log -p --follow -- "$1" | head -200
}

# Show recent work
recent() {
    git log --oneline --since="1 day ago" --author="coolm"
}

# Find related tests
find-tests-for() {
    local module=$1
    find libs/agno/tests -name "*${module}*.py"
}
```

---

## Personal Reminders

### Always

✅ Question first test results - concrete evidence?
✅ Think like a reviewer - would I approve this?
✅ Test the failure case, not just happy path
✅ Comments explain "why", not just "what"
✅ Run format + validate before every commit
✅ Commit messages tell the story for reviewers

### Never

❌ Commit without running format.sh + validate.sh
❌ Write lazy commit messages ("fix stuff", "update")
❌ Add tests that don't validate the actual fix
❌ Skip test docstrings
❌ Assume "tests pass" means fix works
❌ Leave debug code in commits

### When Stuck

1. **Re-read the issue** - fresh perspective
2. **Look for patterns** - search similar code
3. **Create minimal repro** - simplify the problem
4. **Ask for clarification** - don't assume
5. **Take a break** - come back with fresh eyes

### Quality Mantras

> "If you can't prove it works, it doesn't work"

> "Tests should fail when the fix is removed"

> "Write commit messages for reviewers, not machines"

> "Code comments explain why, not what"

> "Concrete evidence beats assumptions"

---

## Continuous Improvement

**After each coding session:**
1. Add learnings to this file
2. Update workflow if process improved
3. Document useful patterns discovered
4. Note mistakes to avoid next time

**Monthly review:**
- [ ] Review session learnings
- [ ] Update quality standards if needed
- [ ] Refine communication templates
- [ ] Remove outdated preferences

**Questions to reflect on:**
- What went well this session?
- What would I do differently?
- What new pattern did I discover?
- What mistake should I avoid next time?

---

*Last updated: 2026-01-13 (PR #5997 session)*
*This file evolves with every session. Keep it current.*
