"""
TopK Context Provider
=====================

End-to-end example:
  1. Creates a TopK dataset with a description.
  2. Uploads a PDF and waits for it to be indexed.
  3. Runs an agent that discovers the dataset via list_datasets,
     then queries it — showing TopK progress events in real time.

Requires:
    TOPK_API_KEY   — TopK API key
    TOPK_REGION    — TopK region   (e.g. "aws-us-east-1-elastica")
    OPENAI_API_KEY — OpenAI API key

Get your API: https://console.topk.io
See available regions: https://docs.topk.io/regions
"""

from __future__ import annotations

import asyncio
import os
import urllib.request

import topk_sdk
from agno.agent import Agent
from agno.context.topk import TopKContextProvider, TopKProgressEvent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunContentEvent

DATASET_NAME = "thai-recipes"
PDF_URL = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"


def setup_dataset(client: topk_sdk.Client) -> None:
    # Create the dataset (skip if it already exists)
    try:
        client.datasets().create(DATASET_NAME)
        print(f"Created dataset '{DATASET_NAME}'")
    except Exception:
        print(f"Dataset '{DATASET_NAME}' already exists, skipping create")

    # Set a description — the agent reads this from list_datasets to decide
    # which datasets are relevant to a question before querying them.
    client.datasets().update(
        DATASET_NAME,
        description=(
            "Traditional Thai recipes: ingredients, preparation steps, and cooking "
            "techniques for dishes like Pad Thai, Tom Yum, Green Curry, and more."
        ),
    )

    # Download and upload the PDF
    print(f"Uploading {PDF_URL} ...")
    with urllib.request.urlopen(PDF_URL) as resp:
        pdf_bytes = resp.read()

    handle = client.dataset(DATASET_NAME).upsert_file(
        doc_id="thai-recipes-pdf",
        input=("ThaiRecipes.pdf", pdf_bytes, "application/pdf"),
        metadata={"source": PDF_URL},
    )

    print("Waiting for indexing to complete...")
    client.dataset(DATASET_NAME).wait_for_handle(handle)
    print("Dataset ready.\n")


async def main() -> None:
    client = topk_sdk.Client(
        api_key=os.environ["TOPK_API_KEY"],
        region=os.environ.get("TOPK_REGION", "aws-us-east-1-elastica"),
    )

    setup_dataset(client)

    topk = TopKContextProvider()

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=topk.get_tools(),
        instructions=topk.instructions(),
        markdown=True,
    )

    prompt = (
        "What Thai recipes are available? Give me a few with their key ingredients."
    )
    print(f"> {prompt}\n")

    async for event in agent.arun(prompt, stream=True):
        if isinstance(event, TopKProgressEvent):
            print(f"  [topk] {event.update}")
        elif isinstance(event, RunContentEvent) and event.content:
            print(event.content, end="", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
