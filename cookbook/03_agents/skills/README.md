# Agent Skills

**Skills** provide agents with structured domain expertise through instructions, scripts, and reference documentation.

> Skills are based on [Anthropic's Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) concept.

## What is a Skill?

A skill is a package containing:
- **SKILL.md**: Instructions for the agent (with YAML frontmatter)
- **scripts/**: Optional executable scripts
- **references/**: Optional reference documentation

## Creating a Skill

```
my-skill/
├── SKILL.md
├── scripts/
│   └── helper.py
└── references/
    └── docs.md
```

### SKILL.md Format

```markdown
---
name: my-skill
description: Short description of what this skill does
license: Apache-2.0
metadata:
  version: "1.0.0"
  author: your-name
  tags: ["tag1", "tag2"]
---
# Skill Instructions

Your detailed instructions here...

## When to Use This Skill

Describe when the agent should use this skill.

## Process

1. Step one
2. Step two
3. Step three
```

## Loading Skills

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.skills import Skills, LocalSkills

# Load skills from a directory
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    skills=Skills(loaders=[LocalSkills("/path/to/skills")])
)

# The agent now has access to:
# - get_skill_instructions(skill_name) - Load full instructions
# - get_skill_reference(skill_name, reference_path) - Load reference docs
# - get_skill_script(skill_name, script_path) - Load executable scripts
```

## How Skills Work

1. **System Prompt**: Available skills are listed in the agent's system prompt
2. **On-Demand Loading**: The agent calls `get_skill_instructions()` when it needs to use a skill
3. **Reference Access**: The agent can load detailed documentation via `get_skill_reference()`
4. **Script Access**: The agent can load executable code templates via `get_skill_script()`

This lazy-loading approach keeps the context window efficient while giving agents access to extensive domain knowledge.

## Examples

| Example | Description |
|---------|-------------|
| [basic_skills.py](./basic_skills.py) | Basic skill usage with `.print_response()` |

## Sample Skills

This cookbook includes sample skills in the `skills/` directory:

- **code-review**: Code review assistance with style checking and best practices
- **git-workflow**: Git workflow guidance with commit conventions

## AgentOS Integration

For deploying skills with AgentOS, see [cookbook/06_agent_os/skills/](../06_agent_os/skills/)
