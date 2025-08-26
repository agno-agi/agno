# Getting Started with Agno Agents 🚀

This guide walks through the basics of building Agents with Agno.

Each example builds on the previous one, introducing new concepts and capabilities progressively. Examples contain detailed comments, example prompts, and required dependencies.

## Setup

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the required dependencies:

```bash
pip install openai ddgs yfinance lancedb tantivy pypdf requests exa-py newspaper4k lxml_html_clean sqlalchemy agno
```

Export your OpenAI API key:

```bash
export OPENAI_API_KEY=your_api_key
```

Export your EXA_API_KEY:

```bash
export EXA_API_KEY=your_api_key
```

Export your ModelsLab API key (for video generation):

```bash
export MODELS_LAB_API_KEY=your_api_key
```

## Learning Path - Logical Progression

### Foundation (Start Here)
Learn the core concepts of agent creation and basic functionality.

#### 1. Basic Agent (`01_basic_agent.py`)
- Creates a simple news reporter with a vibrant personality
- Demonstrates basic agent configuration and responses
- Shows how to customize agent instructions and style

Run this recipe using:
```bash
python cookbook/getting_started/01_basic_agent.py
```

#### 2. Agent with Tools (`02_agent_with_tools.py`)
- Enhances the news reporter with web search capabilities
- Shows how to integrate DuckDuckGo search tool
- Demonstrates real-time information gathering

Run this recipe using:
```bash
python cookbook/getting_started/02_agent_with_tools.py
```

#### 3. Agent with Knowledge (`03_agent_with_knowledge.py`)
- Creates a Thai cooking expert with a recipe knowledge base
- Combines local knowledge with web searches
- Shows vector database integration for information retrieval

Run this recipe using:
```bash
python cookbook/getting_started/03_agent_with_knowledge.py
```

### Tools & Data Handling
Learn to create custom tools and handle structured data.

#### 4. Custom Tools (`04_write_your_own_tool.py`)
- Shows how to create custom tools
- Gives the agent an example tool that queries the Hacker News API

Run this recipe using:
```bash
python cookbook/getting_started/04_write_your_own_tool.py
```

#### 5. Structured Output (`05_structured_output.py`)
- Creates a movie script generator with structured outputs
- Shows how to use Pydantic models for response validation
- Demonstrates both JSON mode and structured output formats

Run this recipe using:
```bash
python cookbook/getting_started/05_structured_output.py
```

### Memory & State Management
Build agents that remember and maintain context.

#### 6. Agent with Storage (`06_agent_with_storage.py`)
- Updates the Thai cooking expert with persistent storage
- Shows how to save and retrieve agent state
- Demonstrates session management and history
- Runs a CLI application for an interactive chat experience

Run this recipe using:
```bash
python cookbook/getting_started/06_agent_with_storage.py
```

#### 7. Agent with State (`07_agent_state.py`)
- Shows how to use session state
- Demonstrates agent state management

Run this recipe using:
```bash
python cookbook/getting_started/07_agent_state.py
```

#### 8. Agent with Context (`08_agent_context.py`)
- Shows how to evaluate dependencies at agent.run and inject them into the instructions
- Demonstrates how to use context variable

Run this recipe using:
```bash
python cookbook/getting_started/08_agent_context.py
```

#### 9. Agent Session (`09_agent_session.py`)
- Shows how to create an agent with session memory
- Demonstrates how to resume a conversation from a previous session

Run this recipe using:
```bash
python cookbook/getting_started/09_agent_session.py
```

#### 10. User Memories and Summaries (`10_user_memories_and_summaries.py`)
- Shows how to create an agent which stores user memories and summaries
- Demonstrates how to access the chat history and session summary

Run this recipe using:
```bash
python cookbook/getting_started/10_user_memories_and_summaries.py
```

### Advanced Features
Master error handling, safety, and advanced capabilities.

#### 11. Retry function call (`11_retry_function_call.py`)
- Shows how to retry a function call if it fails or you do not like the output

Run this recipe using:
```bash
python cookbook/getting_started/11_retry_function_call.py
```

#### 12. Human-in-the-Loop (`12_human_in_the_loop.py`)
- Adds user confirmation to tool execution
- Shows how to implement safety checks
- Demonstrates interactive agent control

Run this recipe using:
```bash
python cookbook/getting_started/12_human_in_the_loop.py
```

### Multimedia & Creative
Work with images, audio, and video generation.

#### 13. Image Agent (`13_image_agent.py`)
- Creates an image agent for image analysis
- Combines image understanding with web searches
- Shows how to process and analyze images

Run this recipe using:
```bash
python cookbook/getting_started/13_image_agent.py
```

#### 14. Image Generation (`14_generate_image.py`)
- Implements an image agent using DALL-E
- Shows prompt engineering for image generation
- Demonstrates handling generated image outputs

Run this recipe using:
```bash
python cookbook/getting_started/14_generate_image.py
```

#### 15. Video Generation (`15_generate_video.py`)
- Creates a video agent using ModelsLabs
- Shows video prompt engineering techniques
- Demonstrates video generation and handling
- **Requires MODELS_LAB_API_KEY**

Run this recipe using:
```bash
python cookbook/getting_started/15_generate_video.py
```

#### 16. Audio Input/Output (`16_audio_input_output.py`)
- Creates an audio agent for voice interaction
- Shows how to process audio input and generate responses
- Demonstrates audio file handling capabilities

Run this recipe using:
```bash
python cookbook/getting_started/16_audio_input_output.py
```

### Multi-Agent Systems
Scale up to team-based agent architectures.

#### 17. Agent Team (`17_agent_team.py`)
- Implements an agent team with web and finance agents
- Shows agent collaboration and role specialization
- Combines market research with financial data analysis

Run this recipe using:
```bash
python cookbook/getting_started/17_agent_team.py
```

### Research & Information
Build powerful research and information gathering agents.

#### 18. Research Agent (`18_research_agent_exa.py`)
- Creates an AI research agent using Exa
- Shows how to steer the expected output of the agent
- **Requires EXA_API_KEY**

Run this recipe using:
```bash
python cookbook/getting_started/18_research_agent_exa.py
```

#### 19. Research Workflow (`19_research_workflow.py`)
- Creates an AI research workflow
- Searches using DuckDuckGo and Scrapes web pages using Newspaper4k
- Shows how to steer the expected output of the agent

Run this recipe using:
```bash
python cookbook/getting_started/19_research_workflow.py
```
