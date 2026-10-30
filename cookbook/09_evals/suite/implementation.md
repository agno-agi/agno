# AgentOS eval suites

- [x] Add validated suite and case HTTP input schemas.
- [x] Run the existing async suite runner against authorized, isolated agent/team copies.
- [x] Persist aggregate reports in existing eval storage; support sync and async databases.
- [x] Add suite execution, list, and detail routes with eval scopes and user isolation.
- [x] Add frontend suite creation, rerun, filtering, results, and JSON export.
- [x] Cover validation, permissions, persistence, and failure evidence with tests.
- [x] Add an AgentOS cookbook and document the HTTP contract.

Scope: saved suite runs reuse evaluation rename/delete endpoints. Executable Python
callbacks and scorers are configured through the Python runner, not HTTP payloads.

- [x] Provide and live-verify six intentional failure cases with three passing controls, including numeric judging and combined failures.
