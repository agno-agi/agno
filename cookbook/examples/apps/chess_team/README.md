# Chess Team Battle

A Streamlit application that demonstrates the use of specialized AI agents working together to play chess. This application showcases how multiple agents with different roles can collaborate to play a game of chess, with move validation handled by the python-chess library.

## Features

- **Multiple Agent Roles**: 
  - White Piece Agent: Strategizes and selects moves for white pieces
  - Black Piece Agent: Strategizes and selects moves for black pieces
  - Master Agent: Analyzes the game state and provides commentary

- **Python-Chess Integration**:
  - Accurate move validation using the python-chess library
  - Detailed move descriptions with piece types and captures
  - Proper handling of special moves (castling, promotion, etc.)
  - Game state evaluation (checkmate, stalemate, draws)

- **Model Selection**: Choose different language models for each agent role
  - OpenAI models (GPT-4o, GPT-4.5, o3-mini)
  - Anthropic models (Claude 3.5, Claude 3.7)
  - Google models (Gemini Flash, Gemini Pro)
  - Groq models (Llama 3.3)

- **Interactive UI**:
  - Visual chess board representation
  - Move history tracking with detailed descriptions
  - Game state analysis
  - Pause/resume functionality

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/agno.git
cd agno/cookbook/examples/apps/chess_team
```

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your API keys as environment variables:
```bash
export OPENAI_API_KEY=your_openai_api_key
export ANTHROPIC_API_KEY=your_anthropic_api_key
export GOOGLE_API_KEY=your_google_api_key
export GROQ_API_KEY=your_groq_api_key
```

## Usage

1. Run the Streamlit application:
```bash
streamlit run app.py
```

2. Open your browser and navigate to the URL displayed in the terminal (usually http://localhost:8501)

3. Select the models for each agent role in the sidebar

4. Click "Start Game" to begin the chess match

5. Watch as the agents play against each other

## How It Works

1. **Game Initialization**:
   - The application creates a chess board using python-chess
   - Each agent is assigned a language model based on user selection

2. **Game Loop**:
   - Python-chess determines all valid moves for the current player
   - The current player agent (White or Black) analyzes the board and selects a move
   - The move is validated and executed on the board
   - The Master Agent provides analysis after each full turn
   - The process repeats until the game ends

3. **Game Termination**:
   - The game ends when checkmate, stalemate, or another draw condition is reached
   - The final result is displayed along with the reason for game termination

## Project Structure

- `app.py`: Main Streamlit application with UI and game flow
- `agents.py`: Agent definitions and initialization
- `utils.py`: Chess board logic and utility functions
- `requirements.txt`: Required Python packages

## Requirements

- Python 3.8+
- Streamlit
- Python-chess
- Agno framework
- API keys for the language models you want to use

## License

This project is licensed under the MIT License - see the LICENSE file for details.

