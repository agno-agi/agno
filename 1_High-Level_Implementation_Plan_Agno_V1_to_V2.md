# High-Level Implementation Plan: Agno V1 → V2 Migration (Fresh Start)

**Test-First Approach: Insight Agent V3.1.1 as Proof-of-Concept**

---

## 📌 Overview

```
Goal: Upgrade Agno V1 to V2 with a focused, iterative approach

Approach:
  1. Extract agno_custom to private repo: /agno
  2. Upgrade agno framework to V2
  3. Create insight_agent_v3.1.1 (copy of v3.0.1) as test case
  4. Migrate v3.1.1 to Agno V2 (validate migration path)
  5. Apply lessons learned to remaining agents

Branches:
  - /agno: "v2-upgrade_v2"
  - /banavo-agent-os: "agno_v2-migrate_v2"

Locations:
  - /agno/agno_custom/ (extracted from banavo-agent-os)
  - /banavo-agent-os/banavo/agent_os/versions/insight_agent_v3/v3_1_1.py (new test case)
  - /banavo-agent-os/banavo/agent_os/versions/insight_agent_v3/v3_0_1.py (remains unchanged V1)
```

---

## 🏗️ Architecture

### **Current (V1)**
```
banavo-agent-os/
├── agno_custom/                    ← Custom extensions (embedded)
├── banavo/agent_os/versions/
│   └── insight_agent_v3/
│       └── v3_0_1.py              ← V1 Agno based
└── pyproject.toml (agno==1.6.2)
```

### **Target (V2 after migration)**
```
/agno/                              ← Private repo
├── agno_custom/                    ← Extracted, V2 compatible
├── pyproject.toml (agno>=2.6.5)
└── PYTHONPATH config

/banavo-agent-os/
├── banavo/agent_os/versions/
│   └── insight_agent_v3/
│       ├── v3_0_1.py              ← Original V1 (reference)
│       ├── v3_1_1.py              ← V2 migration test case
│       └── v3_2_0.py              ← (future) optimized V2 version
├── setup_dev_env.sh               ← Configure PYTHONPATH
└── pyproject.toml (agno>=2.6.5)
```

---

## 🎯 Key Strategy: Test-First with V3.1.1

**Why v3.1.1 first?**
- ✅ Single agent (simpler to debug)
- ✅ Complex enough to validate all patterns (tools, team, streaming)
- ✅ Can run side-by-side with v3.0.1 for comparison
- ✅ Lessons apply to all other agents
- ✅ Lower risk than migrating everything at once

**Migration Path:**
1. Extract agno_custom → /agno
2. Copy v3.0.1 → v3.1.1
3. Migrate v3.1.1 to V2 (fix import issues, API changes)
4. Test v3.1.1 on port 8000
5. Validate output quality matches v3.0.1
6. Document patterns discovered
7. Apply to remaining agents (v3_2_0, others)

---

## 📋 Phases

### **Phase 0: Repository Extraction & Setup**
Extract agno_custom and create v3.1.1 test case

**Tasks:**
- [ ] Create branches: `v2-upgrade_v2` (agno), `agno_v2-migrate_v2` (banavo-agent-os)
- [ ] Extract `/banavo-agent-os/agno_custom` → `/agno/agno_custom`
- [ ] Configure PYTHONPATH in setup_dev_env.sh
- [ ] Create v3.1.1 as copy of v3.0.1
- [ ] Update .gitignore in banavo-agent-os
- [ ] Document structure

**Output:** Clean repo separation, v3.1.1 ready for migration

---

### **Phase 1: Agno V2 Framework Upgrade**
Upgrade agno fork to V2.6.5

**Tasks (in /agno):**
- [ ] Merge Agno V2 base code from upstream
- [ ] Resolve merge conflicts
- [ ] Update agno_custom for V2 APIs
- [ ] Run validation tests
- [ ] Document breaking changes

**Output:** /agno on Agno V2.6.5, agno_custom V2-compatible

---

### **Phase 2: V3.1.1 V1 → V2 Migration**
Migrate insight_agent_v3.1.1 to Agno V2

**Tasks (in banavo-agent-os):**
- [ ] Analyze v3.0.1 code structure
- [ ] Fix import statements in v3.1.1 (from agno_custom V2)
- [ ] Update Agent/Team API calls (V1 → V2)
- [ ] Update streaming handlers
- [ ] Fix tool integration
- [ ] Test on port 8000

**Output:** v3.1.1 running on V2, quality validated against v3.0.1

---

### **Phase 3: Pattern Documentation**
Document migration patterns for other agents

**Tasks:**
- [ ] Create MIGRATION_GUIDE.md for agents
- [ ] Document API changes encountered
- [ ] Document tool integration patterns
- [ ] Document streaming patterns
- [ ] Create code examples

**Output:** Clear guide for migrating remaining agents

---

### **Phase 4: Migrate Remaining Agents**
Apply v3.1.1 patterns to other agents (future work)

**Tasks (future iterations):**
- [ ] v3_2_0 (optimized version)
- [ ] DataScienceAgent
- [ ] SQLAgentV6, SQLAgentV7
- [ ] Other agents

**Output:** All agents on V2

---

### **Phase 5: Production Deployment**
Deploy v3.1.1 and other agents to production (future work)

**Tasks:**
- [ ] Performance benchmarking
- [ ] Docker image update
- [ ] Staging deployment
- [ ] Canary rollout
- [ ] Production monitoring

**Output:** V2 agents in production

---

## 🗂️ File Changes Overview

### **New Branches**
```
agno repo:
└── branch: v2-upgrade_v2
    └── Agno V2.6.5 + agno_custom V2

banavo-agent-os repo:
└── branch: agno_v2-migrate_v2
    └── v3.1.1 (V2 version)
    └── setup_dev_env.sh (PYTHONPATH config)
    └── .gitignore (ignore local agno_custom)
```

### **Files Modified**
```
/banavo-agent-os/
├── setup_dev_env.sh               ← Configure PYTHONPATH to /agno
├── .gitignore                     ← Add /agno_custom
├── banavo/agent_os/versions/insight_agent_v3/
│   ├── v3_0_1.py                 ← Keep unchanged (reference)
│   └── v3_1_1.py                 ← New: V2 version
└── [other files: minimal changes]

/agno/
├── agno_custom/                   ← Extracted from banavo-agent-os
├── [Agno V2.6.5 framework]
└── pyproject.toml (agno>=2.6.5)
```

### **Files Deleted**
```
/banavo-agent-os/agno_custom/    ← Moved to /agno
```

---

## 🔑 Key Principles

1. **Test-First Approach**
   - Migrate v3.1.1 first, validate thoroughly
   - Document patterns before scaling to other agents
   - Minimize risk with single-agent migration

2. **Side-by-Side Comparison**
   - Keep v3.0.1 (V1) running
   - Compare v3.1.1 (V2) output on same queries
   - Validate quality/correctness before moving forward

3. **Clean Separation**
   - agno_custom lives in /agno (external repo)
   - banavo-agent-os stays clean, uses external agno_custom via PYTHONPATH
   - Easy to update both independently

4. **Minimal Risk**
   - Only v3.1.1 gets migrated first
   - Other agents stay on V1 initially
   - Can roll back v3.1.1 without affecting other agents

5. **Clear Documentation**
   - Document every change pattern
   - Create migration guide before scaling
   - Enable team to migrate other agents independently

---

## 📊 Phase Checklist

### **Phase 0: Repository Setup**
- [ ] v2-upgrade_v2 branch created in /agno
- [ ] agno_v2-migrate_v2 branch created in banavo-agent-os
- [ ] agno_custom extracted to /agno
- [ ] PYTHONPATH configured in setup_dev_env.sh
- [ ] v3.1.1 created (copy of v3.0.1)
- [ ] .gitignore updated
- [ ] Clean git state

### **Phase 1: Agno V2 Upgrade**
- [ ] Fork merged with V2 base code
- [ ] Merge conflicts resolved
- [ ] agno_custom compatible with V2 APIs
- [ ] Validation tests passing
- [ ] Breaking changes documented

### **Phase 2: V3.1.1 Migration**
- [ ] Imports fixed (agno_custom V2)
- [ ] Agent/Team APIs updated
- [ ] Streaming handlers updated
- [ ] Tools integrated
- [ ] v3.1.1 runs on port 8000
- [ ] Output quality verified
- [ ] Tests passing

### **Phase 3: Documentation**
- [ ] Migration guide created
- [ ] API changes documented
- [ ] Code examples provided
- [ ] Patterns identified

### **Phase 4+: Future Agents**
- (Deferred until v3.1.1 validation complete)

---

## 🚀 Success Criteria

**Phase 0 Complete:**
- ✅ Both branches exist with clean separation
- ✅ v3.1.1 ready for migration
- ✅ agno_custom extracted and accessible via PYTHONPATH

**Phase 1 Complete:**
- ✅ /agno on Agno V2.6.5
- ✅ All v2.6.5 validation tests pass
- ✅ Breaking changes documented

**Phase 2 Complete:**
- ✅ v3.1.1 imports and initializes on V2
- ✅ v3.1.1 runs queries successfully
- ✅ v3.1.1 output quality ≥ 90% match with v3.0.1
- ✅ No runtime errors on port 8000

**Phase 3 Complete:**
- ✅ Migration guide written and reviewed
- ✅ Team understands migration patterns
- ✅ Ready to scale to remaining agents

---

## 📈 Timeline

```
Week 1:
├─ Phase 0: Repository extraction (2 days)
└─ Phase 1: Agno V2 upgrade (3 days)

Week 2:
├─ Phase 2: v3.1.1 migration (5 days)
└─ Testing and validation (2 days)

Week 3:
├─ Phase 3: Documentation (3 days)
└─ Review and planning for next agents
```

**Estimate: 2-3 weeks to validate v3.1.1 on V2**

---

## 🎯 Next Steps

**Immediate (Today):**
1. ✅ Update plan documents (this document)
2. [ ] Create v2-upgrade_v2 branch in /agno
3. [ ] Create agno_v2-migrate_v2 branch in banavo-agent-os
4. [ ] Extract agno_custom to /agno
5. [ ] Configure setup_dev_env.sh
6. [ ] Create v3.1.1 (copy of v3.0.1)

**Then:**
- Proceed with Phase 1 (Agno V2 upgrade)
- Proceed with Phase 2 (v3.1.1 migration)
- Document patterns and validate

---

**Ready to execute.**
