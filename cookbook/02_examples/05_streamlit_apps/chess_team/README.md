# Chess Team Battle

An interactive game where different language models compete against each other in strategic matches. This example demonstrates advanced multi-agent coordination, real-time game state management, and sophisticated turn-based gameplay.

## ✨ Features

- **Multi-Agent Chess Gameplay**: Watch AI models compete with specialized roles
- **Real-time Chess Visualization**: Interactive board with piece movement tracking
- **Multiple AI Model Support**: Choose from GPT-4, Claude, Gemini, and more
- **Move Validation**: Powered by python-chess for accurate game rules
- **Game Analysis**: Get strategic insights and position evaluation
- **Session Management**: Save and resume chess games
- **Move History**: Detailed tracking of all moves and game progression

## 🚀 Quick Start

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/chess_team/requirements.txt
```

### 3. Export API Keys

Set up API keys for the AI models you want to use:

```shell
# Required for OpenAI models
export OPENAI_API_KEY=***

# Optional - for additional models
export ANTHROPIC_API_KEY=***  # For Claude models
export GOOGLE_API_KEY=***     # For Gemini models
```

### 4. Run the Chess Game

```shell
streamlit run cookbook/examples/streamlit_apps/chess_team/app.py
```

Open [localhost:8501](http://localhost:8501) to view the chess interface.

## 🎮 How It Works

The chess game consists of three specialized AI agents:

### 🤖 Agent Roles

1. **White Player Agent**
   - Strategizes and makes moves for white pieces
   - Analyzes positions using chess principles
   - Considers tactical and strategic elements

2. **Black Player Agent**  
   - Strategizes and makes moves for black pieces
   - Responds to white's strategy appropriately
   - Applies opening and endgame knowledge

3. **Game Master Agent**
   - Coordinates gameplay between players
   - Routes move requests to appropriate agents
   - Provides position analysis and commentary
   - Manages game state and flow

## 📊 Available Models

Choose from various AI models for different playing styles:

- **GPT-4o** (OpenAI) - Balanced strategic play
- **o3-mini** (OpenAI) - Quick tactical decisions  
- **Claude-4-Sonnet** (Anthropic) - Deep positional understanding
- **Gemini-2.5-Pro** (Google) - Creative and dynamic play

## 💡 Usage Examples

### Basic Game
```python
# Start a quick game with default models
team = get_chess_team()
```

### Custom Match
```python
# Set up a specific model matchup
team = get_chess_team(
    white_model="gpt-4o",
    black_model="claude-4-sonnet", 
    master_model="gpt-4o"
)
```

### Game Analysis
Ask the Game Master for insights:
- "Analyze the current position"
- "What are the key strategic themes?"
- "Evaluate material balance and piece activity"
- "Suggest candidate moves for the current player"

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)
