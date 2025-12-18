# Podcast Generator

**Podcast Generator** s an AI-powered podcast agent that generates high-quality podcasts on any topic. It uses real-time search using DuckDuckGo and AI-generated narration to create professional podcast scripts with realistic voices.

> Note: Fork and clone this repository if needed

## Features

- **AI-Generated Podcasts**: Automatically researches & generates podcast scripts.
- **Realistic AI Voices**: Choose from multiple AI voices for narration.
- **Download & Share**: Save and share your generated podcasts.
- **Real-Time Research**: Uses DuckDuckGo for up-to-date insights.

## Getting Started

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/podcast_generator/requirements.txt
```

### 3. Configure API Keys

Required:

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
streamlit run cookbook/examples/streamlit_apps/podcast_generator/app.py
```

## How to Use

1. **Select Model**: Choose your preferred AI model from the dropdown
2. **Choose Voice**: Pick from 6 realistic AI voices (alloy, echo, fable, onyx, nova, shimmer)
3. **Enter Topic**: Describe what you want your podcast to cover
4. **Generate**: Click "Create Podcast" and wait for the AI to work its magic!
5. **Listen & Download**: Play your podcast and download the audio file

## Sample Topics

Try these example topics to get started:

- "The Future of AI in Healthcare"
- "Climate Change Solutions in 2025" 
- "Space Exploration: Mars Missions"
- "The Rise of Electric Vehicles"
- "Blockchain Technology Explained"
- "Mental Health in the Digital Age"

## Voice Options

Choose from 6 distinct AI voices:

- **Alloy**: Balanced, professional tone
- **Echo**: Clear, articulate delivery
- **Fable**: Warm, engaging voice
- **Onyx**: Deep, authoritative tone
- **Nova**: Bright, energetic delivery
- **Shimmer**: Smooth, pleasant voice

## How It Works

1. **Research Phase**: The AI agent uses DuckDuckGo to gather current information about your topic
2. **Script Writing**: Creates a compelling 2-minute podcast script with proper structure
3. **Audio Generation**: Converts the script to high-quality audio using OpenAI's text-to-speech
4. **Delivery**: Provides you with a downloadable WAV file ready for sharing

## Technical Details

- **Backend**: Agno AI framework with OpenAI integration
- **Frontend**: Streamlit for intuitive web interface
- **Audio**: OpenAI TTS with multiple voice options
- **Research**: DuckDuckGo search for real-time information
- **Output**: High-quality WAV audio files

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)
