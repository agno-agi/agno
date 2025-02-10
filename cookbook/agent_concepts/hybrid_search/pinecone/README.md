## Pinecone Hybrid Search Agent

### 1. Create a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Install libraries

```shell
pip install -U pinecone pinecone-text pypdf openai agno
```

### 3. Set Pinecone API Key

```shell
export PINECONE_API_KEY=***
```

### 4. Run Pinecone Hybrid Search Agent

```shell
python cookbook/agent_concepts/hybrid_search/pinecone/agent.py
```
