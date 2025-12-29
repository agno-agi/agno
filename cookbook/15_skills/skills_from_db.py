"""Skills from Database with AgentOS Example

This example demonstrates:
1. Agent with skills from both LocalSkills and DbSkills loaders
2. Serving the agent via AgentOS
3. Creating a new skill via API call after server starts

Run: python skills_from_db.py
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.skills import DbSkills, LocalSkills, Skills

# Database for storing skills
db = SqliteDb(
    id="skills-db",
    db_file="tmp/skills.db",
    skills_table="skills",
)

# Get the local skills directory
skills_dir = Path(__file__).parent / "skills"

# Create an agent with skills from BOTH local directory AND database
agent = Agent(
    name="Skilled Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    skills=Skills(
        loaders=[
            LocalSkills(str(skills_dir)),  # Local: code-review, git-workflow
            DbSkills(db=db),  # Database: docker-deployment (created via API)
        ],
        dynamic=True,  # Reload skills on each access
    ),
    instructions=[
        "You are a helpful assistant with access to specialized skills.",
    ],
    markdown=True,
)

# Docker deployment skill data - includes scripts and references
DOCKER_SKILL = {
    "name": "docker-deployment",
    "description": "Deploy Python applications using Docker containers",
    "instructions": """# Docker Deployment Skill

You are an expert in containerizing and deploying Python applications with Docker.

## When to Use This Skill
Use this skill when the user asks about:
- Creating Dockerfiles for Python apps
- Building and running Docker containers
- Docker Compose for multi-container setups
- Container best practices and optimization

## Deployment Process
1. **Analyze the application**: Identify dependencies and requirements
2. **Create Dockerfile**: Use the script template via `get_skill_reference`
3. **Build the image**: `docker build -t app-name .`
4. **Run the container**: `docker run -p 8000:8000 app-name`

## Available Resources
- Use `get_skill_reference("docker-deployment", "dockerfile-template.py")` for the Dockerfile generator
- Use `get_skill_reference("docker-deployment", "docker-commands.md")` for Docker commands
""",
    "version": 1,
    "scripts": [
        {
            "name": "dockerfile-template.py",
            "content": '''"""Dockerfile Generator for Python Applications"""

def generate_dockerfile(python_version="3.12", app_port=8000, use_uv=True):
    if use_uv:
        return f"""FROM python:{python_version}-slim AS builder
WORKDIR /app
RUN pip install uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

FROM python:{python_version}-slim
WORKDIR /app
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY --chown=appuser:appuser . .
EXPOSE {app_port}
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "{app_port}"]
"""
    return f"""FROM python:{python_version}-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE {app_port}
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "{app_port}"]
"""
''',
        }
    ],
    "references": [
        {
            "name": "docker-commands.md",
            "content": """# Docker Commands Cheatsheet

## Build & Run
```bash
docker build -t myapp:latest .
docker run -d -p 8000:8000 myapp:latest
docker run -e DATABASE_URL=... myapp:latest
```

## Manage Containers
```bash
docker ps                    # List running
docker logs -f <container>   # View logs
docker exec -it <container> bash
docker stop <container>
```

## Docker Compose
```bash
docker-compose up -d
docker-compose down
docker-compose logs -f
```
""",
        }
    ],
}


async def create_skill_via_api():
    """Create the docker-deployment skill via API call with retries."""
    base_url = "http://localhost:7777"
    max_retries = 15

    print("[Skill Creator] Starting skill creation task...", flush=True)

    async with httpx.AsyncClient() as client:
        # Wait for server to be ready
        for i in range(max_retries):
            try:
                response = await client.get(f"{base_url}/health", timeout=2)
                if response.status_code == 200:
                    print(f"[Skill Creator] Server ready after {i+1} attempts", flush=True)
                    break
            except httpx.RequestError:
                print(f"[Skill Creator] Waiting for server... attempt {i+1}/{max_retries}", flush=True)
            await asyncio.sleep(1)
        else:
            print("[Skill Creator] Server not ready after max retries", flush=True)
            return

        # Check if skill already exists
        try:
            response = await client.get(f"{base_url}/skills", timeout=5)
            if response.status_code == 200:
                existing = response.json().get("data", [])
                if any(s["name"] == "docker-deployment" for s in existing):
                    print("\n" + "=" * 60)
                    print("'docker-deployment' skill already exists in database")
                    print("=" * 60 + "\n", flush=True)
                    return
        except httpx.RequestError as e:
            print(f"[Skill Creator] Error checking existing skills: {e}", flush=True)

        # Create the skill via API
        try:
            response = await client.post(
                f"{base_url}/skills",
                json=DOCKER_SKILL,
                timeout=10,
            )
            if response.status_code == 201:
                print("Created 'docker-deployment' skill via API!")
            else:
                print(f"[Skill Creator] Failed to create skill: {response.status_code} - {response.text}", flush=True)
        except httpx.RequestError as e:
            print(f"[Skill Creator] Error creating skill: {e}", flush=True)


@asynccontextmanager
async def skill_creator_lifespan(_app):
    """Lifespan that creates the docker-deployment skill after startup."""
    # Startup: schedule skill creation as background task
    task = asyncio.create_task(create_skill_via_api())
    yield
    # Shutdown: cancel task if still running
    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# Create AgentOS with custom lifespan
agent_os = AgentOS(
    id="skills-db-demo",
    description="Skills Demo - Agent with Local + Database skills",
    agents=[agent],
    lifespan=skill_creator_lifespan,  # Add lifespan for skill creation
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="skills_from_db:app", reload=True)
