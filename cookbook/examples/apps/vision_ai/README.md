# VisionAI 🖼️
VisionAI is a **smart image analysis agent** that extracts structured insights from images using AI-powered **object detection, OCR, and scene recognition**.

The system is designed with two separate agents:
- **Image Processing Agent**: Extracts structured insights based on the uploaded image and user instructions.
- **Chat Agent**: Answers follow-up questions using the last extracted insights from image and (optionally) web search via DuckDuckGo.

---

## 🚀 **Setup Instructions**

> Note: Fork and clone the repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install libraries

```shell
pip install -r cookbook/examples/apps/vision_ai/requirements.txt
```

### 3. Export API Keys

We recommend using gpt-4o for this task, but you can use any Model you like.

```shell
export OPENAI_API_KEY=***
```

Other API keys are optional, but if you'd like to test:

```shell
export GOOGLE_API_KEY=***
export MISTRAL_API_KEY=***
```

### 4. Run VisionAI Agent

```shell
streamlit run cookbook/examples/apps/vision_ai/app.py
```

- Open [localhost:8501](http://localhost:8501) to view the VisionAI Agent.

### 5. Features

### Image Processing Modes
- **Auto**: Extracts the image automatically without any extra information from users
- **Manual**: User provide specific instructions for image extraction
- **Hybrid**: Combined auto-processing mode with user-defined instructions

### Smart Chat Agent for Follow-up Queries
- Interactive follow-up questions on extracted image data
- Optional web search integration via **DuckDuckGo**
- Seamless switching between different AI models

### Enable/Disable Web Search
- Users can easily toggle web search capability (DuckDuckGo) on/off using a convenient radio button in the sidebar
- When enabled, the chat agent leverages web search results to enhance responses specifically when users request the agent to search online

---

### 6. How to Use 🛠

- **Upload Image**: Support for PNG, JPG, and JPEG (up to 20MB)
- **Select Model**: Choose between OpenAI, Gemini, or Mistral
- **Configure Mode**: Set processing approach (Auto/Manual/Hybrid)
- **Enter Instructions** *(if required for Manual/Hybrid Mode).
- **Toggle Search**: Enable/disable DuckDuckGo web search
- **Process Image**: Extract structured insights from your image
- **Ask Follow-Up Questions**: Chat with VisionAI about the extracted image data

### 7. Message us on [discord](https://agno.link/discord) if you have any questions


