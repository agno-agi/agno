# Agent Skills with AgentOS

This example demonstrates how to deploy an agent with skills using AgentOS.

## Running the Example

```bash
# Start the server
python cookbook/06_agent_os/skills/agent_with_local_skill.py
```

## What This Example Shows

- Loading skills from a local directory using `LocalSkills`
- Integrating skills with an agent served via AgentOS
- The agent has access to `get_skill_instructions`, `get_skill_reference`, and `get_skill_script` tools

## Sample Skills Included

The skills are loaded from `cookbook/15_skills/skills/`:
- **code-review**: Code review assistance with style guide references
- **git-workflow**: Git workflow guidance with commit type references
