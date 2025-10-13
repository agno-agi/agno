"""Small demo script that creates a sample AgentSession and prints JSON and Markdown exports."""
from pathlib import Path
import json

from agno.session.agent import AgentSession
from agno.run.agent import RunOutput
from agno.session.summary import SessionSummary
from agno.models.message import Message
from agno.session.exporter import export_session_to_json, export_session_to_markdown


def make_simple_session():
    s = AgentSession(session_id="s1", agent_id="agent1", user_id="user1", session_data={"key": "value"})
    r = RunOutput(run_id="r1", session_id="s1", agent_id="agent1", content="response text")
    r.messages = [Message(role="user", content="hello"), Message(role="assistant", content="world")]
    s.runs = [r]
    s.summary = SessionSummary(summary="short summary")
    return s


def main():
    session = make_simple_session()

    json_out = export_session_to_json(session, pretty=True)
    md_out = export_session_to_markdown(session)

    out_dir = Path("." )/ "tmp_export"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "session_s1.json"
    md_path = out_dir / "session_s1.md"

    json_path.write_text(json_out, encoding="utf-8")
    md_path.write_text(md_out, encoding="utf-8")

    print("--- JSON Export (pretty) ---")
    print(json_out)
    print()
    print(f"Wrote JSON to: {json_path.resolve()}")
    print()
    print("--- Markdown Export ---")
    print(md_out)
    print()
    print(f"Wrote Markdown to: {md_path.resolve()}")


if __name__ == "__main__":
    main()
