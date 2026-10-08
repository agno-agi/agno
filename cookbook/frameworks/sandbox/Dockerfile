FROM python:3.12-slim AS runtime
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources && apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY libs/agno /app/libs/agno
COPY libs/agnoctl /app/libs/agnoctl
RUN pip install --no-cache-dir /app/libs/agnoctl '/app/libs/agno[os,postgres]' redis 'sqlalchemy==2.0.52' 'claude-agent-sdk==0.2.148' 'openai-codex==0.162.0'
COPY cookbook/frameworks/sandbox /example
ENV PYTHONPATH=/example AGNO_TELEMETRY=false
RUN useradd --create-home --uid 1000 sandbox && mkdir /workspace && chown sandbox:sandbox /workspace
USER sandbox
WORKDIR /workspace
EXPOSE 7777
CMD ["python", "-m", "agno.sandbox.runtime"]

FROM docker:29-cli AS docker-cli
FROM runtime AS control-plane
USER root
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
CMD ["python", "/example/control_plane.py"]
