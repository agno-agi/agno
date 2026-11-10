from pathlib import Path

from agno.db.sqlite import SqliteDb

WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

gemini_agents_db = SqliteDb(db_file=str(WORKSPACE / "gemini_agents.db"))
