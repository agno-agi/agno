"""
Test script to verify that partial content and messages are preserved
when a Team run is cancelled.
"""

import threading
import time
from agno.agent import Agent
from agno.team import Team
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from agno.run.team import TeamRunEvent


def team_cancellation():
    """Test team cancellation with sync streaming - using threads like the agent example."""
    
    researcher = Agent(
        name="Researcher", 
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a researcher. Write detailed responses.",
    )
    
    team = Team(
        name="Test Team",
        members=[researcher],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=SqliteDb(db_file="tmp/test_team_cancel.db"),
        store_tool_messages=True,
        store_history_messages=True,
    )
    
    print("=" * 60)
    print("Test: Team Cancellation with Sync Streaming")
    print("=" * 60)
    
    # Container to share run_id between threads
    run_id_container = {}
    content_chunks = []
    
    def run_team_task():
        """Run the team in a separate thread."""
        try:
            for event in team.run(
                input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
                stream=True,
                stream_events=True,
            ):
                # Capture the run_id from events
                if hasattr(event, 'run_id') and event.run_id and "run_id" not in run_id_container:
                    run_id_container["run_id"] = event.run_id
                    print(f"Captured run_id: {event.run_id}")
                
                # Capture content chunks
                if hasattr(event, 'content') and event.content:
                    content_chunks.append(event.content)
                    print(event.content, end="", flush=True)
                
                # Check for cancellation event
                if hasattr(event, 'event') and event.event == TeamRunEvent.run_cancelled:
                    print(f"\nRun was cancelled!")
                    run_id_container["cancelled"] = True
                    return
                    
        except Exception as e:
            print(f"\nException in run: {e}")
            run_id_container["error"] = str(e)
    
    def cancel_after_delay(delay_seconds: int = 3):
        """Cancel the run after a delay."""
        print(f"Will cancel run in {delay_seconds} seconds...")
        time.sleep(delay_seconds)
        
        run_id = run_id_container.get("run_id")
        if run_id:
            print(f"\nCancelling run: {run_id}")
            success = team.cancel_run(run_id)
            if success:
                print(f"Run {run_id} marked for cancellation")
            else:
                print(f"Failed to cancel run {run_id}")
        else:
            print("No run_id found to cancel")
    
    # Start threads
    run_thread = threading.Thread(target=run_team_task, name="TeamRunThread")
    cancel_thread = threading.Thread(target=cancel_after_delay, args=(5,), name="CancelThread")
    
    run_thread.start()
    cancel_thread.start()
    
    run_thread.join()
    cancel_thread.join()
    
    # Check results
    print("\n" + "=" * 60)
    print("Checking stored session...")
    print("=" * 60)
    
    session = team.get_session(session_id=team.session_id)
    if session and session.runs:
        last_run = session.runs[-1]
        print(f"Run ID: {last_run.run_id}")
        print(f"Status: {last_run.status}")
        print(f"Content preserved: {bool(last_run.content)}")
        if last_run.content:
            print(f"Content length: {len(last_run.content)}")
            print(f"Content: {last_run.content}")
        print(f"Messages preserved: {bool(last_run.messages)}")
        if last_run.messages:
            print(f"Number of messages: {len(last_run.messages)}")
            print("\nMessages:")
            for i, msg in enumerate(last_run.messages):
                content_preview = str(msg.content)[:100] if msg.content else "None"
                print(f"  {i+1}. Role: {msg.role}, Content: {content_preview}...")
    else:
        print("No session or runs found!")
    
    print("\n" + "=" * 60)
    print(f"Chunks received before cancellation: {len(content_chunks)}")
    partial_content = ''.join(content_chunks)
    print(f"Partial content length: {len(partial_content)}")
    print(f"Partial content preview: {partial_content[:500]}..." if len(partial_content) > 500 else f"Partial content: {partial_content}")
    print("=" * 60)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("RUNNING SYNC TEST")
    print("=" * 80 + "\n")
    team_cancellation()
