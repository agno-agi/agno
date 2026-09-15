# Test Log

Not run yet. Repository instructions require waiting for explicit user approval
before running the cookbook or automated tests.

### docker_filesystem.py

**Status:** NOT RUN

**Description:** Containerized AgentOS with a LocalFileSystem stored in a Docker
named volume. Includes an image built from the current checkout and Compose setup.

**Result:** Image build, startup, file operations, and persistence after container
replacement have not been executed. Waiting for the user's instruction to test.

### e2b_filesystem.py

**Status:** NOT RUN

**Description:** Local AgentOS connected to a temporary E2B sandbox through the
cookbook-only E2BFileSystem adapter, with read/write/list/delete and inherited
async/search support.

**Result:** No sandbox created and no agent or API calls executed. SDK behavior,
browser integration, and shutdown cleanup remain unverified.

### workspace_quickstart.py

**Status:** NOT RUN

**Description:** AgentOS with a Notes Agent and Report Agent sharing one durable
filesystem for project configuration, notes, and reports.

**Result:** Not executed; waiting for the user's instruction to test.
