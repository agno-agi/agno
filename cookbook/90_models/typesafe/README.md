# TypeSafe Cookbook

Decision models answer typed questions with probabilities instead of generating text.
Jev is TypeSafe's decision model.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `TYPESAFE_API_KEY`

```shell
export TYPESAFE_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U agno
```

### 4. Ask typed questions

```shell
python cookbook/90_models/typesafe/basic.py
```

### 5. Decide asynchronously

```shell
python cookbook/90_models/typesafe/async_basic.py
```

### 6. Use a self-hosted decision model

Start an SGLang server with an open-weight checkpoint (see the script docstring), then:

```shell
python cookbook/90_models/typesafe/self_hosted.py
```

### 7. Run an Agent on a decision model

Each field of `output_schema` becomes one typed question; `run.decisions` holds the probabilities.

```shell
python cookbook/90_models/typesafe/agent_triage.py
```

### 8. Decision Agent with a guardrail and storage

```shell
python cookbook/90_models/typesafe/agent_with_guardrail.py
```
