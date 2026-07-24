# AgentOS Cookbook Test Prompt

Validate the current phase of `cookbook/05_agent_os` against `AGENTS.md`,
`cookbook/STYLE_GUIDE.md`, and the rewrite specification. Phase 0 covers only
the deterministic migrations and deletions; the numbered lesson-by-lesson
testing playbook replaces this file in Phase 1.

## Environment

- Cookbook Python: `.venvs/demo/bin/python`
- Development checks: `.venv`
- Optional environment loading: `direnv allow`

## Phase 0 checks

1. Read every changed Python file and its owning README and TEST_LOG.
2. Run the recursive cookbook pattern checker over each changed destination:

   ```bash
   .venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
     --base-dir <changed-directory> --recursive
   ```

3. Execute credentials-free examples. For credential-gated examples, import
   the module, construct the integration or app, and verify the expected route
   or client object. Record `Status: PASS` and the observed behavior; label
   credential-gated checks `Test mode: CONSTRUCTION_SMOKE`.
4. Confirm deleted paths are absent and surviving READMEs and TEST_LOGs do not
   reference them.
5. Run `./scripts/format.sh`, `./scripts/validate.sh`, and `git diff --check`
   from the Agno development environment.

Do not report a final FAIL, MANUAL, PENDING, or unexecuted test as success.
