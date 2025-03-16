# Sage: Advanced Answer Engine

Sage is a powerful answer engine that combines:
- Real-time web search capabilities (using DuckDuckGo)
- Deep contextual analysis (using ExaTools)
- Intelligent tool selection
- Multiple LLM support
- Session management (using Sqlite)
- Chat history export

## 🚀 Quick Start

### 1. Environment Setup

Create and activate a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r cookbook/examples/apps/answer_engine/requirements.txt
```

### 3. Configure API Keys

Required:
```bash
export GROQ_API_KEY=your_groq_key_here
export EXA_API_KEY=your_exa_key_here
```

Optional (for additional models):
```bash
export OPENAI_API_KEY=your_openai_key_here
export ANTHROPIC_API_KEY=your_anthropic_key_here
export GOOGLE_API_KEY=your_google_key_here
```

### 4. Launch the Application

```bash
streamlit run cookbook/examples/apps/answer_engine/app.py
```

Visit [localhost:8501](http://localhost:8501) to use the answer engine.

## 🔧 Customization

### Model Selection

The application supports multiple model providers:
- Groq (llama-3.3-70b-versatile)
- OpenAI (o3-mini, gpt-4o)
- Anthropic (claude-3-5-sonnet)
- Google (gemini-2.0-flash-exp)

### Agent Configuration

The agent configuration is in `agents.py` and the prompts are in `prompts.py`.
- If you just want to modify the prompts, update the `prompts.py` file.
- If you want to add new tools, models etc. update the `agents.py` file.

## 📚 Documentation

For more detailed information:
- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)
