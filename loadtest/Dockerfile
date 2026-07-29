# Load-test AgentOS replica. Builds against the local agno source (editable).
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install the local agno lib (editable) with the OS server + OpenAI extras,
# plus the Postgres/Redis drivers the queue store needs.
COPY libs/agno /agno_src/libs/agno
RUN pip install --no-cache-dir -e "/agno_src/libs/agno[os,openai]" \
    && pip install --no-cache-dir "psycopg[binary]" redis "uvicorn[standard]"

# App + stub model
COPY loadtest/app.py loadtest/stub_model.py /app/

EXPOSE 7777
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7777"]
