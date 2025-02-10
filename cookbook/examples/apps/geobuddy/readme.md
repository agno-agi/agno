# GeoBuddy 🌍

GeoBuddy is an AI-powered geography agent that analyzes images to predict locations based on visible cues like landmarks, architecture, and cultural symbols.

## Features

- **Location Identification**: Predicts location details from uploaded images.
- **Detailed Reasoning**: Explains predictions based on visual cues.
- **User-Friendly UI**: Built with Streamlit for an intuitive experience.

---

## Setup Instructions

### 1. Create a virtual environment

```shell
python3 -m venv ~/.venvs/geobuddyenv
source ~/.venvs/geobuddyenv/bin/activate
```

### 2. Install requirements

```shell
pip install -r cookbook/examples/apps/geobuddy/requirements.txt
```

### 3. Export `GOOGLE_API_KEY`

```shell
export GOOGLE_API_KEY=***
```

### 4. Run Streamlit App

```shell
streamlit run cookbook/examples/apps/geobuddy/app.py
```
