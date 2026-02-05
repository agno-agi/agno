# TEST_LOG - Dynamic Knowledge Cookbooks

Manual test results for callable knowledge examples.

Last updated: 2026-02-05

## Test Environment

- Python: `.venvs/demo/bin/python`
- Model: `gpt-4o-mini` (OpenAI)

---

## 01_user_namespaced_knowledge.py

**Status:** NOT RUN

**Notes:** Requires `OPENAI_API_KEY` and `chromadb`. Run command:

```bash
VIRTUAL_ENV=.venvs/demo uv pip install chromadb
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/07_knowledge/dynamic_knowledge/01_user_namespaced_knowledge.py
```

---

## 02_multi_tenant_knowledge.py

**Status:** NOT RUN

**Notes:** Requires `OPENAI_API_KEY` and `chromadb`. Run command:

```bash
VIRTUAL_ENV=.venvs/demo uv pip install chromadb
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/07_knowledge/dynamic_knowledge/02_multi_tenant_knowledge.py
```

