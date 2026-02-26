# Gemini 3 -- Progressive Guide to Agno Agents

Build agents with Google Gemini, progressively adding capabilities at each step. From a basic chat to a multi-agent team deployed on Agent OS.

| # | File | Agent | What It Adds |
|:--|:-----|:------|:-------------|
| 1 | `1_basic.py` | Chat Assistant | Agent + Gemini, sync/async/streaming |
| 2 | `2_tools.py` | Finance Agent | WebSearchTools, instructions |
| 3 | `3_structured_output.py` | Movie Critic | Pydantic output_schema |
| 4 | `4_search.py` | News Agent | Gemini native search |
| 5 | `5_grounding.py` | Fact Checker | Grounding with citations |
| 6 | `6_url_context.py` | URL Context Agent | Native URL fetching |
| 7 | `7_thinking.py` | Thinking Agent | Extended thinking with budget control |
| 8 | `8_image_input.py` | Image Analyst | Image understanding |
| 9 | `9_image_generation.py` | Image Generator | Image generation + editing |
| 10 | `10_audio_input.py` | Audio Analyst | Audio transcription |
| 11 | `11_text_to_speech.py` | TTS Agent | Text-to-speech audio output |
| 12 | `12_video_input.py` | Video Analyst | Video understanding + YouTube |
| 13 | `13_pdf_input.py` | Document Reader | PDF understanding |
| 14 | `14_csv_input.py` | Data Analyst | CSV analysis |
| 15 | `15_file_search.py` | File Search Agent | Server-side RAG with citations |
| 16 | `16_prompt_caching.py` | Transcript Analyst | Prompt caching for token savings |
| 17 | `17_knowledge.py` | Recipe Assistant | ChromaDb knowledge + SqliteDb storage |
| 18 | `18_memory.py` | Personal Tutor | LearningMachine + agentic memory |
| 19 | `19_team.py` | Content Team | Multi-agent team (Writer/Editor/Fact-Checker) |
| 20 | `20_agent_os.py` | Agent OS | All agents + team on Agent OS |

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create and activate a virtual environment

```bash
uv venv .venvs/gemini --python 3.12
source .venvs/gemini/bin/activate
```

### 3. Install dependencies

```bash
uv pip install -r cookbook/gemini_3/requirements.txt
```

### 4. Set your API key

```bash
export GOOGLE_API_KEY=your-google-api-key
```

### 5. Run any step

```bash
python cookbook/gemini_3/1_basic.py
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
|------|------|
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
