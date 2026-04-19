# Factories -- Test Log

## Agent Factories

### agent/01_basic_factory.py

**Status:** PENDING

**Description:** Basic per-tenant agent factory alongside a static prototype agent.

---

### agent/02_input_schema_factory.py

**Status:** PENDING

**Description:** Factory with pydantic input schema for client-controlled persona and depth parameters.

---

### agent/03_jwt_role_factory.py

**Status:** PENDING

**Description:** JWT-driven RBAC factory that grants tools based on the caller's verified role claim.

---

### agent/04_tiered_model_factory.py

**Status:** PENDING

**Description:** Model selection based on subscription tier (free/pro/enterprise).

---

## Team Factories

### team/01_basic_team_factory.py

**Status:** PENDING

**Description:** Per-tenant support team with billing and tech support members.

---

### team/02_tiered_team_factory.py

**Status:** PENDING

**Description:** Team size and model quality scale with subscription tier.

---

## Workflow Factories

### workflow/01_basic_workflow_factory.py

**Status:** PENDING

**Description:** Per-tenant content pipeline workflow (draft + edit steps).

---

### workflow/02_tiered_workflow_factory.py

**Status:** PENDING

**Description:** Pipeline depth scales with subscription tier (2 vs 3 steps).

---
