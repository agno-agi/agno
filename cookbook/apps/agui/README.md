# AG-UI Application Examples

This directory contains examples of how to create and serve Agno agents using the AG-UI protocol, which enables communication with frontend applications.

## What is AG-UI?

AG-UI (Agent-GUI) is a protocol that allows Agno agents to communicate with frontend applications. It supports:
- Real-time streaming responses
- Frontend-defined tools that the agent can call
- State synchronization between frontend and backend
- Compatible with various frontend frameworks

## Quick Start

### 1. Start the Backend

Run the basic AG-UI app:

```bash
cd cookbook/apps/agui
python app.py
```

This will start the backend server at `http://localhost:8000` with the chat agent.

### 2. Start the Frontend

In a separate terminal, start the frontend client:

```bash
cd cookbook/apps/agui/client
pnpm install  # or npm install
pnpm run dev  # or npm run dev
```

The frontend will be available at `http://localhost:3000`.

## Examples

### FastAPI server  (`app.py`)

The simplest example showing how to serve a chat agent via AG-UI:

```
python app.py
```

## Frontend Client

We have a feature viewer starter app in the `client` directory that provides a web interface to interact with the AG-UI agents.

### Features:
- Real-time chat interface
- Streaming responses
- Support for frontend tools
- Background color changing demo
- Clean UI with proper text visibility

### Setup:

1. **Install dependencies:**
   ```bash
   cd client
   pnpm install
   ```

2. **Start development server:**
   ```bash
   pnpm run dev
   ```

3. **Access the app:**
   Open `http://localhost:3000/feature/agentic_chat` in your browser

## Testing the Setup

1. Start the backend: `python basic.py`
2. Start the frontend: `cd client && pnpm run dev`
3. Visit `http://localhost:3000/feature/agentic_chat`
4. Try typing a message - you should see:
   - Black text (no more white-on-white)
   - Streaming responses from the agent
   - No empty message bubbles
   - Try: "Can you change the background color to blue?"
