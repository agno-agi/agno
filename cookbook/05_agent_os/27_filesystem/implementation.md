# Agent files and Knowledge pages cookbook

- [x] Accept `PageFileSystem(db=db, namespace=...)` directly in `Agent(filesystem=...)`.
- [x] Default Knowledge, page storage, PgVector, and bounded OpenAI embedding configuration.
- [x] Automatically attach read-only tools and guidance without writable file tools.
- [x] Preserve explicit `PageFileSystem(knowledge=...)` construction.
- [x] Preserve agent-copy tool ownership and registry-based page filesystem persistence.
- [x] Provide explicit sync, chat, and local AgentOS serve commands.
- [x] Use built-in AgentOS routes without custom endpoints.
- [x] Document toolkit responsibilities, setup, and local access policy.
- [ ] Run the cookbook and verify read-only tool calls after user approval.

- [x] Automatically discover attached page filesystems and prepare storage at AgentOS startup.
- [x] Keep syncing explicit and preserve the cookbook's existing storage namespace and vector table.
- [x] Add source-aware backend routes with per-source authorization and publication-aware reads.
- [x] Replace the agent selector with a file-source selector in the control plane.
- [ ] Verify source switching, authorization, revision changes, and incomplete-search UI after user approval.

## Runnable AgentOS cookbooks

- [x] Replace the debugging/assertion scripts with seven focused AgentOS applications.
- [x] Cover Postgres, local disk, custom namespaces, shared files, and JWT user isolation.
- [x] Cover existing Knowledge and Knowledge with writable notes alongside the shorthand example.
- [x] Document server startup, required environment variables, and prompts to try in Chat.
- [x] Record all new examples as NOT RUN; no test harnesses or automatic cleanup on exit.
- [ ] Run the servers and verify chat/filesystem UI behavior after user approval.
