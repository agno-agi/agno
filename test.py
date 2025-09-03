from agno.models.openai import OpenAILike
from agno.agent import Agent
from agno.team.team import Team, TeamRunEvent
from agno.agent import RunEvent
import json



discovery_agent = Agent(
                model=OpenAILike(id="gpt-oss:20b", base_url="http://12.1.52.176:11434/v1", reasoning_effort="high"),
                instructions=[
                    """
                    At like a good agent.
                    """
                    ],
                show_tool_calls=True,
                telemetry=False,
            )

discovery_team = Team(
    model = OpenAILike(id="gpt-oss:20b", base_url="http://12.1.52.176:11434/v1", reasoning_effort="high"),
    members=[discovery_agent]
)

async def run():
    content_started = False
    member_content_started = False

    async for run_response_event in await discovery_team.arun(
        message="Hello",
        stream=True,
        stream_intermediate_steps=True,
    ):
        if run_response_event.event in [
            TeamRunEvent.run_started,
            TeamRunEvent.run_completed,
        ]:
            print({
                "type": "team_event",
                "event": run_response_event.event,
                "message": str(run_response_event.event)
            })
        
        if run_response_event.event in [
            RunEvent.run_started,
            RunEvent.run_completed,
        ]:
            print( {
                "type": "member_run_event",
                "event": run_response_event.event,
                "message": str(run_response_event.event)
            })
        
        if run_response_event.event in [TeamRunEvent.tool_call_started]:
            print(json.dumps({
                "type": "team_tool_call_started",
                "event": run_response_event.event,
                "tool_name": run_response_event.tool.tool_name,
                "tool_args": run_response_event.tool.tool_args
            }, indent=2))
        
        if run_response_event.event in [TeamRunEvent.tool_call_completed]:
            print(json.dumps({
                "type": "team_tool_call_completed",
                "event": run_response_event.event,
                "tool_name": run_response_event.tool.tool_name,
                "tool_result": run_response_event.tool.result
            }, indent=2))
            
        # Member events
        if run_response_event.event in [RunEvent.tool_call_started]:
            print(json.dumps({
                "type": "member_tool_call_started",
                "event": run_response_event.event,
                "tool_name": run_response_event.tool.tool_name,
                "tool_args": run_response_event.tool.tool_args
            }, indent=2))
        
        if run_response_event.event in [RunEvent.tool_call_completed]:
            print(json.dumps({
                "type": "member_tool_call_completed",
                "event": run_response_event.event,
                "tool_name": run_response_event.tool.tool_name,
                "tool_result": run_response_event.tool.result
            }, indent=2))
        
        if run_response_event.event in [TeamRunEvent.run_response_content]:
            if not content_started:
                print({
                    "type": "team_content_header",
                    "message": "TEAM CONTENT:"
                })
                content_started = True
            print(json.dumps({
                "type": "team_content",
                "content": run_response_event.content
            }, indent=2))
        
        if run_response_event.event in [RunEvent.run_response_content]:
            if not member_content_started:
                print({
                    "type": "member_content_header",
                    "message": "MEMBER CONTENT:"
                })
                member_content_started = True
            print(json.dumps({
                "type": "member_content",
                "content": run_response_event.content
            }, indent=2))

import asyncio

print(asyncio.run(run()))