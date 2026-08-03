# Test Log: 21_factories

Tested on 2026-07-24 against Agno source commit
`a7ffb023da5f99a1c43fe28a181e379d855831ba`.

Each file was booted as a standalone server on port 7777 with the rewrite
worktree on `PYTHONPATH`. Its `--demo` client then exercised discovery,
resolution, and a live model-backed run or the lesson's documented error path.

### 01_basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Resolved the same tenant factory twice, inspected the factory
metadata, and ran the produced Agent through the REST API.

**Result:** `/health` returned `ok`; discovery returned
`tenant-assistant` with `is_factory=true` and database
`basic-factory-db`. Both resolutions produced distinct objects, overrode the
component ID, inherited the factory database, and enabled event storage. Run
`4239b315-a074-4dcd-819b-ccef10aa1e9b` completed and identified tenant `mira`.

---

### 02_with_input_schema.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Discovered the generated input schema, ran valid typed input,
and sent an out-of-range depth that must fail before construction.

**Result:** Discovery exposed exactly `depth` and `persona`. Valid run
`f9a2972f-fc77-4ed6-b460-9288dba5453c` completed with the requested two-point
skeptic configuration. Depth `99` returned HTTP 400 with
`factory_input validation failed`.

---

### 03_with_jwt_rbac.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Signed local JWTs for viewer, admin, and unsupported roles,
then checked both resolved tools and REST authorization behavior.

**Result:** The viewer received only `list_documents`; the admin also received
`invite_member`. Viewer run `34d640da-887c-4c74-b77c-7ed367621ed7` and admin
run `867eb94a-988e-4c05-ba51-f5fc17c60fe1` completed. The unsupported role
raised `FactoryPermissionError` and returned HTTP 403 without reaching a model.

---

### 04_tiered_model.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Resolved model policy from verified tier claims and called
the enterprise configuration through the authenticated run route.

**Result:** Standard resolved to `gpt-5.5` with low reasoning effort;
enterprise resolved to `gpt-5.5` with high effort. Enterprise run
`9052ae8b-140c-4b77-976b-6cb4fbc0b50d` completed.

---

### 05_team_factory.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Resolved and discovered the Team factory, then ran its billing
and technical specialists for one tenant.

**Result:** Discovery returned `tenant-support-team` with
`is_factory=true`. The resolved Team had two members, the factory database, and
event storage. Run `8d29be69-197d-4655-a012-7b69405d1dc7` completed with a
duplicate-invoice diagnosis that retained tenant `acme`.

---

### 06_workflow_factory.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Resolved and discovered the Workflow factory, then executed
its draft-and-edit pipeline for one tenant.

**Result:** Discovery returned `tenant-content-pipeline` with
`is_factory=true`. The resolved Workflow had two steps, the factory database,
and event storage. Run `3ab1f710-0e71-4577-b145-d7fb00ae13ea` completed with an
edited launch update that retained tenant `acme`.

---

### 07_async_factory.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Registered one synchronous and one asynchronous AgentFactory,
verified callable detection, and ran both through the same REST contract.

**Result:** The sync callable was detected as synchronous and the async
callable as asynchronous. Runs `a4aab34a-0b85-4a5c-8ad4-1b319d87b9eb` and
`dc9e896f-4b73-4b09-822f-d0fbebdf12ac` both completed and retained user
`mira`.

---

## Validation

- All 7 standalone servers returned HTTP 200 from `/health`.
- All 7 examples passed a real capability-specific `--demo` flow.
- The focused factory unit module passed all 23 tests.
- Recursive pattern validation checked exactly 7 Python files with 0
  violations.
- Targeted Ruff format and check, Python compilation, inventory parity, and
  `git diff --check` passed.
- The legacy nested `factories/` curriculum was fully consumed or deleted.
