# REVIEW_LOG

## custom_retriever — v2.5 Review

Reviewed: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

## Framework Issues

[FRAMEWORK] agent/agent.py — `knowledge_retriever` parameter accepts `Callable[..., Optional[List[Union[Dict, str]]]]` but the cookbook examples show it can also receive `RunContext` as first arg via dependency injection. This pattern is not documented in the type signature.

---

## Cookbook Quality

[QUALITY] retriever.py / async_retriever.py — Both use Qdrant which requires a running Qdrant server. No fallback to in-memory Qdrant client is shown.

[QUALITY] retriever_with_dependencies.py — Excellent example of RunContext dependency injection. Shows how custom retrievers can access agent dependencies at runtime.

[QUALITY] All custom_retriever cookbooks — Missing docstrings explaining when to use `knowledge_retriever` vs standard `knowledge` parameter. Would benefit from a comparison note.

---

## Fixes Applied

No v2.5 compatibility fixes needed.
