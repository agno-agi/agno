FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY agno /opt/agno/agno
COPY pyproject.toml LICENSE README.md /opt/agno/
RUN pip install --no-cache-dir "/opt/agno[claude,codex]" \
    sqlalchemy==2.0.52 claude-agent-sdk==0.2.165 openai-codex==0.162.1 \
    && python -c "import agno.sandbox.agentcore.server, agno.sandbox.runtime, claude_agent_sdk, openai_codex"
ENV HOME=/runtime
WORKDIR /workspace
# A passwd entry for the runtime user, for tools that look up the current user.
RUN groupadd --gid 1000 sandbox && useradd --uid 1000 --gid 1000 --home-dir /runtime --no-create-home sandbox
# One image serves both providers. DockerSandbox sets the user to 1000:1000, the
# entrypoint and the working directory when it creates a container. AgentCore
# cannot override them, so the image's own entrypoint is the AgentCore server: it
# runs as root to keep its claim out of the agent's reach, and starts the runtime
# server and every command as UID 1000. AgentCore requires port 8080 and ARM64.
EXPOSE 8080
ENTRYPOINT ["python", "-I", "-m", "agno.sandbox.agentcore.server", "serve"]
