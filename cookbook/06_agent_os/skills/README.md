# Skills with AgentOS

This example demonstrates deploying an agent with skills using AgentOS.

## Overview

Skills provide agents with structured domain expertise through instructions, scripts, and reference documentation. This example shows how to serve a skilled agent via AgentOS.

## Running the Example

```bash
cd cookbook/06_agent_os/skills
python agent_with_local_skill.py
```

This starts an AgentOS server with a skilled agent that can:
- Review code using the `code-review` skill
- Follow git workflows using the `git-workflow` skill

## Skills Location

The sample skills are located in `cookbook/15_skills/skills/` and are shared with the regular skills cookbook examples.

## Learn More

- [Skills Cookbook](../../15_skills/) - Regular skills examples with `.print_response()`
- [Skills from Database](../../15_skills/skills_from_db.py) - Example with Local + Database skills via AgentOS
