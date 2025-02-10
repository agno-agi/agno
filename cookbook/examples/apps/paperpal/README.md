# Paperpal Workflow

Paperpal is a research and technical blog writer workflow that writes a detailed blog on research topics referencing research papers by utilizing models and external tools: Exa and ArXiv

### 1. Create a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Install requirements

```shell
pip install -r cookbook/use_cases/apps/paperpal/requirements.txt
```

### 3. Export `OPENAI_API_KEY` and `EXA_API_KEY`

```shell
export OPENAI_API_KEY=sk-***
export EXA_API_KEY=***
```

### 4. Run Streamlit App

```shell
streamlit run cookbook/use_cases/apps/paperpal/app.py
```
