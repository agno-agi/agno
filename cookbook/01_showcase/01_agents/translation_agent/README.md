# Translation Agent

An emotion-aware translation agent that translates text, analyzes the emotional tone, selects an appropriate voice, and generates localized audio output using Cartesia TTS.

## Quick Start

### 1. Prerequisites

```bash
# Set API keys
export OPENAI_API_KEY=your-openai-api-key
export CARTESIA_API_KEY=your-cartesia-api-key
```

### 2. Run Examples

```bash
# Basic translation
.venvs/demo/bin/python cookbook/01_showcase/01_agents/translation_agent/examples/basic_translation.py

# Emotional content
.venvs/demo/bin/python cookbook/01_showcase/01_agents/translation_agent/examples/emotional_content.py

# Batch translation
.venvs/demo/bin/python cookbook/01_showcase/01_agents/translation_agent/examples/batch_translate.py
```

## Key Concepts

### Multi-Step Workflow

The agent follows a sequential workflow:

1. **Identify** - Parse text and target language
2. **Translate** - Convert text preserving meaning
3. **Analyze Emotion** - Detect emotional tone
4. **Get Language Code** - Map to 2-letter code
5. **List Voices** - Get available Cartesia voices
6. **Select Voice** - Choose voice matching language + emotion
7. **Localize Voice** - Create language-specific clone
8. **Generate Audio** - Create TTS output

### Emotion-Voice Mapping

| Emotion | Voice Characteristics |
|---------|----------------------|
| Neutral | Clear, professional, moderate pace |
| Happy | Upbeat, energetic, slightly faster |
| Sad | Slower, softer, lower energy |
| Angry | Stronger, more intense |
| Excited | High energy, dynamic |
| Calm | Soothing, steady |

### Supported Languages

| Language | Code |
|----------|------|
| French | fr |
| Spanish | es |
| German | de |
| Italian | it |
| Portuguese | pt |
| Japanese | ja |
| Chinese | zh |
| Korean | ko |
| Russian | ru |
| Arabic | ar |

## Usage

### Basic Translation

```python
from agent import translation_agent

response = translation_agent.run(
    "Translate 'Hello, how are you?' to French and create a voice note"
)

# Access audio
if response.audio:
    audio_bytes = response.audio[0].content
    # Save or play the audio
```

### Helper Function

```python
from agent import translate_and_speak

result = translate_and_speak(
    text="Hello!",
    target_language="Spanish",
    output_path="greeting_spanish.mp3"
)

print(result["audio_path"])  # Path to saved audio
```

## Architecture

```
User Request (Text + Language)
    |
    v
[Translation Agent (GPT-5.2)]
    |
    +---> Translate text
    |
    +---> Analyze emotion
    |
    +---> CartesiaTools
    |         |
    |         +---> list_voices
    |         +---> localize_voice
    |         +---> text_to_speech
    |
    v
Audio Output (MP3)
```

## Dependencies

- `agno` - Core framework
- `openai` - GPT-5.2 model
- `cartesia` - TTS API

## API Credentials

To use this agent, you need a Cartesia API key:

1. Go to [cartesia.ai](https://cartesia.ai)
2. Create an account
3. Get your API key
4. Set `CARTESIA_API_KEY` environment variable
