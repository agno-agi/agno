# The Grid

Cookbook examples for `cookbook/90_models/thegrid`.

[The Grid](https://thegrid.ai) is a spot market for inference. An id names a market
instrument -- a task type (`text`, `code`, `agent`) paired with a quality tier
(`standard`, `prime`, `max`) -- rather than a fixed model, so the model that serves
a request differs from the instrument requested. Set your API key first:

```bash
export THEGRID_API_KEY=***
```

Run examples with:

```bash
.venvs/demo/bin/python cookbook/90_models/thegrid/<example>.py
```
