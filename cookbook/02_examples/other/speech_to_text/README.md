# Speech to Text Examples

Speech to text examples using OpenAI and Gemini. These examples demonstrate how to transcribe audio files using Agno. Based on the use case, either of the cookbooks can be used as a starting point for your own implementation.

## Authentication

Set the `OPENAI_API_KEY` and `GEMINI_API_KEY` environment variables with your OpenAI and Gemini API keys.

**Quick start:**
Go to https://platform.openai.com/ and https://console.cloud.google.com/ to get your API keys.

## Features

- **Structured Transcription** - Get structured output from the audio file
- **Simple Transcription** - Get simple transcription from the audio file
- **Workflow** - Use an Agno Workflow to transcribe the audio file

The Agents and the Workflow can be used with AgentOS to create a full-fledged speech to text application.

## Getting Started

### 1. Clone the repository

```shell
git clone https://github.com/agno-ai/agno.git
cd agno/cookbook/02_examples/other/speech_to_text
```

### 2. Create and activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Set environment variables

Follow the instructions to get your OpenAI and Gemini API keys. Make sure to copy the API keys and set them in the `OPENAI_API_KEY` and `GEMINI_API_KEY` environment variables.

```shell
export OPENAI_API_KEY=xxx
export GEMINI_API_KEY=xxx
```

### 4. Run Postgres with PgVector

Postgres stores agent sessions, memory, knowledge, and state. Install [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) and run:

```bash
./cookbook/scripts/run_pgvector.sh
```

Or run directly:

```bash
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pgvolume:/var/lib/postgresql/data \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:16
```

### 5. Run the examples

```shell
python stt_openai_agent_simple.py
```

```shell
python stt_openai_agent.py
```

```shell
python stt_gemini_agent.py
```
