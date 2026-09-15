FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install this checkout so the image includes the filesystem feature under development.
COPY libs/agno /opt/agno
COPY README.md /opt/agno/README.md
RUN pip install --no-cache-dir "/opt/agno[os]" openai

RUN useradd --create-home --uid 10001 agno \
    && mkdir -p /data/files /app \
    && chown -R agno:agno /data /app

COPY cookbook/05_agent_os/27_filesystem/docker_filesystem.py /app/docker_filesystem.py
WORKDIR /app
USER agno

EXPOSE 7777
CMD ["python", "docker_filesystem.py"]
