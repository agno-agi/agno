# Agent Skills - Design Document

## Executive Summary

Agent Skills are a first-class primitive in Agno that give agents access to structured instructions, reference documentation, and executable scripts. Skills provide a standardized way to teach agents domain expertise and workflows that can be versioned, shared, and evolved.

**Key Differentiator**: While other platforms only support file-based skills, Agno supports database-backed skills with automatic persistence, enabling version control, deduplication, and enterprise-grade skill governance.

---

## Developer Experience (DX)

### Recommended Usage (V1)

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.skills import Skills, LocalSkills
from agno.db.sqlite import SqliteDb

# Create database for persistence
agent_db = SqliteDb(
    db_file="agent.db",
    skill_table="agno_skills",
    session_table="agno_sessions",
)

# Create an agent with skills
agent = Agent(
    name="Code Assistant",
    model=OpenAIChat(id="gpt-4o"),
    skills=Skills(
        loaders=[
            LocalSkills("./skills"),           # All skills in directory
            LocalSkills("./skills/pdf-tool"),  # Single skill folder
        ],
        db=agent_db,  # Optional, falls back to Agent's db
    ),
    db=agent_db,
)

# Agent now has access to all loaded skills
response = agent.run("Review this pull request following our coding standards")
```

### Multiple Skill Sources

```python
from agno.skills import Skills, LocalSkills

agent = Agent(
    name="Enterprise Assistant",
    model=OpenAIChat(id="gpt-4o"),
    skills=Skills(
        loaders=[
            LocalSkills("./company-skills"),   # Company-specific skills
            LocalSkills("./team-skills"),      # Team-specific skills
        ],
        db=agent_db,
    ),
    db=agent_db,
)
```

### DB Fallback

If `AgentSkills` doesn't have a `db` parameter, it will automatically use the Agent's `db` when attached:

```python
# AgentSkills will use agent_db for persistence
agent_skills = Skills(loaders=[LocalSkills("./skills")])  # No db

agent = Agent(
    name="Code Assistant",
    skills=agent_skills,
    db=agent_db,  # AgentSkills will fall back to this
)
```

### Legacy API (Deprecated)

The old `SkillsDir` provider is still supported for backward compatibility:

```python
from agno.skills import SkillsDir

# Deprecated - use AgentSkills with LocalSkills instead
agent = Agent(
    name="Code Assistant",
    skills=[SkillsDir(path="./skills")],  # Old API
)
```

### Skill Directory Structure

```
./skills/
├── code-review/
│   ├── SKILL.md              # Required: metadata + instructions
│   ├── scripts/              # Optional: executable automation
│   │   ├── run_linter.py
│   │   └── format_code.sh
│   └── references/           # Optional: detailed documentation
│       ├── style-guide.md
│       └── error-codes.md
├── git-workflow/
│   ├── SKILL.md
│   └── scripts/
│       └── commit_helper.sh
└── api-design/
    ├── SKILL.md
    └── references/
        └── openapi-spec.md
```

### Example SKILL.md

```yaml
---
name: code-review
description: Code review assistance with linting, style checking, and best practices
license: Apache-2.0
metadata:
  version: "1.2.0"
  author: engineering-team
  tags: ["quality", "review", "linting"]
---
# Code Review Skill

You are a code review assistant. When reviewing code, follow these steps:

## Review Process
1. **Run Linter**: Use `run_skill_script("code-review", "run_linter.py")` to check for issues
2. **Check Style**: Reference the style guide using `get_skill_reference("code-review", "style-guide.md")`
3. **Provide Feedback**: Give structured feedback with severity levels

## Feedback Format
- **Critical**: Must fix before merge
- **Important**: Should fix, but not blocking
- **Suggestion**: Nice to have improvements

## Available Scripts
- `run_linter.py [--fix]` - Run linter with optional auto-fix
- `format_code.sh` - Format code to match style guide
```

---

## Tools the Agent Gets

When `skills` is provided, the agent automatically receives these tools:

### 1. `get_skill_instructions(skill_name: str) -> str`

Loads the full SKILL.md body (instructions) for a skill.

```python
# Agent calls this when it needs detailed instructions
result = get_skill_instructions("code-review")

# Returns:
{
  "skill_name": "code-review",
  "description": "Code review assistance with linting...",
  "instructions": "# Code Review Skill\n\nYou are a code review assistant...",
  "available_scripts": ["run_linter.py", "format_code.sh"],
  "available_references": ["style-guide.md", "error-codes.md"]
}
```

### 2. `get_skill_reference(skill_name: str, reference_path: str) -> str`

Loads a reference document from a skill's `references/` directory.

```python
# Agent calls this to get detailed documentation
result = get_skill_reference("code-review", "style-guide.md")

# Returns:
{
  "skill_name": "code-review",
  "reference_path": "style-guide.md",
  "content": "# Code Style Guide\n\n## Naming Conventions\n..."
}
```

### 3. `run_skill_script(skill_name: str, script_name: str, args: List[str]) -> str`

Executes a script from a skill's `scripts/` directory.

```python
# Agent calls this to run automation
result = run_skill_script("code-review", "run_linter.py", ["--fix", "src/"])

# Returns:
{
  "skill_name": "code-review",
  "script_name": "run_linter.py",
  "return_code": 0,
  "stdout": "Fixed 3 linting issues in 2 files",
  "stderr": "",
  "success": true
}
```

---

## System Prompt Integration

Skills use **progressive disclosure** to minimize token usage:

### What Goes in System Prompt (~50-100 tokens per skill)

```xml
<available_skills>
<skill>
  <name>code-review</name>
  <description>Code review assistance with linting, style checking, and best practices</description>
  <scripts>run_linter.py, format_code.sh</scripts>
  <references>style-guide.md, error-codes.md</references>
</skill>
<skill>
  <name>git-workflow</name>
  <description>Git workflow automation and commit message helpers</description>
  <scripts>commit_helper.sh</scripts>
</skill>
</available_skills>

You have access to skills that provide domain expertise. Use the get_skill_instructions tool
to load full instructions when you need to use a skill. Use get_skill_reference to access
detailed documentation, and run_skill_script to execute automation scripts.
```

### Agent Workflow

1. Agent sees available skills in system prompt (metadata only)
2. When task matches a skill, agent calls `get_skill_instructions("skill-name")`
3. Agent follows the loaded instructions
4. Agent uses `get_skill_reference()` for detailed docs if needed
5. Agent uses `run_skill_script()` for automation if available

---

## Database Persistence

### SkillRow Schema

Skills are persisted to the database using the `SkillRow` schema:

```python
class SkillRow(BaseModel):
    id: str                    # Auto-generated from content_hash
    name: str                  # Unique skill name
    description: str
    instructions: str
    license: Optional[str]
    compatibility: Optional[str]
    metadata: Optional[Dict]   # version, author, tags, etc.
    allowed_tools: Optional[str]
    scripts: List[str]         # Script filenames
    references: List[str]      # Reference filenames
    source_type: str           # "local" (future: "github", "url")
    source_path: str           # Filesystem path
    content_hash: str          # SHA256 for deduplication
    created_at: int
    updated_at: int
```

### How Persistence Works

1. **On Load**: When `AgentSkills` loads skills from loaders, each skill is:
   - Converted to a `SkillRow`
   - Content-hashed for deduplication
   - Upserted to the database

2. **Deduplication**: Skills with the same content hash are not duplicated

3. **DB Fallback**: If `AgentSkills.db` is `None`, it uses the Agent's `db` when attached

---

## Examples

### Example 1: Code Review Agent

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.skills import Skills, LocalSkills
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="agent.db", skill_table="skills", session_table="sessions")

code_review_agent = Agent(
    name="Code Reviewer",
    model=OpenAIChat(id="gpt-4o"),
    skills=Skills(loaders=[LocalSkills("./skills")], db=db),
    instructions=["You are a senior code reviewer. Use available skills to provide thorough reviews."],
    db=db,
)

# User asks for a code review
response = code_review_agent.run("""
Review this Python function:

def calc(x, y):
    return x + y
""")

# Agent workflow:
# 1. Sees "code-review" skill available
# 2. Calls get_skill_instructions("code-review")
# 3. Follows review process from instructions
# 4. Calls run_skill_script("code-review", "run_linter.py") on the code
# 5. Checks get_skill_reference("code-review", "style-guide.md") for naming conventions
# 6. Returns structured feedback
```

### Example 2: DevOps Agent with Multiple Skills

```python
from agno.agent import Agent
from agno.skills import Skills, LocalSkills

devops_agent = Agent(
    name="DevOps Assistant",
    model=Claude(id="claude-sonnet-4-5-20250929"),
    skills=Skills(
        loaders=[LocalSkills("./devops-skills")],  # Contains: docker, k8s, ci-cd
    ),
    db=agent_db,
)

response = devops_agent.run("Deploy the new version to staging")

# Agent can use:
# - docker skill for building images
# - k8s skill for deployment manifests
# - ci-cd skill for pipeline triggers
```

### Example 3: Customer Support Agent

```python
from agno.agent import Agent
from agno.skills import AgentSkills, LocalSkills

support_agent = Agent(
    name="Support Agent",
    model=OpenAIChat(id="gpt-4o"),
    skills=AgentSkills(loaders=[LocalSkills("./support-skills")]),
    db=agent_db,
)

# ./support-skills/
# ├── troubleshooting/
# │   ├── SKILL.md
# │   └── references/
# │       ├── common-issues.md
# │       └── escalation-guide.md
# └── refunds/
#     ├── SKILL.md
#     └── scripts/
#         └── process_refund.py

response = support_agent.run("Customer wants a refund for order #12345")

# Agent loads refund skill instructions
# Follows refund policy from skill
# Can run process_refund.py script if authorized
```

---

## Architecture

### V1 Architecture (Current)

```
                    ┌─────────────────┐
                    │  SkillLoader    │  (Abstract Base Class)
                    │     (ABC)       │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
    ┌─────────────────┐ ┌─────────────┐ ┌─────────────┐
    │  LocalSkills    │ │ GitHubSkills│ │  URLSkills  │
    │    (V1)         │ │   (V2)      │ │    (V2)     │
    └─────────────────┘ └─────────────┘ └─────────────┘
    │                   │              │
    │ path="./skills"   │ repo="x/y"   │ url="..."
    │                   │              │
    └───────────────────┴──────────────┘
                    │
                    ▼
            ┌───────────────┐
            │  AgentSkills  │
            │ (orchestrator │
            │  + toolkit)   │
            └───────────────┘
                    │
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
    ┌───────────┐       ┌───────────┐
    │  BaseDb   │       │   Agent   │
    │(persist)  │       │ (tools)   │
    └───────────┘       └───────────┘
```

### Key Components

| Component | Purpose |
|-----------|---------|
| `SkillLoader` | Abstract base class for loaders |
| `LocalSkills` | Loads skills from filesystem |
| `AgentSkills` | Main orchestrator - loads, persists, provides tools |
| `SkillRow` | Database schema for skill persistence |
| `Skill` | In-memory skill representation |

---

## Implementation Status

### V1 (Implemented)

| Feature | Status |
|---------|--------|
| `LocalSkills` loader | Done |
| `AgentSkills` orchestrator | Done |
| DB persistence (SqliteDb) | Done |
| 3 agent tools | Done |
| Content hash deduplication | Done |
| DB fallback to Agent's db | Done |
| Backward compat with `SkillsDir` | Done |

### V2 (Deferred)

| Feature | Status |
|---------|--------|
| `GitHubSkills` loader | Planned |
| `URLSkills` loader | Planned |
| Loading strategies (bootstrap, sync, eager, db_only) | Planned |
| Context management (max_active, pinned) | Planned |
| Script sandbox | Planned |
| Agent learning (allow_create, allow_update) | Planned |

---

## Files

### Created (V1)

| File | Purpose |
|------|---------|
| `libs/agno/agno/skills/agent_skills.py` | Main AgentSkills orchestrator |
| `libs/agno/agno/db/schemas/skill.py` | SkillRow database schema |
| `libs/agno/agno/skills/loaders/__init__.py` | Loader exports |
| `libs/agno/agno/skills/loaders/base.py` | SkillLoader ABC |
| `libs/agno/agno/skills/loaders/local.py` | LocalSkills implementation |

### Modified (V1)

| File | Change |
|------|--------|
| `libs/agno/agno/db/base.py` | Added skill CRUD methods |
| `libs/agno/agno/db/sqlite/sqlite.py` | Implemented skill methods |
| `libs/agno/agno/db/sqlite/schemas.py` | Added SKILL_TABLE_SCHEMA |
| `libs/agno/agno/agent/agent.py` | Accept AgentSkills + backward compat |
| `libs/agno/agno/skills/__init__.py` | Updated exports |

### Existing (Unchanged)

| File | Purpose |
|------|---------|
| `libs/agno/agno/skills/skill.py` | Skill dataclass + parsing |
| `libs/agno/agno/skills/provider.py` | Legacy SkillsProvider + SkillsDir |
| `libs/agno/agno/skills/toolkit.py` | Legacy SkillsToolkit |
| `libs/agno/agno/skills/exceptions.py` | Skill exceptions |

---

## Future Evolution: Platform UI Integration

### Phase 2: Additional Loaders

```python
from agno.skills import Skills, LocalSkills, GitHubSkills, URLSkills

agent = Agent(
    skills=Skills(
        loaders=[
            LocalSkills("./skills"),
            GitHubSkills(repo="company/agent-skills", branch="main"),
            URLSkills(url="https://skills.company.com/api/skills"),
        ],
        db=agent_db,
    ),
)
```

### Phase 3: Agno Platform UI

**Skills Management Page:**
```
┌─────────────────────────────────────────────────────────────────┐
│  AGNO PLATFORM  │  Skills  │  Agents  │  Analytics             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  📦 Skills Library                          [+ Create Skill]    │
│  ─────────────────────────────────────────────────────────────  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 📋 code-review                              v2.1.0       │   │
│  │ Code review assistance with linting and style checking   │   │
│  │ Used by: 3 agents  │  Last updated: 2 days ago          │   │
│  │ [Edit] [Version History] [Assign to Agents]              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 🔄 git-workflow                             v1.5.0       │   │
│  │ Git workflow automation and commit helpers               │   │
│  │ Used by: 5 agents  │  Last updated: 1 week ago          │   │
│  │ [Edit] [Version History] [Assign to Agents]              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Skill Editor:**
```
┌─────────────────────────────────────────────────────────────────┐
│  Edit Skill: code-review                    [Save] [Publish]    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Name: [code-review          ]  Version: [2.1.0]               │
│  Description: [Code review assistance with linting...]          │
│                                                                  │
│  ┌─ Instructions ──────────────────────────────────────────┐   │
│  │ # Code Review Skill                                      │   │
│  │                                                          │   │
│  │ You are a code review assistant. Follow these steps:     │   │
│  │ 1. Run the linter first                                  │   │
│  │ 2. Check against style guide                             │   │
│  │ ...                                                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ Scripts ─────────────────────────────┐  ┌─ References ───┐ │
│  │ + run_linter.py                       │  │ + style-guide  │ │
│  │ + format_code.sh                      │  │ + error-codes  │ │
│  │ [+ Add Script]                        │  │ [+ Add Ref]    │ │
│  └───────────────────────────────────────┘  └────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Agent Builder Integration:**
```
┌─────────────────────────────────────────────────────────────────┐
│  Agent Builder: Code Review Bot                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Model: [Claude Sonnet 4.5      ▼]                             │
│                                                                  │
│  ┌─ Assigned Skills ────────────────────────────────────────┐   │
│  │                                                           │   │
│  │  ☑ code-review        v2.1.0  (latest)                   │   │
│  │  ☑ git-workflow       v1.5.0  (latest)                   │   │
│  │  ☐ api-design         v1.0.0                             │   │
│  │                                                           │   │
│  │  [+ Add Skill from Library]                              │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Version Pinning:                                               │
│  ○ Always use latest version                                    │
│  ● Pin to specific versions (recommended for production)        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Skills Analytics Dashboard:**
```
┌─────────────────────────────────────────────────────────────────┐
│  Skills Analytics                                [Last 30 days] │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  📊 Usage Overview                                              │
│  ─────────────────────────────────────────────────────────────  │
│                                                                  │
│  Total Skill Invocations: 12,450                                │
│  Unique Skills Used: 8                                          │
│  Most Used: code-review (4,230 calls)                          │
│                                                                  │
│  ┌─ Skill Performance ─────────────────────────────────────┐   │
│  │                                                          │   │
│  │  code-review    ████████████████████  4,230  (92% ✓)    │   │
│  │  git-workflow   ██████████████        2,890  (88% ✓)    │   │
│  │  api-design     ████████              1,650  (95% ✓)    │   │
│  │  refunds        ██████                1,200  (78% ✓)    │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ Script Execution Stats ────────────────────────────────┐   │
│  │                                                          │   │
│  │  Script              Runs    Success   Avg Time         │   │
│  │  run_linter.py       1,890   98.2%     2.3s             │   │
│  │  format_code.sh      1,240   99.1%     1.1s             │   │
│  │  process_refund.py     450   94.5%     4.7s             │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### UI-Enabled Capabilities

| Capability | File System (V1) | Database + UI (V3) |
|------------|------------------|-------------------|
| Version control | Git | Built-in versioning |
| Rollback | Git revert | One-click rollback |
| A/B testing | Manual | UI-driven experiments |
| Access control | File permissions | Role-based UI |
| Analytics | None | Usage metrics, success rates |
| Collaboration | PRs | Real-time editing |
| Audit trail | Git log | Full audit history |
| Cross-agent sharing | Copy files | Click to assign |
| Skill discovery | Browse folders | Searchable library |
| Version pinning | Manual | UI toggle per agent |

### Platform API (V3)

The platform will expose a Skills API for programmatic management:

```python
from agno.platform import AgnoClient

client = AgnoClient(api_key="...")

# List all skills in the platform
skills = client.skills.list()

# Create a new skill
skill = client.skills.create(
    name="new-skill",
    description="A new skill",
    instructions="# Instructions\n...",
    scripts=["script.py"],
)

# Assign skill to an agent
client.agents.assign_skill(agent_id="agent-123", skill_id=skill.id)

# Get skill analytics
analytics = client.skills.analytics(skill_id=skill.id, period="30d")
```

### Agent-Side Platform Integration

```python
from agno.agent import Agent
from agno.skills import AgentSkills, PlatformSkills

# Load skills from Agno Platform (V3)
agent = Agent(
    name="Enterprise Agent",
    skills=AgentSkills(
        loaders=[
            PlatformSkills(
                api_key="...",
                skill_ids=["code-review", "git-workflow"],  # Specific skills
                # OR
                tags=["engineering", "devops"],              # By tags
                # OR
                all=True,                                    # All assigned skills
            ),
        ],
    ),
)
```

---

## Summary

**V1 (Current):**
- `skills=AgentSkills(loaders=[LocalSkills("./skills")], db=agent_db)`
- File-based loading with DB persistence
- 3 tools: get_skill_instructions, get_skill_reference, run_skill_script
- Progressive disclosure for token efficiency
- Backward compatible with old `SkillsDir` API

**V2 (Planned):**
- GitHub and URL loaders
- Loading strategies and context management
- Script sandbox
- Agent learning capabilities

**V3 (Future - Platform UI):**
- Full UI for skill management
- Version control and rollback
- A/B testing and analytics
- Role-based access control
- Cross-agent skill sharing
- Platform API for programmatic management
- **This is where Agno differentiates from every other platform**
