# Test Log: 08_os_config

Tested on 2026-07-24 against Agno source commit
`37496c5ccd3be632cdbb97a9111a4a09999850fb`.

### config_basics.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the checked-in Python-configured AgentOS on
port 7787 (via the `AGENT_OS_PORT`/`AGENT_OS_BASE_URL` environment
overrides; the checked-in default is 7777),
then ran the checked-in `--demo` client against its health and configuration
routes.

**Result:** `GET /health` returned `ok`. `GET /config` returned OS ID
`python-config-os`, agent ID `operations-agent`, available model `gpt-5.5`,
both manifest labels, all three quick prompts, and the explicit
`os-config-db` session and memory domains named `Operations conversations` and
`Operations preferences`.

---

### yaml_config.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the checked-in YAML-configured AgentOS on
port 7787 (via the `AGENT_OS_PORT`/`AGENT_OS_BASE_URL` environment
overrides; the checked-in default is 7777),
then ran its checked-in `--demo` client.

**Result:** `GET /health` returned `ok`. `GET /config` preserved the YAML
manifest and `gpt-5.5` model list, linked `yaml-operations-agent` to the
registered Agent, and returned only the real `yaml-os-config-db` in the named
session and memory domains. The interface list was empty.

---

## Validation

- Both Python files imported and constructed their AgentOS apps with this
  worktree's `libs/agno` on `PYTHONPATH`.
- Recursive pattern validation checked exactly 2 Python files with 0
  violations.
- Targeted Ruff format and check passed.
- Stale-model, emoji, deprecated-interface, and non-PASS status scans returned
  no target hits.
- `git diff --check` passed for the lesson.
