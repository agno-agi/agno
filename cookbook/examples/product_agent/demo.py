"""Call the running Product Agent over HTTP, then ask a follow-up and stream.
Start product_agent.py first. Each demo starts a fresh conversation.
"""

from uuid import uuid4

import httpx

# ---------------------------------------------------------------------------
# Create the client conversation
# ---------------------------------------------------------------------------
URL = "http://127.0.0.1:7777/agents/product-agent/runs"
PROMPTS = [
    "How do I schedule a weekly report in Acme Reports?",
    "Which plan do I need for that, and who can configure it?",
]

# ---------------------------------------------------------------------------
# Run the same API the documentation introduces
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = str(uuid4())
    with httpx.Client(timeout=120) as client:
        for question in PROMPTS:
            response = client.post(
                URL,
                data={
                    "message": question,
                    "user_id": "demo-user",
                    "session_id": session_id,
                    "stream": "false",
                },
            )
            response.raise_for_status()
            result = response.json()
            print(result["content"])
            print("Session:", result["session_id"], "Run:", result["run_id"])
        with client.stream(
            "POST",
            URL,
            data={
                "message": "How do I export only the filtered rows from a report?",
                "user_id": "demo-user",
                "session_id": session_id,
                "stream": "true",
            },
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    print(line)
