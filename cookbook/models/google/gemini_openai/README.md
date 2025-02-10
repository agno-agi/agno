# Google Gemini OpenAI Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export `GOOGLE_API_KEY`

```shell
export GOOGLE_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/google/gemini_openai/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/google/gemini_openai/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Agent

```shell
python cookbook/models/google/tool_use.py
```


### 6. Run Agent that returns structured output

```shell
python cookbook/models/google/structured_output.py
```
