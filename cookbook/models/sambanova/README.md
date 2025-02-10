# Sambanova Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `SAMBANOVA_API_KEY`

```shell
export SAMBANOVA_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/sambanova/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/sambanova/basic.py
```
## Disclaimer:

Sambanova does not support all OpenAIChat features. The following features are not yet supported and will be ignored:

- logprobs
- top_logprobs
- n
- presence_penalty
- frequency_penalty
- logit_bias
- tools
- tool_choice
- parallel_tool_calls
- seed
- stream_options: include_usage
- response_format

Please refer to https://community.sambanova.ai/t/open-ai-compatibility/195 for more information.
