# iFLYTEK Spark

[iFLYTEK Spark](https://www.xfyun.cn/solutions/xinghuoAPI) (讯飞星火) exposes its
models through an
[OpenAI-compatible HTTP API](https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html),
so you can drive them through Agno the same way you'd drive any OpenAI-compatible
provider. The Agno `Spark` class defaults to `4.0Ultra` (Spark 4.0 Ultra) and points
at `https://spark-api-open.xf-yun.com/v1`.

## Models

| id | Model | Tool calling |
| --- | --- | --- |
| `4.0Ultra` | Spark 4.0 Ultra | ✅ |
| `generalv3.5` | Spark Max | ✅ |
| `max-32k` | Spark Max-32K | ✅ |
| `generalv3` | Spark Pro | — |
| `pro-128k` | Spark Pro-128K | — |
| `lite` | Spark Lite | — |

## Get an API Password

Sign in to the [iFLYTEK console](https://console.xfyun.cn), create a Spark
application, then copy the HTTP-service **API Password**
(`http服务接口认证信息` → `APIPassword`). This single Bearer credential is what the
`spark-api-open.xf-yun.com` OpenAI-compatible endpoint expects — it is different
from the APPID/APIKey/APISecret triple used by the legacy WebSocket API.

### 1. Create and activate a virtual environment

See the repository [Development setup](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md#development-setup).

### 2. Export your API Password

```shell
export SPARK_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

## Examples

```shell
# Basic agent (sync, async, streaming)
.venvs/demo/bin/python cookbook/90_models/spark/basic.py

# Create an agent from the "spark:<model-id>" string shorthand
.venvs/demo/bin/python cookbook/90_models/spark/string_model.py

# Structured output: return a typed Pydantic object via JSON mode
.venvs/demo/bin/python cookbook/90_models/spark/structured_output.py

# Tool use: web search with a function-calling model
.venvs/demo/bin/python cookbook/90_models/spark/tool_use.py
```
