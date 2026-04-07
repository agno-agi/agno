# Kelly Intelligence

Cookbook examples for `cookbook/90_models/kelly_intelligence`.

[Kelly Intelligence](https://api.thedailylesson.com) is an OpenAI-compatible API
with a built-in 162,000-word vocabulary RAG layer, operated by
[Lesson of the Day, PBC](https://lotdpbc.com). Because it speaks the OpenAI
Chat Completions schema, the `KellyIntelligence` model class inherits from
`OpenAILike`.

## Setup

Set your Kelly Intelligence API key:

```bash
export KELLY_API_KEY="your-key-from-api.thedailylesson.com"
```

Run examples with:

```bash
.venvs/demo/bin/python cookbook/90_models/kelly_intelligence/<example>.py
```
