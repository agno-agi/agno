"""
Basic AG-UI Application Example

This example shows how to run the AG-UI application with all agents.
"""
from agno.app.agui import app

if __name__ == "__main__":
    print("🚀 Starting AG-UI Application...")
    print("📍 Access the agents at:")
    print("   - http://localhost:8000/agui/awp?agent=chat_agent")
    print("\n📍 List all agents: http://localhost:8000/agui/agents")
    print("📍 API docs: http://localhost:8000/docs")
    
    # Get FastAPI instance with AG-UI enabled
    api = app.get_app(enable_agui=True)
    
    # Serve the application
    app.serve(api, host="0.0.0.0", port=8000)