### check_cookbook_pattern.py

**Status:** PASS

**Description:** Ran `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/observability --recursive` to validate module docstrings, section banners, create/run section order, main gates, and emoji rules.

**Result:** Validation passed with zero violations. Runtime execution of individual cookbook scripts was not performed in this pass.

---

### langfuse_via_setup_tracing.py

**Status:** PASS

**Description:** Verified the setup section: importing the module configures a global tracer provider with an OTLPSpanExporter attached via setup_tracing(exporters=[...]) and instruments Agno automatically. Full agent run against Langfuse was not performed (no LANGFUSE credentials in the test environment).

**Result:** Tracer provider configured with OTLPSpanExporter as expected.

---

### trace_to_database_and_langfuse.py

**Status:** PASS

**Description:** Verified the setup section: importing the module attaches both DatabaseSpanExporter and OTLPSpanExporter to the same tracer provider via setup_tracing(db=..., exporters=[...]). Separately verified with a fake exporter that both destinations receive the same spans with the same trace_id and that repeated setup_tracing() calls do not duplicate processors. Full agent run against Langfuse was not performed (no LANGFUSE credentials in the test environment).

**Result:** Both exporters attached to a single tracer provider; identical trace_id confirmed across destinations.

---

### mlflow_via_setup_tracing.py

**Status:** PASS

**Description:** Started a local MLflow 3.14.0 server (mlflow server --port 5001, sqlite backend), loaded the cookbook's setup section with MLFLOW_TRACKING_URI pointing at it, emitted a test span through the tracer provider configured by setup_tracing(exporters=[OTLPSpanExporter(...)]), and queried MLflow via mlflow.search_traces(). The trace arrived with state OK and the MLflow trace_id (tr-<id>) matched the emitted OTel trace_id. Full agent run was not performed (no OPENAI_API_KEY in the test environment).

**Result:** OTLP export to MLflow verified end-to-end; trace ingested and queryable.

---

### arize_phoenix_via_setup_tracing.py

**Status:** PASS

**Description:** Verified the setup section: importing the module attaches both DatabaseSpanExporter and OTLPSpanExporter (pointed at the Phoenix collector endpoint, with Bearer auth headers) to the same tracer provider via setup_tracing(db=..., exporters=[...]). Full agent run against Phoenix was not performed (no PHOENIX_API_KEY in the test environment).

**Result:** Both exporters attached to a single tracer provider as expected.

---
