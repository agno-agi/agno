# GeoBuddy 🌍

An AI-powered geography detective that analyzes images to predict locations based on visual cues. This example demonstrates how to build sophisticated computer vision applications that combine geographical knowledge with advanced image analysis.

## Features

- **Location Identification**: Predicts location details from uploaded images.
- **Detailed Reasoning**: Explains predictions based on visual cues.
- **User-Friendly UI**: Built with Streamlit for an intuitive experience.

## 🚀 Quick Start

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/geobuddy/requirements.txt
```

### 3. Export API Keys

Set up your Google API key for Gemini models:

```shell
# Required for Gemini models (image analysis)
export GOOGLE_API_KEY=***
```

### 4. Run GeoBuddy

```shell
streamlit run cookbook/examples/streamlit_apps/geobuddy/app.py
```

Open [localhost:8501](http://localhost:8501) to start analyzing images.

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)
