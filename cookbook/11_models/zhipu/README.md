# Zhipu AI

[Zhipu AI Models Overview](https://open.bigmodel.cn/)

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your Zhipu API Key

```shell
export ZHIPU_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U agno ddgs
```

### 4. Run basic agent

- Streaming on

```shell
python cookbook/11_models/zhipu/basic_stream.py
```

- Streaming off

```shell
python cookbook/11_models/zhipu/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/11_models/zhipu/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/11_models/zhipu/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/11_models/zhipu/db.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/11_models/zhipu/knowledge.py
```

### 9. Run Agent with thinking mode

```shell
python cookbook/11_models/zhipu/thinking_agent.py
```

### 10. Run Agent with image input

```shell
python cookbook/11_models/zhipu/image_agent.py
```

