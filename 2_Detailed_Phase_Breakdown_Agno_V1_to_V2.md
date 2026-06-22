# Detailed Phase Breakdown: Agno V1 → V2 Migration (Fresh Start)

**Test-First Approach: Insight Agent V3.1.1 as Proof-of-Concept**

---

## PHASE 0: Repository Extraction & Setup

### Objective
Extract agno_custom to external repo, create v3.1.1 test case, establish clean branch structure

---

### Task 0.1: Create New Branches

**In `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno`:**
```bash
cd /Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno
git checkout -b v2-upgrade_v2
# This branch will contain Agno V2.6.5 + agno_custom V2
```

**In `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/banavo-agent-os`:**
```bash
cd /Users/glaston.jiue/Desktop/Banavo/Agent_OS/banavo-agent-os
git checkout -b agno_v2-migrate_v2
# This branch will contain v3.1.1 migration + v3.0.1 reference
```

**Verification:**
```bash
# In both repos, verify branch exists
git branch -v | grep -E "v2-upgrade_v2|agno_v2-migrate_v2"
```

**Deliverables:**
- [ ] v2-upgrade_v2 branch created in /agno
- [ ] agno_v2-migrate_v2 branch created in banavo-agent-os
- [ ] Both branches checked out and ready

---

### Task 0.2: Extract agno_custom to /agno

**What to do:**
```bash
# 1. Verify agno_custom exists in banavo-agent-os
cd /Users/glaston.jiue/Desktop/Banavo/Agent_OS/banavo-agent-os
ls -la agno_custom/ | head -20

# 2. Copy to /agno (into v2-upgrade_v2 branch)
cd /Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno
cp -r ../banavo-agent-os/agno_custom ./agno_custom
git add agno_custom/
git commit -m "refactor: extract agno_custom from banavo-agent-os (fresh start)"

# 3. Verify extraction
ls -la agno_custom/ | head -20
```

**Document structure:**
Create `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno/AGNO_CUSTOM_STRUCTURE.md`:
```markdown
# agno_custom Structure

Extracted from: /Users/glaston.jiue/Desktop/Banavo/Agent_OS/banavo-agent-os/agno_custom/

Directory layout:
├── agent/
├── team/
├── memory/
├── models/
├── tools/
├── utils/
├── run/
├── events/
└── [other modules]

Status: V1 code, will be updated to V2 in Phase 1
Migration Priority: High (required for v3.1.1)

All files preserve original logic, only APIs updated to V2.
```

**Deliverables:**
- [ ] agno_custom copied to /agno/agno_custom/
- [ ] Git commit created
- [ ] Structure documented
- [ ] Files intact and readable

---

### Task 0.3: Update setup_dev_env.sh in banavo-agent-os

**File:** `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/banavo-agent-os/setup_dev_env.sh`

**Content:**
```bash
#!/bin/bash
# Development environment setup for Agno V2 migration
# Configures PYTHONPATH to use external agno_custom from /agno

export PYTHONPATH="/Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno:${PYTHONPATH}"

echo "✅ Development environment configured for Agno V2"
echo "PYTHONPATH=$PYTHONPATH"
echo ""
echo "agno_custom will be imported from:"
echo "  /Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno/agno_custom"
echo ""
echo "To use this setup, run:"
echo "  source setup_dev_env.sh"
```

**Test:**
```bash
cd /banavo-agent-os
source setup_dev_env.sh
python -c "import agno_custom; print(f'✓ agno_custom from: {agno_custom.__file__}')"
```

**Deliverables:**
- [ ] setup_dev_env.sh created/updated
- [ ] PYTHONPATH points to /agno
- [ ] Import test passes

---

### Task 0.4: Update .gitignore in banavo-agent-os

**File:** `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/banavo-agent-os/.gitignore`

**Add:**
```
# Local agno_custom (use external version in /agno)
/agno_custom/
```

**Reason:** Local agno_custom should not be committed; use external /agno/agno_custom via PYTHONPATH

**Verification:**
```bash
cd /banavo-agent-os
git status | grep agno_custom
# Should show nothing (file is ignored)
```

**Deliverables:**
- [ ] .gitignore updated
- [ ] agno_custom ignored by git

---

### Task 0.5: Create insight_agent_v3.1.1 (V2 Test Case)

**What to do:**
```bash
# 1. Copy v3.0.1 to v3.1.1
cd /Users/glaston.jiue/Desktop/Banavo/Agent_OS/banavo-agent-os
cp banavo/agent_os/versions/insight_agent_v3/v3_0_1.py \
   banavo/agent_os/versions/insight_agent_v3/v3_1_1.py

# 2. Edit v3_1_1.py to mark as V2 version
# Change at top of file:
# OLD: Version 3.0.1 (Agno V1)
# NEW: Version 3.1.1 (Agno V2 test case)

# 3. Verify file exists
ls -la banavo/agent_os/versions/insight_agent_v3/v3_1_1.py
```

**Initial Changes (minimal):**
```python
# At top of /banavo-agent-os/banavo/agent_os/versions/insight_agent_v3/v3_1_1.py:

"""
Insight Agent V3.1.1 - Agno V2 Test Case

This is a copy of v3.0.1 being migrated to Agno V2.
Serves as proof-of-concept for V2 migration.

Differences from v3.0.1:
- Updated to Agno V2.6.5 APIs
- Updated agno_custom imports to V2
- Updated streaming handlers for V2
- All business logic unchanged (target 100% behavior match)

Status: UNDER MIGRATION (Phase 2)
"""

from enum import Enum
from typing import AsyncIterator, Optional
from uuid import uuid4

# [rest of file unchanged from v3.0.1 for now]
```

**Document in `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/banavo-agent-os/V3_VERSIONS.md`:**
```markdown
# Insight Agent V3 Versions

## v3.0.1 - Original (Agno V1)
- Framework: Agno V1.6.2
- Status: Production (reference implementation)
- Branch: main
- Use for: Baseline comparison, understanding business logic

## v3.1.1 - V2 Test Case (IN PROGRESS)
- Framework: Agno V2.6.5
- Status: Under migration (Phase 2)
- Branch: agno_v2-migrate_v2
- Use for: V2 migration validation, pattern discovery
- Target: 100% behavior match with v3.0.1

## v3.2.0 - Optimized (Future)
- Framework: Agno V2.6.5
- Status: Planned (Phase 4+)
- Use for: Production deployment after v3.1.1 validated
- Improvements: Better reasoning, faster execution, lower tokens

Running both v3.0.1 and v3.1.1:
- v3.0.1 on standard import path (uses V1 agno)
- v3.1.1 via external agno_custom (uses V2 agno)
```

**Deliverables:**
- [ ] v3_1_1.py created (copy of v3_0_1.py)
- [ ] Initial header comments added
- [ ] V3_VERSIONS.md documented
- [ ] File ready for Phase 2 migration

---

### Task 0.6: Document Repository Structure

**File:** `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/REPOSITORY_STRUCTURE.md`

**Content:**
```markdown
# Repository Structure (Agno V2 Migration)

## /agno (External Repo)
Private repository containing:
- Agno V2.6.5 framework
- agno_custom module (extracted from banavo-agent-os)

Branches:
- main (stable, Agno V1)
- v2-upgrade_v2 (Agno V2.6.5 + agno_custom V2)

Path: `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno`

PYTHONPATH Configuration:
When running banavo-agent-os, set PYTHONPATH to include /agno
so that `import agno_custom` resolves to external agno_custom

## /banavo-agent-os (Main Repo)
Production agent implementations:
- banavo/agent_os/versions/
  - insight_agent_v3/v3_0_1.py (V1 reference)
  - insight_agent_v3/v3_1_1.py (V2 test case)
  - [other agents - future migration]

Branches:
- main (stable, Agno V1)
- agno_v2-migrate_v2 (v3.1.1 + V2 migration)

PYTHONPATH:
Configured in setup_dev_env.sh
Points to: `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno`

## Key Files

### In /agno:
- agno_custom/ (extracted)
- AGNO_CUSTOM_STRUCTURE.md (module layout)
- pyproject.toml (agno>=2.6.5 dependency)

### In /banavo-agent-os:
- setup_dev_env.sh (PYTHONPATH config)
- .gitignore (excludes local agno_custom)
- V3_VERSIONS.md (version tracking)
- banavo/agent_os/versions/insight_agent_v3/
  - v3_0_1.py (reference - unchanged)
  - v3_1_1.py (test case - under migration)

## Workflow

### Running v3.0.1 (V1):
```bash
cd /banavo-agent-os
python -m banavo.agent_os.versions.insight_agent_v3.v3_0_1
# Uses built-in agno V1.6.2
# Can run without setup_dev_env.sh
```

### Running v3.1.1 (V2):
```bash
cd /banavo-agent-os
source setup_dev_env.sh
python -m banavo.agent_os.versions.insight_agent_v3.v3_1_1
# Uses external agno_custom from /agno via PYTHONPATH
# Requires setup_dev_env.sh to be sourced first
```

## Git Operations

### In /agno:
```bash
git checkout v2-upgrade_v2
git status  # Should show agno_custom changes
```

### In /banavo-agent-os:
```bash
git checkout agno_v2-migrate_v2
git status  # Should show v3_1_1.py, setup_dev_env.sh
```

### Syncing changes:
- Changes to agno_custom: Push to /agno repo
- Changes to v3.1.1: Push to banavo-agent-os repo
- Both repos tracked independently
```

**Deliverables:**
- [ ] REPOSITORY_STRUCTURE.md created
- [ ] Clear instructions for both workflows
- [ ] Documentation complete and reviewed

---

### Task 0.7: Phase 0 Completion Checklist

**Verify all Phase 0 tasks:**
```bash
# 1. Check branches exist
cd /agno && git branch | grep v2-upgrade_v2
cd /banavo-agent-os && git branch | grep agno_v2-migrate_v2

# 2. Check agno_custom extracted
ls -la /agno/agno_custom/__init__.py

# 3. Check setup_dev_env.sh
cat /banavo-agent-os/setup_dev_env.sh

# 4. Check .gitignore
grep "agno_custom" /banavo-agent-os/.gitignore

# 5. Check v3.1.1 exists
ls -la /banavo-agent-os/banavo/agent_os/versions/insight_agent_v3/v3_1_1.py

# 6. Check documentation
ls -la /agno/AGNO_CUSTOM_STRUCTURE.md
ls -la /banavo-agent-os/V3_VERSIONS.md
ls -la /Users/glaston.jiue/Desktop/Banavo/Agent_OS/REPOSITORY_STRUCTURE.md
```

**Deliverables:**
- [ ] All Phase 0 tasks complete
- [ ] All files in place
- [ ] Documentation complete
- [ ] Ready to proceed to Phase 1

---

## PHASE 1: Agno V2 Framework Upgrade

### Objective
Upgrade /agno from V1 to V2.6.5, ensure agno_custom compatible with V2 APIs

---

### Task 1.1: Verify Local Agno V2 Files

**In `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno` (v2-upgrade_v3 branch):**

⚠️ **IMPORTANT:** Work with local files only. No remote repo access needed.

All Agno V2 files are already cloned locally. Just verify the structure exists.

```bash
cd /agno

# 1. Verify agno V2 structure exists locally
ls -la libs/agno/agno/ | head -20
# Should show V2.6.5 structure with:
# - agent/
# - models/
# - team/
# - knowledge/
# - memory/
# - tools/
# - db/
# - [other V2 modules]

# 2. Count total Python files in Agno V2
find libs/agno/agno -name "*.py" -type f | wc -l
# Should show 1000+ files

# 3. Verify agno_custom/ directory
ls -la agno_custom/
# Should show 29 Python files extracted in Phase 0

# 4. Check current state
git status
# Should show clean working tree
```

**What to verify:**
- ✅ Agno V2 framework files present in libs/agno/agno/
- ✅ agno_custom/ directory present with 29 files
- ✅ Working tree clean (no uncommitted changes)
- ✅ Both directories coexist without conflicts

**Why local-only approach:**
- All files already cloned on local machine
- No need to fetch from remote
- Simpler workflow, less risk of network issues
- Faster development cycle

**Deliverables:**
- [ ] Verify Agno V2 files structure
- [ ] Verify agno_custom/ present
- [ ] Confirm working tree clean
- [ ] Document local V2 structure

---

### Task 1.2: Analyze V1 Imports & Plan Compatibility Stubs

**In `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno/agno_custom` (local files):**

⚠️ **IMPORTANT:** Work with local files only. No remote repo access needed.

Scan agno_custom for V1-only imports and plan compatibility stubs.

```bash
cd /agno/agno_custom

# 1. Find all agno imports
grep -r "from agno\|import agno" --include="*.py" | grep -v "__pycache__" > /tmp/v1_imports.txt
cat /tmp/v1_imports.txt

# 2. Analyze imports by module
echo "=== Agent imports ===" && grep "from agno\|import agno" agent/*.py 2>/dev/null
echo "=== Team imports ===" && grep "from agno\|import agno" team/*.py 2>/dev/null
echo "=== Memory imports ===" && grep "from agno\|import agno" memory/*.py 2>/dev/null
echo "=== Models imports ===" && grep "from agno\|import agno" models/**/*.py 2>/dev/null
```

**Expected V1-only imports to stub:**
```
from agno.metrics import SessionMetrics        ❌ V1 only (no V2 equiv)
from agno.knowledge import Knowledge           ⚠️ Changed to AgentKnowledge
from agno.db.schemas import UserMemory         ⚠️ API changed
from agno.run.base import BaseRunOutputEvent   ⚠️ Changed to BaseRunResponseEvent
```

**Compatibility Stubs to Create:**
```python
# In agno_custom modules, add:

class SessionMetrics:
    """Stub for V1 SessionMetrics (not in V2)"""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class UserMemory:
    """Stub for V1 UserMemory (not in V2)"""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)
    
    def to_dict(self) -> dict:
        return self.__dict__.copy()
```

**Action Plan:**
1. Catalog all problematic imports
2. Identify which need stubs vs. V2 equivalents
3. Create stubs in appropriate modules
4. Update imports to use V2 or stubs
5. Document mapping (V1 → V2/stub)

**Deliverables:**
- [ ] V1 imports catalogued and analyzed
- [ ] Compatibility stub list created
- [ ] Mapping document (V1 → V2)
- [ ] Ready for implementation

---

### Task 1.3: Validate agno_custom Imports (Local)

**In `/agno` and `/banavo-agent-os` (local files):**

⚠️ **IMPORTANT:** Test with local files only. Configure PYTHONPATH for external agno_custom.

```bash
cd /banavo-agent-os

# 1. Configure PYTHONPATH for external agno_custom
source setup_dev_env.sh
echo "PYTHONPATH: $PYTHONPATH"

# 2. Test agno_custom imports
python3 -c "import agno_custom; print('✓ agno_custom imports from external /agno')"
python3 -c "print('Location:', agno_custom.__file__)"

# 3. Test critical imports
python3 -c "from agno_custom.agent import Agent; print('✓ Agent imports OK')"
python3 -c "from agno_custom.team import Team; print('✓ Team imports OK')"
python3 -c "from agno_custom.memory import Memory; print('✓ Memory imports OK')"
python3 -c "from agno_custom.models import Claude, OpenAIChat; print('✓ Models imports OK')"

# 4. Test v3.1.1 can import
cd /banavo-agent-os
python3 -c "
from banavo.agent_os.versions.insight_agent_v3.v3_1_1 import AgentOS
print('✓ v3.1.1 imports successfully')
"
```

**What to verify:**
- ✅ agno_custom imports from /agno
- ✅ All critical modules importable
- ✅ v3.1.1 can initialize
- ✅ No V1-only import errors

**If import errors:**
1. Check which imports fail
2. Create compatibility stubs (Task 1.2)
3. Re-test
4. Document fix

**Deliverables:**
- [ ] agno_custom fully importable
- [ ] All critical imports working
- [ ] v3.1.1 can import successfully
- [ ] Ready for Phase 2

---

### Task 1.4: Document Breaking Changes (Local Analysis)

**File:** `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/PHASE_1_BREAKING_CHANGES.md`

⚠️ **IMPORTANT:** Create locally, document findings from Tasks 1.2-1.3 only.

**What to document:**
1. V1 imports that don't exist in V2
2. API changes discovered during import analysis
3. Compatibility stubs created
4. Migration workarounds applied

**Example format:**
```markdown
# Agno V1 → V2 Breaking Changes (Local Analysis)

## Removed Classes (need stubs):
- SessionMetrics (V1 only, no V2 equivalent)
- UserMemory (API changed significantly)
- MemoryManager (architecture redesigned)

## Changed Imports:
- V1: from agno.knowledge import Knowledge
- V2: from agno.knowledge import AgentKnowledge

## API Changes:
- V1: agent.run(message) → V2: agent.arun(message)
- V1: model.invoke() → V2: model.ainvoke()

## Stubs Created:
- SessionMetrics (in agno_custom)
- UserMemory (in agno_custom)
- [others as discovered]

## Compatibility Strategy:
- Create stubs for V1-only classes
- Use V2 equivalents where they exist
- Preserve existing behavior
```

**How to create:**
1. After Tasks 1.2-1.3 complete
2. Document all issues discovered
3. List all stubs created
4. Note any workarounds applied
5. Save to /Users/glaston.jiue/Desktop/Banavo/Agent_OS/

**Deliverables:**
- [ ] Breaking changes catalogued
- [ ] Stubs documented
- [ ] Workarounds recorded
- [ ] Ready for Phase 2 reference

---

### Task 1.5: Phase 1 Completion Summary

**Verify completion (local files only):**
```bash
cd /agno

# 1. Verify working on v2-upgrade_v3 branch
git branch | grep "*"
# Should show: * v2-upgrade_v3

# 2. Verify agno_custom directory present
ls -la agno_custom/ | head -15
# Should show 29 Python files

# 3. Verify agno V2 structure exists
ls -la libs/agno/agno/ | head -10
# Should show V2 modules

# 4. From banavo-agent-os: test external agno_custom
cd /banavo-agent-os
source setup_dev_env.sh
python3 -c "import agno_custom; print('✓ Phase 1 Complete')"
```

**What was accomplished:**
- ✅ Verified Agno V2 structure (local)
- ✅ Analyzed V1 imports in agno_custom
- ✅ Planned compatibility stubs
- ✅ Validated imports work with PYTHONPATH
- ✅ Documented breaking changes
- ✅ Ready for Phase 2

**Deliverables:**
- [ ] Agno V2 files structure verified (local)
- [ ] agno_custom fully compatible/stubbed
- [ ] All imports working via PYTHONPATH
- [ ] Breaking changes documented
- [ ] Ready for Phase 2: v3.1.1 Migration

---

## PHASE 2: V3.1.1 V1 → V2 Migration

### Objective
Migrate insight_agent_v3.1.1 to Agno V2, validate output quality

**Note:** This is the primary test case. All changes made here will inform migration of other agents.

---

### Task 2.1: Analyze v3.0.1 Code Structure

**In `/banavo-agent-os` (agno_v2-migrate_v2 branch):**

```bash
# 1. Understand v3.0.1 structure
wc -l banavo/agent_os/versions/insight_agent_v3/v3_0_1.py
head -50 banavo/agent_os/versions/insight_agent_v3/v3_0_1.py

# 2. Identify key components
grep -n "class\|def\|import" banavo/agent_os/versions/insight_agent_v3/v3_0_1.py | head -50

# 3. Check imports
grep "^from\|^import" banavo/agent_os/versions/insight_agent_v3/v3_0_1.py | sort | uniq
```

**Document findings in v3_1_1.py as comments:**
```python
# Key components in v3.0.1:
# - DatalakeAgentResponseStatus enum (lines 74-77)
# - DatalakeAgentResponseSummary model (lines 80-86)
# - AgentOS class (lines 89+)
#   - artifact_reader_agent
#   - relevance_judging_agent
#   - context_artifact_agent
#   - context_resolution_agent
#   - summarization_agent
#   - banavo_datalake_agent
#   - data_science_agent
#   - orchestrator
# - entry_point async method

# Strategy:
# 1. Keep all business logic unchanged
# 2. Update imports to use V2 agno_custom
# 3. Update Agent/Team API calls
# 4. Update streaming handlers
# 5. Test on port 8000
```

**Deliverables:**
- [ ] Code structure understood
- [ ] Components mapped
- [ ] Migration strategy documented

---

### Task 2.2: Update Imports in v3_1_1.py

**In v3.1.1.py:**

Replace all V1 agno_custom imports with V2 equivalents:

```python
# OLD (v3_0_1.py):
from agno_custom.memory import Memory
from agno_custom.models import Claude, OpenAIChat, OpenAIServiceTier
from agno_custom.team import Team
from agno_custom.agent import Agent

# NEW (v3_1_1.py):
# These remain the same, but agno_custom is now from /agno
# PYTHONPATH is configured to find /agno/agno_custom
from agno_custom.memory import Memory
from agno_custom.models import Claude, OpenAIChat, OpenAIServiceTier
from agno_custom.team import Team
from agno_custom.agent import Agent

# The imports themselves don't change (still from agno_custom)
# But agno_custom is now V2-compatible (from /agno/agno_custom)
```

**Verify:**
```bash
cd /banavo-agent-os
source setup_dev_env.sh
python -c "from banavo.agent_os.versions.insight_agent_v3.v3_1_1 import AgentOS; print('✓ v3_1_1 imports OK')"
```

**Deliverables:**
- [ ] All imports updated
- [ ] v3_1_1.py imports successfully
- [ ] Using V2 agno_custom from /agno

---

### Task 2.3: Update Agent/Team API Calls

**Common changes from V1 → V2:**

```python
# V1 Agent/Team methods:
# agent.run(message) → async
# agent.run_sync(message) → sync

# V2 Agent/Team methods:
# agent.arun(message) → async (same as V1)
# No sync version built-in

# For v3.1.1:
# Keep using async methods
# Use asyncio.run() for sync contexts if needed
```

**Scan v3_1_1.py for patterns:**
```python
# Check for:
# - model.invoke() calls
# - agent.run() calls
# - agent.run_sync() calls
# - team.run() calls
# - streaming patterns

grep -n "\.run\|\.arun\|\.invoke" banavo/agent_os/versions/insight_agent_v3/v3_1_1.py
```

**Update patterns:**
```python
# If found:
# OLD: response = agent.run(message)
# NEW: response = await agent.arun(message)

# OLD: response = model.invoke(...)
# NEW: response = await model.ainvoke(...)

# Keep changes minimal - only API updates, no logic changes
```

**Deliverables:**
- [ ] All agent/team API calls identified
- [ ] Updated to V2 async patterns
- [ ] Business logic unchanged

---

### Task 2.4: Update Streaming Handlers

**Check for streaming code in v3_1_1.py:**
```bash
grep -n "stream\|astream" banavo/agent_os/versions/insight_agent_v3/v3_1_1.py
```

**Common patterns:**
```python
# V1:
async for chunk in agent.arun(message, stream=True):
    print(chunk)

# V2:
# (same interface, may have changed details)
async for chunk in agent.arun(message, stream=True):
    print(chunk)
```

**Test streaming:**
```bash
cd /banavo-agent-os
source setup_dev_env.sh
python -m pytest tests/test_v3_1_1_streaming.py -v
# (If test file exists)
```

**Deliverables:**
- [ ] Streaming handlers identified
- [ ] Updated to V2 patterns
- [ ] Streaming tests pass

---

### Task 2.5: Fix Tool Integration

**Check tools in AgentOS class:**
```bash
grep -n "\.tools\|get_tools" banavo/agent_os/versions/insight_agent_v3/v3_1_1.py
```

**V1 vs V2 tool patterns:**
```python
# V1:
agent = Agent(
    tools=[tool1, tool2, tool3],  # list of Tool objects or functions
)

# V2:
agent = Agent(
    tools=[tool1, tool2, tool3],  # same - list of Tool objects
)
```

**If using tool registry:**
```python
# from banavo.tools.registry import get_tools
# tools = get_tools(["kg_context", "athena_query"])
```

**Verify tool objects compatible:**
```bash
python -c "
from agno_custom.tools import Tool
from banavo.tools import some_tool
print(f'Tool type: {type(some_tool)}')
print(f'Has callable: {hasattr(some_tool, \"callable\")}')
"
```

**Deliverables:**
- [ ] Tool objects identified
- [ ] Compatible with V2 Tool system
- [ ] Tools execute without errors

---

### Task 2.6: Test v3_1_1 on Port 8000

**Create test script:** `/banavo-agent-os/test_v3_1_1.py`

```python
"""Test v3.1.1 on port 8000"""
import asyncio
import sys
from banavo.agent_os.versions.insight_agent_v3.v3_1_1 import AgentOS
from banavo.config import SETTINGS
from banavo.config.tenant.tenant_base import TenantBaseSettings

async def test_v3_1_1():
    """Test v3.1.1 agent initialization and query"""
    try:
        # Initialize agent
        tenant_config = TenantBaseSettings(
            AGENT_STORAGE_DB_URL=SETTINGS.AGENT_STORAGE_DB_URL,
            NEO4J_DB_NAME=SETTINGS.NEO4J_DB_NAME,
            ATHENA_DATABASE=SETTINGS.ATHENA_DATABASE,
            ATHENA_OUTPUT_LOCATION=SETTINGS.ATHENA_OUTPUT_LOCATION,
            ATHENA_REGION=SETTINGS.ATHENA_REGION,
            CURRENCY=SETTINGS.CURRENCY,
            DATA_TIMEZONE=SETTINGS.DATA_TIMEZONE,
            WEEK_START=SETTINGS.WEEK_START,
            WEEK_END=SETTINGS.WEEK_END,
            AGENT_DB_SCHEMA=SETTINGS.AGENT_DB_SCHEMA,
        )
        
        agent_os = AgentOS(config=tenant_config)
        print("✅ v3.1.1 Agent initialized successfully")
        
        # Run test query
        test_query = "What are our top products?"
        print(f"\nRunning query: {test_query}")
        
        # Stream response
        count = 0
        async for chunk in await agent_os.entry_point(message=test_query):
            print(f"Chunk {count}: {chunk[:100] if chunk else 'empty'}...")
            count += 1
        
        print(f"\n✅ v3.1.1 Query completed ({count} chunks)")
        return True
        
    except Exception as e:
        print(f"❌ v3.1.1 Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_v3_1_1())
    sys.exit(0 if success else 1)
```

**Run test:**
```bash
cd /banavo-agent-os
source setup_dev_env.sh
python test_v3_1_1.py
```

**Expected output:**
```
✅ v3.1.1 Agent initialized successfully

Running query: What are our top products?
Chunk 0: [response content]...
Chunk 1: [response content]...
...
✅ v3.1.1 Query completed (N chunks)
```

**Deliverables:**
- [ ] v3.1.1 initializes without errors
- [ ] Queries execute successfully
- [ ] Streaming works
- [ ] Ready for comparison testing

---

### Task 2.7: Compare v3.0.1 vs v3.1.1 Output

**Create comparison test:** `/banavo-agent-os/test_v3_comparison.py`

```python
"""Compare v3.0.1 (V1) vs v3.1.1 (V2) output"""
import asyncio
from banavo.agent_os.versions.insight_agent_v3.v3_0_1 import AgentOS as AgentOS_V1
from banavo.agent_os.versions.insight_agent_v3.v3_1_1 import AgentOS as AgentOS_V2
from banavo.config import SETTINGS
from banavo.config.tenant.tenant_base import TenantBaseSettings

async def test_comparison():
    """Run same query on both versions"""
    
    # Initialize config
    tenant_config = TenantBaseSettings(
        AGENT_STORAGE_DB_URL=SETTINGS.AGENT_STORAGE_DB_URL,
        NEO4J_DB_NAME=SETTINGS.NEO4J_DB_NAME,
        ATHENA_DATABASE=SETTINGS.ATHENA_DATABASE,
        ATHENA_OUTPUT_LOCATION=SETTINGS.ATHENA_OUTPUT_LOCATION,
        ATHENA_REGION=SETTINGS.ATHENA_REGION,
        CURRENCY=SETTINGS.CURRENCY,
        DATA_TIMEZONE=SETTINGS.DATA_TIMEZONE,
        WEEK_START=SETTINGS.WEEK_START,
        WEEK_END=SETTINGS.WEEK_END,
        AGENT_DB_SCHEMA=SETTINGS.AGENT_DB_SCHEMA,
    )
    
    # Test queries
    queries = [
        "What are our top 5 products?",
        "Show me Q1 revenue",
        "Customer churn analysis",
    ]
    
    try:
        # Initialize both versions
        print("Initializing v3.0.1 (V1)...")
        agent_v1 = AgentOS_V1(config=tenant_config)
        print("✓ v3.0.1 initialized")
        
        print("Initializing v3.1.1 (V2)...")
        agent_v2 = AgentOS_V2(config=tenant_config)
        print("✓ v3.1.1 initialized")
        
        # Run queries on both
        for query in queries:
            print(f"\n{'='*60}")
            print(f"Query: {query}")
            print(f"{'='*60}")
            
            # V1 query
            print("\nV1 (v3.0.1) response:")
            v1_response = ""
            async for chunk in await agent_v1.entry_point(message=query):
                v1_response += str(chunk)
            print(v1_response[:500] + "..." if len(v1_response) > 500 else v1_response)
            
            # V2 query
            print("\nV2 (v3.1.1) response:")
            v2_response = ""
            async for chunk in await agent_v2.entry_point(message=query):
                v2_response += str(chunk)
            print(v2_response[:500] + "..." if len(v2_response) > 500 else v2_response)
            
            # Simple comparison
            v1_len = len(v1_response)
            v2_len = len(v2_response)
            ratio = v2_len / v1_len if v1_len > 0 else 0
            
            print(f"\nComparison:")
            print(f"  V1 length: {v1_len} chars")
            print(f"  V2 length: {v2_len} chars")
            print(f"  Ratio: {ratio:.1%}")
            
            if 0.8 < ratio < 1.2:
                print("  ✓ Similar length (good parity)")
            else:
                print("  ⚠ Different length (check quality)")
        
        return True
        
    except Exception as e:
        print(f"❌ Comparison error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    asyncio.run(test_comparison())
```

**Run comparison:**
```bash
cd /banavo-agent-os
source setup_dev_env.sh
python test_v3_comparison.py
```

**Deliverables:**
- [ ] Comparison test created and runs
- [ ] V1 vs V2 output compared
- [ ] Quality verified (target: 90%+ parity)
- [ ] Differences documented

---

### Task 2.8: Phase 2 Completion

**Verify v3.1.1 fully migrated:**
```bash
# 1. Check file exists and is different from v3.0.1
ls -la banavo/agent_os/versions/insight_agent_v3/v3_1_1.py
diff banavo/agent_os/versions/insight_agent_v3/v3_0_1.py \
     banavo/agent_os/versions/insight_agent_v3/v3_1_1.py | head -50

# 2. Run test
source setup_dev_env.sh
python test_v3_1_1.py

# 3. Run comparison
python test_v3_comparison.py

# 4. Check no import errors
python -c "from banavo.agent_os.versions.insight_agent_v3.v3_1_1 import AgentOS; print('✓')"
```

**Deliverables:**
- [ ] v3.1.1 fully migrated to Agno V2
- [ ] All imports working
- [ ] Queries execute successfully
- [ ] Output quality verified (90%+ parity with v3.0.1)
- [ ] Streaming works
- [ ] Ready for Phase 3

---

## PHASE 3: Pattern Documentation

### Objective
Document migration patterns for other agents

---

### Task 3.1: Create MIGRATION_GUIDE.md

**File:** `/banavo-agent-os/MIGRATION_GUIDE_AGNO_V1_TO_V2.md`

**Content (from patterns learned in Phase 2):**

```markdown
# Agent Migration Guide: Agno V1 → V2

## Overview
This guide documents patterns discovered during v3.1.1 migration.
Use these patterns to migrate other agents.

## Patterns Discovered

### 1. Import Updates
From Phase 2, document specific changes needed...
(fill in after v3.1.1 migration)

### 2. API Changes
From Phase 2, document Agent/Team API changes...
(fill in after v3.1.1 migration)

### 3. Tool Integration
From Phase 2, document tool integration patterns...
(fill in after v3.1.1 migration)

### 4. Streaming Handlers
From Phase 2, document streaming changes...
(fill in after v3.1.1 migration)

## Checklist for Migrating New Agent

When migrating a new agent (e.g., v3.2.0, DataScienceAgent):

- [ ] Copy V1 version to new Vx.y.z file
- [ ] Update imports (see Patterns section)
- [ ] Update Agent/Team API calls (see Patterns section)
- [ ] Update streaming handlers (see Patterns section)
- [ ] Test on port 8000
- [ ] Compare output with V1 version
- [ ] Verify 90%+ parity
- [ ] Document any new patterns found

## Common Gotchas
(fill in as discovered)
```

**Deliverables:**
- [ ] MIGRATION_GUIDE.md created
- [ ] Patterns documented with examples
- [ ] Checklists provided
- [ ] Ready for team to use

---

### Task 3.2: Update Planning Documents

**Update:** `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/1_High-Level_Implementation_Plan_Agno_V1_to_V2.md`

Mark Phase 0-2 as complete:
```markdown
### Phase 0: Repository Extraction & Setup
- ✅ COMPLETE (DATE)
  - v2-upgrade_v2 branch created
  - agno_v2-migrate_v2 branch created
  - agno_custom extracted
  - v3.1.1 created

### Phase 1: Agno V2 Framework Upgrade
- ✅ COMPLETE (DATE)
  - Fork merged with V2
  - agno_custom V2-compatible
  - All imports working

### Phase 2: V3.1.1 Migration
- ✅ COMPLETE (DATE)
  - v3.1.1 migrated to V2
  - Output parity verified (90%+)
  - All tests passing

### Phase 3: Pattern Documentation
- ⏳ IN PROGRESS
  - MIGRATION_GUIDE.md created
  - Patterns documented
  - Checklists provided
```

**Deliverables:**
- [ ] Plans updated with completion dates
- [ ] Progress visible
- [ ] Team informed

---

### Task 3.3: Phase 3 Completion

**Verify documentation complete:**
```bash
# 1. Check MIGRATION_GUIDE exists
cat /banavo-agent-os/MIGRATION_GUIDE_AGNO_V1_to_V2.md

# 2. Check plan documents updated
grep "Phase 2" /Users/glaston.jiue/Desktop/Banavo/Agent_OS/1_High-Level_Implementation_Plan_Agno_V1_to_V2.md

# 3. Review all documentation
ls -la /banavo-agent-os/V3_VERSIONS.md
ls -la /agno/AGNO_CUSTOM_STRUCTURE.md
ls -la /Users/glaston.jiue/Desktop/Banavo/Agent_OS/REPOSITORY_STRUCTURE.md
```

**Deliverables:**
- [ ] All migration patterns documented
- [ ] Clear checklists for future agents
- [ ] Team can proceed with Phase 4
- [ ] Ready to migrate remaining agents

---

## PHASE 4+: Migrate Remaining Agents (Future)

Once v3.1.1 validation is complete and patterns documented, apply same approach to:

1. **v3.2.0** (optimized V2 version of insight agent)
2. **DataScienceAgent**
3. **SQLAgentV6, SQLAgentV7**
4. Other agents

Each following same pattern:
- Copy V1 version
- Update imports
- Update APIs
- Test
- Compare output
- Document patterns

---

## Summary

**3-Phase Approach:**

| Phase | Scope | Effort | Risk | Deliverable |
|-------|-------|--------|------|-------------|
| **0** | Extract agno_custom, setup branches | Low | Low | Clean repo structure |
| **1** | Upgrade /agno to V2 | Low | Low | V2.6.5 ready |
| **2** | Migrate v3.1.1 | Medium | Medium | Validated V2 agent |
| **3** | Document patterns | Low | Low | Migration guide |
| **4+** | Remaining agents | High | Medium | All agents on V2 |

**Timeline:** Phases 0-3 can complete in 2-3 weeks
**Phase 4+:** Depends on number of agents, can parallelize

---

**Ready to execute.**
