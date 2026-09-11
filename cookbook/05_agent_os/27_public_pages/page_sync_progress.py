"""Native progress from a function step, without a synthetic agent/executor run."""

import argparse
import asyncio
from contextlib import aclosing

from agno.knowledge.page import SyncReport
from agno.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.types import StepOutput, StepProgress


async def sync_pages(step_input):
    from public_pages import knowledge

    await knowledge.asetup()
    async with aclosing(knowledge.astream_sync_pages(url=step_input.input)) as updates:
        async for update in updates:
            if isinstance(update, SyncReport):
                yield StepOutput(
                    content=update.model_dump(), success=update.status != "partial"
                )
            else:
                yield StepProgress(content=update.stage, data=update.model_dump())


async def check_step(step_input):
    yield StepProgress(content="Checking one page", data={"processed": 1})
    yield StepOutput(content="done")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="HTTPS documentation llms.txt URL")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run a function-only workflow without storage/provider calls",
    )
    args = parser.parse_args()
    if not args.check and not args.url:
        parser.error("provide a source URL or --check")
    workflow = Workflow(
        id="page-sync",
        steps=[
            Step(
                name="sync",
                executor=check_step if args.check else sync_pages,
                max_retries=0,
            )
        ],
        telemetry=False,
    )
    events = []
    async for event in workflow.arun(
        args.url or "check", stream=True, stream_events=True
    ):
        events.append(event)
        print(event.to_json())
    if args.check:
        assert any(event.event == "StepProgress" for event in events)
        assert events[-1].event == "WorkflowCompleted"


if __name__ == "__main__":
    asyncio.run(main())
