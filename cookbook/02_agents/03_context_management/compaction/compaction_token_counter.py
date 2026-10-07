"""
Compaction Token Counter
========================

`compact_at_tokens` is a number of tokens, so something has to count them. By default
compaction uses a local tiktoken estimate: in-process, a few milliseconds, and a few percent
off for models that do not use OpenAI's tokenizer.

`token_counter` replaces it with any function that takes `(messages, tools)` and returns an
int. Three common choices:

- Nothing (the default): the local tiktoken estimate.
- `model.count_tokens`: the provider's own count. `Model.count_tokens` already has this
  shape, so it can be passed as is. It is exact, but for Claude, OpenAI Responses, Gemini and
  Bedrock it is a network call on every size check (roughly 350-700 ms).
- Any tokenizer you have, such as a Hugging Face tokenizer for an open-weight model - wrapped
  in a small function, as below.

The counter decides when `compact_at_tokens` is reached and sizes the request during
overflow recovery. If it raises, compaction logs a warning and falls back to the local
estimate, so a counter can never fail a run.
"""

import json

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.message import Message
from agno.models.openai import OpenAIResponses
from agno.utils.tokens import count_tokens
from tokenizers import Tokenizer

# ---------------------------------------------------------------------------
# A Hugging Face tokenizer as a token counter
# ---------------------------------------------------------------------------
# The tokenizer an open-weight model was trained with counts its tokens exactly. Any
# tokenizer works the same way: turn the messages (and tool definitions) into text and
# count the tokens.
llama3 = Tokenizer.from_pretrained("Xenova/llama-3-tokenizer")


def llama3_counter(messages, tools):
    text = "\n".join(message.get_content_string() for message in messages)
    if tools:
        # Tools arrive as Function objects; count the schema the model is sent, not their repr.
        schemas = [
            tool.to_dict() if hasattr(tool, "to_dict") else tool for tool in tools
        ]
        text += "\n" + json.dumps(schemas)
    return len(llama3.encode(text).ids)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
model = OpenAIResponses(id="gpt-5.6-luna")

agent = Agent(
    model=model,
    db=SqliteDb(db_file="tmp/compaction_token_counter.db"),
    session_id="compaction_token_counter",
    add_history_to_context=True,
    compaction=Compaction(
        # Low enough that this short demo reaches it; the default is 150k.
        compact_at_tokens=1_500,
        uncompacted_runs=1,
        # The provider's own count. Swap in llama3_counter, or any function of your own.
        token_counter=model.count_tokens,
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Three counters, one conversation. They disagree, and by how much depends on the
    #    text - which is why the choice is yours.
    sample = [
        Message(
            role="user",
            content="Summarize the 2023 revenue: Q1 1.2M, Q2 1.45M, Q3 1.61M, Q4 2.07M.",
        ),
        Message(
            role="assistant",
            content="Revenue grew every quarter, from 1.2M to 2.07M, totalling 6.33M.",
        ),
    ]
    print("Counting the same two messages:")
    print(f"  local estimate (default) : {count_tokens(sample)}")
    print(f"  OpenAI count_tokens      : {model.count_tokens(sample)}")
    print(f"  Llama 3 tokenizer        : {llama3_counter(sample, None)}")

    # 2. A conversation that crosses compact_at_tokens, measured by the provider.
    questions = [
        "Explain how a database index works, in detail.",
        "Now compare that to a hash index, in detail.",
        "Explain covering indexes and index-only scans, in detail.",
        "Explain when an index hurts more than it helps, in detail.",
        "Explain partial and expression indexes, in detail.",
    ]
    for question in questions:
        run = agent.run(question)
        if run.compaction is not None:
            print(
                f"\nFolded {run.compaction.messages_compacted} messages "
                f"({run.compaction.tokens_before} -> {run.compaction.tokens_after} tokens)"
            )
        else:
            print(f"\nNo fold yet after: {question}")
