# Gemini 3 -- Build Agents with Google Gemini

Build Agno agents with Google Gemini, progressively adding capabilities at each step. From a basic chat to workflows and multi-agent teams deployed on Agent OS.

This guide walks through the basics of building Agents, the easy way. Follow along to learn how to build agents with tools, storage, memory, knowledge, state, guardrails, and human in the loop. We'll also build multi-agent teams and step-based agentic workflows.

Each example can be run independently and contains detailed comments + example prompts to help you understand what's happening behind the scenes. We'll use **Gemini 3 Flash** — fast, affordable, and excellent at tool calling but you can swap in any model with a one line change. We use either **Gemini 3 Flash** or **Gemini 3.1 Pro** as the model, depending on the example.

## Fast Path

```bash
# 1. Clone
git clone https://github.com/agno-agi/agno.git && cd agno

# 2. Create virtual environment
uv venv .venvs/gemini --python 3.12 && source .venvs/gemini/bin/activate

# 3. Install
uv pip install -r cookbook/gemini_3/requirements.txt

# 4. Set your API key
export GOOGLE_API_KEY=your-google-api-key

# 5. Run your first agent
python cookbook/gemini_3/1_basic.py
```

## What You'll Build

### Part 1: Framework Basics

| # | File | Agent | What It Adds | Key Features |
|:--|:-----|:------|:-------------|:-------------|
| 1 | `1_basic.py` | Chat Assistant | Agent + Gemini, sync/async/streaming | Agent, print_response, streaming |
| 2 | `2_tools.py` | Finance Agent | WebSearchTools, instructions | Tool calling, system prompts |
| 3 | `3_structured_output.py` | Movie Critic | Pydantic output_schema | Structured output, type safety |

### Part 2: Gemini-Native Features

| # | File | Agent | What It Adds | Key Features |
|:--|:-----|:------|:-------------|:-------------|
| 4 | `4_search.py` | News Agent | Gemini native search | Real-time Google Search |
| 5 | `5_grounding.py` | Fact Checker | Grounding with citations | Verifiable, cited responses |
| 6 | `6_url_context.py` | URL Context Agent | Native URL fetching | Read and compare web pages |
| 7 | `7_thinking.py` | Thinking Agent | Extended thinking with budget | Complex reasoning, chain-of-thought |

### Part 3: Multimodal

| # | File | Agent | What It Adds | Key Features |
|:--|:-----|:------|:-------------|:-------------|
| 8 | `8_image_input.py` | Image Analyst | Image understanding | Describe, read text, answer questions |
| 9 | `9_image_generation.py` | Image Generator | Image generation + editing | Create and edit images from text |
| 10 | `10_audio_input.py` | Audio Analyst | Audio transcription | Transcribe, summarize, analyze |
| 11 | `11_text_to_speech.py` | TTS Agent | Text-to-speech audio output | Generate spoken audio |
| 12 | `12_video_input.py` | Video Analyst | Video understanding + YouTube | Scene description, content analysis |
| 13 | `13_pdf_input.py` | Document Reader | PDF understanding | Read documents natively |
| 14 | `14_csv_input.py` | Data Analyst | CSV analysis | Analyze datasets directly |

### Part 4: Advanced Features

| # | File | Agent | What It Adds | Key Features |
|:--|:-----|:------|:-------------|:-------------|
| 15 | `15_file_search.py` | File Search Agent | Server-side RAG with citations | Managed document search |
| 16 | `16_prompt_caching.py` | Transcript Analyst | Prompt caching for token savings | Cache large documents |

### Part 5: Knowledge, Memory, Team, and Workflow

| # | File | Agent | What It Adds | Key Features |
|:--|:-----|:------|:-------------|:-------------|
| 17 | `17_knowledge.py` | Recipe Assistant | ChromaDb knowledge + SqliteDb storage | Local RAG, hybrid search |
| 18 | `18_memory.py` | Personal Tutor | LearningMachine + agentic memory | Agent improves over time |
| 19 | `19_team.py` | Content Team | Multi-agent team (Writer/Editor/Fact-Checker) | Team coordination |
| 20 | `20_workflow.py` | Research Pipeline | Step-based workflow (Parallel, Condition) | Predictable multi-step pipelines |
| 21 | `21_agent_os.py` | Agent OS | All agents + team + workflow on Agent OS | Web UI, tracing, deployment |

## Run Each Step

```bash
# Part 1: Framework Basics
python cookbook/gemini_3/1_basic.py              # Basic chat
python cookbook/gemini_3/2_tools.py              # Agent + tools
python cookbook/gemini_3/3_structured_output.py  # Structured output

# Part 2: Gemini Features
python cookbook/gemini_3/4_search.py             # Native search
python cookbook/gemini_3/5_grounding.py          # Grounding
python cookbook/gemini_3/6_url_context.py        # URL context fetching
python cookbook/gemini_3/7_thinking.py           # Extended thinking

# Part 3: Multimodal
python cookbook/gemini_3/8_image_input.py        # Image understanding
python cookbook/gemini_3/9_image_generation.py   # Image generation + editing
python cookbook/gemini_3/10_audio_input.py       # Audio understanding
python cookbook/gemini_3/11_text_to_speech.py    # Text-to-speech
python cookbook/gemini_3/12_video_input.py       # Video + YouTube
python cookbook/gemini_3/13_pdf_input.py         # PDF understanding
python cookbook/gemini_3/14_csv_input.py         # CSV analysis

# Part 4: Advanced Features
python cookbook/gemini_3/15_file_search.py       # Server-side RAG
python cookbook/gemini_3/16_prompt_caching.py    # Prompt caching

# Part 5: Production
python cookbook/gemini_3/17_knowledge.py         # Knowledge + storage
python cookbook/gemini_3/18_memory.py            # Memory + learning
python cookbook/gemini_3/19_team.py              # Multi-agent team
python cookbook/gemini_3/20_workflow.py           # Step-based workflow
python cookbook/gemini_3/21_agent_os.py          # Agent OS (web UI)
```

## Run via Agent OS

Agent OS provides a web interface for interacting with all your agents. Step 21 registers every agent, team, and workflow from this guide.

```bash
python cookbook/gemini_3/21_agent_os.py
```

Then visit [os.agno.com](https://os.agno.com) and add `http://localhost:7777` as an endpoint.

## Troubleshooting

| Issue | Fix |
|:------|:----|
| `GOOGLE_API_KEY not set` | `export GOOGLE_API_KEY=your-key` |
| `ModuleNotFoundError` | `uv pip install -r cookbook/gemini_3/requirements.txt` |
| `429 Rate limit exceeded` | Wait a minute, or use a different model ID |
| `Model not found` | Check model ID spelling -- use `gemini-3-flash-preview` or `gemini-3.1-pro-preview` |

## Learn More

- [Agno Documentation](https://docs.agno.com)
- [Agent OS Overview](https://docs.agno.com/agent-os/introduction)
- [Gemini API Reference](https://ai.google.dev/docs)
