# skills

Examples for defining and using agent skills and helper scripts.

## Files
- `basic_skills.py` - Demonstrates basic skills.
- `sample_skills/code-review/scripts/check_style.py` - Demonstrates check style.
- `sample_skills/git-workflow/scripts/commit_message.py` - Demonstrates commit message.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
