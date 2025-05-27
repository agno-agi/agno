# Vercel Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `V0_API_KEY`

```shell
export V0_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/vercel/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/vercel/basic.py
```
