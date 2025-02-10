# Game Generator Workflow

This is a simple game generator workflow that generates a single-page HTML5 game based on a user's prompt.

### 1. Create a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Install requirements

```shell
pip install -r cookbook/examples/apps/game_generator/requirements.txt
```

### 3. Export `OPENAI_API_KEY`

```shell
export OPENAI_API_KEY=sk-***
```

### 4. Run Streamlit App

```shell
streamlit run cookbook/examples/apps/game_generator/app.py
```
