# Gemini 3 -- Build Agents with Google Gemini

Build agents with Google Gemini, progressively adding capabilities at each step. From a basic chat to a multi-agent team deployed on Agent OS -- in 20 steps.

Each example can be run independently and contains detailed comments to help you understand what's happening behind the scenes. We use **Gemini 3 Flash** -- fast, affordable, and excellent at tool calling.

## Fast Path (2 minutes)

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

**That's it.** No Docker, no Postgres -- just Python and an API key.

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

### Part 5: Production

| # | File | Agent | What It Adds | Key Features |
|:--|:-----|:------|:-------------|:-------------|
| 17 | `17_knowledge.py` | Recipe Assistant | ChromaDb knowledge + SqliteDb storage | Local RAG, hybrid search |
| 18 | `18_memory.py` | Personal Tutor | LearningMachine + agentic memory | Agent improves over time |
| 19 | `19_team.py` | Content Team | Multi-agent team (Writer/Editor/Fact-Checker) | Team coordination |
| 20 | `20_agent_os.py` | Agent OS | All agents + team on Agent OS | Web UI, tracing, deployment |

## 15-Minute Tour

Short on time? Run these 5 steps for a quick tour of the highlights:

```bash
python cookbook/gemini_3/1_basic.py              # Your first agent
python cookbook/gemini_3/2_tools.py              # Agent with web search
python cookbook/gemini_3/8_image_input.py        # Image understanding
python cookbook/gemini_3/12_video_input.py       # Video analysis
python cookbook/gemini_3/19_team.py              # Multi-agent team
```

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
python cookbook/gemini_3/20_agent_os.py          # Agent OS (web UI)
```

## Domain-Specific Prompt Ideas

Each step works with domain-specific prompts. Here are ideas for music, film, and gaming:

| Step | Music | Film | Gaming |
|:-----|:------|:-----|:-------|
| 2 (Tools) | "Find the latest music industry revenue trends" | "What films are trending at the box office?" | "What are the top-selling games this month?" |
| 8 (Image) | "Analyze this album cover artwork" | "Describe the composition of this movie poster" | "What visual style does this game screenshot use?" |
| 10 (Audio) | "Transcribe and describe the mood of this track" | "Analyze the dialogue in this film clip" | "What sound effects are used in this game trailer?" |
| 12 (Video) | "Break down this music video scene by scene" | "Analyze the pacing of this film trailer" | "Review this game trailer for target audience" |
| 19 (Team) | "Create a press release for an album launch" | "Write a film review with fact-checking" | "Draft a game announcement with market analysis" |

See `use_cases/` for full working examples combining multiple steps.

## Run via Agent OS

Agent OS provides a web interface for interacting with all your agents. Step 20 registers every agent and team from this guide.

```bash
python cookbook/gemini_3/20_agent_os.py
```

Then visit [os.agno.com](https://os.agno.com) and add `http://localhost:7777` as an endpoint.

| Agent in UI | What You Get |
|:------------|:-------------|
| Chat Assistant | Basic Gemini chat |
| Finance Agent | Web search for financial research |
| Movie Critic | Structured movie reviews |
| News Agent | Real-time news via Gemini search |
| Fact Checker | Grounded, cited responses |
| URL Context Agent | Read and compare web pages |
| Image Analyst | Image understanding |
| Document Reader | PDF analysis |
| Recipe Assistant | Knowledge base + conversation history |
| Personal Tutor | Learns your preferences over time |
| Content Team | Writer + Editor + Fact-Checker team |

## When to Use Each Step

| Need | Step |
|:-----|:-----|
| Simple Q&A, no memory needed | **1 - Basic** |
| Agent needs to take actions (search, calculate) | **2 - Tools** |
| Need typed, structured responses | **3 - Structured Output** |
| Need current information from the web | **4 - Search** |
| Need verifiable, cited answers | **5 - Grounding** |
| Need to read and compare web pages | **6 - URL Context** |
| Need complex reasoning (math, logic) | **7 - Thinking** |
| Need to understand images | **8 - Image Input** |
| Need to generate or edit images | **9 - Image Generation** |
| Need to transcribe or analyze audio | **10 - Audio Input** |
| Need to generate spoken audio | **11 - Text-to-Speech** |
| Need to understand video or YouTube | **12 - Video Input** |
| Need to read PDFs or CSVs | **13-14 - Document Input** |
| Need managed RAG with citations | **15 - File Search** |
| Need token savings on repeated context | **16 - Prompt Caching** |
| Agent needs domain knowledge or conversation history | **17 - Knowledge** |
| Agent should improve over time | **18 - Memory** |
| Task needs multiple specialist perspectives | **19 - Team** |
| Need a production web service | **20 - Agent OS** |

**Start at step 1.** Add complexity only when simplicity fails.

## Swap Models Anytime

Agno is model-agnostic. Same code, different provider:

```python
# Gemini (default in these examples)
from agno.models.google import Gemini
model = Gemini(id="gemini-3-flash-preview")

# OpenAI
from agno.models.openai import OpenAIResponses
model = OpenAIResponses(id="gpt-5.2")

# Anthropic
from agno.models.anthropic import Claude
model = Claude(id="claude-sonnet-4-5")
```

## Related Cookbooks

- **[00_quickstart](../00_quickstart/)** -- Model-agnostic fundamentals: guardrails, HITL, state management, workflows, typed I/O
- **[90_models/google/gemini](../90_models/google/gemini/)** -- Raw Gemini API examples: Vertex AI, advanced file uploads, model variants
- **[02_agents](../02_agents/)** -- Deep dive into agent features with async variants

## Troubleshooting

| Issue | Fix |
|:------|:----|
| `GOOGLE_API_KEY not set` | `export GOOGLE_API_KEY=your-key` |
| `ModuleNotFoundError` | `uv pip install -r cookbook/gemini_3/requirements.txt` |
| `429 Rate limit exceeded` | Wait a minute, or use a different model ID |
| `Model not found` | Check model ID spelling -- use `gemini-3-flash-preview` or `gemini-3.1-pro-preview` |
| Image generation fails | Make sure you're NOT setting `instructions` on the agent (not supported for image gen) |

## Learn More

- [Agno Documentation](https://docs.agno.com)
- [Agent OS Overview](https://docs.agno.com/agent-os/introduction)
- [Gemini API Reference](https://ai.google.dev/docs)
