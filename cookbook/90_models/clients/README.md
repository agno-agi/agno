# Clients

Cookbook examples for `cookbook/90_models/clients`.

Run examples with:

```bash
.venvs/demo/bin/python cookbook/90_models/clients/<example>.py
```

## OpenAI-compatible User-Agent

`OpenAILike` sends `agno/<version> Python/<python-version>` by default. Set
`AGNO_USER_AGENT` before creating the client to change the default for your
process. To set it for one model, supply a `User-Agent` in `default_headers`.

```python
from agno.models.openai.like import OpenAILike

model = OpenAILike(
    id="gpt-5.6-luna",
    base_url="https://gateway.example/v1",
    default_headers={"User-Agent": "my-app/1.0"},
)
```
