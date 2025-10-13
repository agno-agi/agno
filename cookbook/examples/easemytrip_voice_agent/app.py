"""
EaseMyTrip Voice Agent - AgentOS Deployment

Production-ready deployment using Agno's AgentOS.
Features:
- FastAPI server with REST API endpoints
- Session management with SQLite
- Conversation history persistence
- Production-ready architecture
"""

from agno.os import AgentOS
from voice_agent import easemytrip_agent

# Create AgentOS instance
agent_os = AgentOS(
    agents=[easemytrip_agent],
    name="EaseMyTrip Voice Assistant API",
    description="Voice-enabled customer support for EaseMyTrip with T&C knowledge"
)

# Get the FastAPI application
app = agent_os.get_app()


if __name__ == "__main__":
    """
    Run the AgentOS server.

    The server will be available at:
    - API: http://localhost:7780
    - Docs: http://localhost:7780/docs
    - Config: http://localhost:7780/config
    - AgentOS UI: https://os.agno.com (connect to this server)

    Usage:
        python app.py
    """
    print("="*80)
    print("EaseMyTrip Voice Agent - AgentOS Server")
    print("="*80)
    print()
    print("🚀 Starting server...")
    print()
    print("Available endpoints:")
    print("  📡 API Base:       http://localhost:7780")
    print("  📚 API Docs:       http://localhost:7780/docs")
    print("  ⚙️  Configuration:  http://localhost:7780/config")
    print("  💬 Chat with agent: POST http://localhost:7780/v1/agents/{agent_id}/runs")
    print()
    print("🖥️  AgentOS UI:      https://os.agno.com")
    print("   (Connect to http://localhost:7780 from the UI)")
    print()
    print("💾 Database:        tmp/easemytrip_agent.db")
    print()
    print("="*80)
    print()

    agent_os.serve(
        app="app:app",
        host="0.0.0.0",
        port=7780,
        reload=True  # Auto-reload on code changes
    )
