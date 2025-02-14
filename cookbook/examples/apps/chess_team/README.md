# Chess Team Agent

A sophisticated chess application where multiple AI agents collaborate to play chess against each other. The system features:
- White Piece Agent vs Black Piece Agent for move selection
- Legal Move Agent to validate moves
- Master Agent to coordinate the game and check for end conditions

> Note: Fork and clone the repository if needed

## Setup

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/apps/chess_team/requirements.txt
```

### 3. Set up environment variables

Create a `.envrc` file or export your API keys:

```shell
export OPENAI_API_KEY=your_api_key_here
```

### 4. Run the application

```shell
streamlit run cookbook/examples/apps/chess_team/app.py
```
- Open [localhost:8501](http://localhost:8501) to view the Chess Teams Agent.

### 5. Message us on [discord](https://agno.link/discord) if you have any questions

