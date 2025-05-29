"""
Single Agent AG-UI Example

This example shows how to serve a single agent via AG-UI protocol.
"""
from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.app.fastapi.app import FastAPIApp
from agno.tools import tool

# Create a simple agent
agent = Agent(
    name="demo_agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="""
    You are a helpful AI assistant that can interact with frontend applications.
    You support frontend-defined tools and can maintain state across conversations.
    Be conversational and explain what you're doing.
    """,
    markdown=True,
    debug_mode=True,
)

# Add some backend tools
@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression"""
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return f"The result of {expression} is {result}"
    except Exception as e:
        return f"Error evaluating expression: {str(e)}"

@tool
def get_current_time() -> str:
    """Get the current time"""
    from datetime import datetime
    return f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

# Create the FastAPI app
app = FastAPIApp(
    agent=agent,
    name="Single Agent Demo",
    description="Demo of a single agent with AG-UI protocol"
)

# Add tools to the agent
agent.tools = [calculate, get_current_time]

if __name__ == "__main__":
    print("🚀 Starting Single Agent Demo...")
    print("📍 AG-UI endpoint: http://localhost:8000/agui/awp")
    print("📍 API docs: http://localhost:8000/docs")
    print("\n✨ This agent supports:")
    print("   - Backend tools: calculate, get_current_time")
    print("   - Frontend-defined tools (provided by the client)")
    print("   - State synchronization")
    print("   - Real-time streaming")
    
    # Get FastAPI instance with AG-UI enabled
    api = app.get_app(enable_agui=True)
    
    # Serve the application
    app.serve(api, host="0.0.0.0", port=8000) 