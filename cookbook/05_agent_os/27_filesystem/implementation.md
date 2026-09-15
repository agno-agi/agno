# Docker and sandbox filesystem cookbooks

- [x] Add a Docker example using LocalFileSystem and a named volume.
- [x] Build its image from the local Agno package with a restricted build context.
- [x] Add an E2B example with a cookbook-only BaseFS adapter.
- [x] Provide sync storage methods and inherit BaseFS async wrappers.
- [x] Document setup, storage lifetimes, example prompts, and cleanup.
- [ ] Build or run the Docker example and verify persistence.
- [ ] Run the E2B example and verify file operations and sandbox cleanup.
- [ ] Run formatting, validation, or tests when requested by the user.

No framework code changes are required. Both examples use the existing
FileSystem attachment and AgentOS file routes. Runtime checks are pending the
user's instruction to test.
