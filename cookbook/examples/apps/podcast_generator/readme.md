# Podify AI 🎙

Podify AI is an AI-powered podcast agent that generates high-quality podcasts on any topic.
It uses real-time search using DuckDuckGo and AI-generated narration to create professional podcast scripts with realistic voices.

🎧 Enter a topic → model writes a script → narrates it → you listen & download!

## Features

- **AI-Generated Podcasts**: Automatically researches & generates podcast scripts.
- **Realistic AI Voices**: Choose from multiple AI voices for narration.
- **Download & Share**: Save and share your generated podcasts.
- **Real-Time Research**: Uses DuckDuckGo for up-to-date insights.
---

## Setup Instructions

### 1. Create a virtual environment

```shell
python3 -m venv ~/.venvs/podifyenv
source ~/.venvs/podifyenv/bin/activate
```

### 2. Install requirements

```shell
pip install -r cookbook/examples/apps/podcast_generator/requirements.txt
```

### 3. Export `OPENAI_API_KEY`

```shell
export OPENAI_API_KEY=***
```

### 4. Run Streamlit App

```shell
streamlit run cookbook/examples/apps/podcast_generator/app.py
```
