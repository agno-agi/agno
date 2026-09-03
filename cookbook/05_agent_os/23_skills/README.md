# Skills

`LocalSkills` loads validated skill packages from disk. `Skills` combines one
or more loaders and gives an Agent three tools for reading instructions,
reading references, and reading or executing scripts. This lesson serves that
Agent through AgentOS and verifies a real skill-script execution through the
run API.

## Files

| File | What it teaches |
|---|---|
| `README.md` | Lesson setup, execution flow, and local-skill contract. |
| `TEST_LOG.md` | Direct-script, live AgentOS, and focused validation evidence. |
| `basic.py` | Serve a skills Agent and run the end-to-end HTTP proof with `--demo`. |
| `sample_skills/system-info/SKILL.md` | Define validated skill metadata and model-facing instructions. |
| `sample_skills/system-info/scripts/get_system_info.py` | Return host and Python runtime facts as JSON. |
| `sample_skills/system-info/scripts/list_directory.py` | Return a sorted one-level directory inventory as JSON. |

## Run the AgentOS lesson

Set up the demo environment and export the provider key:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
```

Start the server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/23_skills/basic.py
```

In another terminal, run the proof client:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/23_skills/basic.py --demo
```

The client checks `/health` and `/config`, sends a non-streaming request to
`POST /agents/skills-agent/runs`, and rejects the response unless the recorded
tool sequence includes:

1. `get_skill_instructions` for `system-info`;
2. `get_skill_script` for `get_system_info.py` with `execute=True`; and
3. a zero return code plus valid JSON in the script's `stdout`.

Use `AGENT_OS_PORT` to move the server from port `7777` and
`AGENT_OS_BASE_URL` to point the demo client at that port.

## Run the scripts directly

Both scripts are standalone executables as well as Agent skill resources:

```bash
.venvs/demo/bin/python \
  cookbook/05_agent_os/23_skills/sample_skills/system-info/scripts/get_system_info.py

.venvs/demo/bin/python \
  cookbook/05_agent_os/23_skills/sample_skills/system-info/scripts/list_directory.py \
  cookbook/05_agent_os/23_skills/sample_skills/system-info
```

Each successful command exits `0` and writes one JSON document. The directory
script writes a JSON error to standard error and exits nonzero if the supplied
path cannot be read.

## Local skill contract

Point `LocalSkills` at either one skill directory or a parent containing
multiple skill directories. Validation is enabled by default, so each skill
must contain a valid `SKILL.md` whose lowercase `name` matches its directory.
Wrapping the loader in `Skills` eagerly loads the packages and registers the
three skill tools on the Agent.

Script names are resolved only from the skill's `scripts/` directory. Execution
uses the skill directory as the working directory, rejects traversal outside
that package, and returns structured `stdout`, `stderr`, and `returncode`
fields. Treat loaded skills as executable code: review and control who can
write them before enabling script execution in a production AgentOS.
