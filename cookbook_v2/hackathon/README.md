# Hackathon Resources

Thank you for using Agno to build your hackathon project! Here you'll find setup guides, examples, and resources to bring your multimodal agents to life.

> Read this documentation on [Agno Docs](https://docs.agno.com)

## Environment Setup

Let's get your environment setup for the hackathon. Here are the steps:

1. Create a virtual environment
2. Install libraries
3. Export your API keys

### Create a virtual environment

You can use `python3 -m venv` or `uv` to create a virtual environment.

- Standard python

```shell
python3 -m venv .venv
source .venv/bin/activate
```

- Using uv

```shell
uv venv --python 3.12
source .venv/bin/activate
```

- for Windows

```shell
python -m venv venv
venv\scripts\activate
```

### Install libraries

Install the `agno` python package along with the models and tools you want to use.

- Standard python

```shell
pip install -U agno openai
```

- Using uv

```shell
uv pip install -U agno openai
```

### Export your API keys

Export the API keys for the models and tools you want to use.

```shell
export OPENAI_API_KEY=***
export GOOGLE_API_KEY=***
export ELEVEN_LABS_API_KEY=***
```

for Windows

```shell
$env:OPENAI_API_KEY="your-api-key"
```

## Text Agents

Here are some examples of Text Agents built with Agno:

- [Simple Text Agent](cookbook/hackathon/examples/simple_text_agent.py)
- [Agent with Tools](cookbook/hackathon/examples/agent_with_tools.py)
- [Agent with Knowledge](cookbook/hackathon/examples/agent_with_knowledge.py)
- [Agent with Structured Outputs](cookbook/hackathon/examples/structured_output.py)
- [Research Agent](cookbook/hackathon/examples/research_agent.py)
- [Youtube Agent](cookbook/hackathon/examples/youtube_agent.py)

## Image Agents

- [Image Input + Tools](cookbook/hackathon/multimodal_examples/image_input_with_tools.py)
- [Image Generation](cookbook/hackathon/multimodal_examples/image_generate.py)
- [Image to Structured Output](cookbook/hackathon/multimodal_examples/image_to_structured_output.py)
- [Image to Audio](cookbook/hackathon/multimodal_examples/image_to_audio.py)
- [Image to Image](cookbook/hackathon/multimodal_examples/image_to_image.py)
- [Image Transcription](cookbook/hackathon/multimodal_examples/image_transcription.py)
- [Image Generation with Steps](cookbook/hackathon/multimodal_examples/image_generate_with_intermediate_steps.py)
- [Image Search with Giphy](cookbook/hackathon/multimodal_examples/image_gif_search.py)

## Audio Agents

- [Audio Input](cookbook/hackathon/multimodal_examples/audio_input.py)
- [Audio Input Output](cookbook/hackathon/multimodal_examples/audio_input_output.py)
- [Audio Multiturn](cookbook/hackathon/multimodal_examples/audio_multi_turn.py)
- [Audio Sentiment Analysis](cookbook/hackathon/multimodal_examples/audio_sentiment_analysis.py)
- [Audio Transcription](cookbook/hackathon/multimodal_examples/audio_transcription.py)
- [Audio Podcast](cookbook/hackathon/multimodal_examples/audio_podcast_generator.py)

## Video Agents

- [Video Input](cookbook/hackathon/multimodal_examples/video_input.py)
- [Video to Shorts](cookbook/hackathon/multimodal_examples/video_to_shorts.py)
- [Video Caption](cookbook/hackathon/multimodal_examples/video_caption.py)
- [Video Generation using Replicate](cookbook/hackathon/multimodal_examples/video_generate_using_replicate.py)
- [Video Generation using Models Lab](cookbook/hackathon/multimodal_examples/video_generate_using_models_lab.py)
