# Vision AI

**Vision AI** is a smart image analysis agent that extracts structured insights from images using AI-powered object detection, OCR, and scene recognition.

> Note: Fork and clone this repository if needed

The system is designed with two separate agents:
- **Image Processing Agent**: Extracts structured insights based on the uploaded image and user instructions.
- **Chat Agent**: Answers follow-up questions using the last extracted insights from image and (optionally) web search via DuckDuckGo.

## Getting Started

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/vision_ai/requirements.txt
```

### 3. Configure API Keys

Required (choose at least one):

```bash
export OPENAI_API_KEY=your_openai_key_here
```

Optional (for additional models):

```bash
export ANTHROPIC_API_KEY=your_anthropic_key_here
export GOOGLE_API_KEY=your_google_key_here
```

### 4. Run the application

```shell
streamlit run cookbook/examples/streamlit_apps/vision_ai/app.py
```

## How to Use

1. **Select Model**: Choose your preferred AI model for image analysis
2. **Upload Image**: Select a PNG, JPG, or JPEG file (up to 200MB)
3. **Choose Analysis Mode**: 
   - **Auto**: Comprehensive automatic analysis
   - **Manual**: Provide specific analysis instructions
   - **Hybrid**: Automatic analysis + your custom instructions
4. **Analyze**: Click "Analyze Image" to process your image
5. **Ask Questions**: Chat about the analysis results and ask follow-up questions

## Analysis Modes

### Auto Mode
Performs comprehensive automatic analysis including:
- Object and element identification
- Text extraction (OCR)
- Scene description
- Context and purpose inference
- Technical details

### Manual Mode
Allows you to specify exactly what you want to analyze:
- Focus on specific elements
- Extract particular types of information
- Custom analysis requirements

### Hybrid Mode
Combines automatic comprehensive analysis with your custom instructions:
- Gets the full auto analysis
- Plus your specific requirements
- Best of both approaches

## Supported Image Formats

- **PNG**: Portable Network Graphics
- **JPG/JPEG**: Joint Photographic Experts Group
- **Maximum Size**: 200MB per image

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)