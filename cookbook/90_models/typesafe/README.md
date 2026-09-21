# Jev / TypeSafe

Jev is a classification and routing model for Agno teams and workflows. Use it
to classify text, select a specialist or tool, and make structured decisions
between workflow steps. This avoids spending generative-model calls on finite
decisions and reserves those models for steps that need written answers.

Through the official TypeSafe Python SDK, Jev selects labels, estimates yes/no
probabilities, and scores against an ordered rubric. Its outputs are structured
decisions, not conversational replies. The same capabilities power classifier
tools, guardrails, and reference-based accuracy scoring. Start with `route_team.py`
to route requests to a specialist or `workflow.py` to classify a ticket before
a generative explanation step.

Install on Python 3.10 or newer:

```sh
pip install -e 'libs/agno[typesafe,openai]'
```

Set `TYPESAFE_API_KEY`. Examples using OpenAI also need `OPENAI_API_KEY`.
The default model is `jev-latest`; use `Jev(id="...")` to pin a model.
`api_key`, `base_url`, `timeout`, `client` and `async_client` are available on
the model, tools, guardrails, and accuracy scorer (`model` names the model on
tools, guardrails, and the scorer).
The SDK reads `TYPESAFE_BASE_URL` when no explicit URL is supplied.
For custom retries, pass a configured `TypeSafeClient` / `AsyncTypeSafeClient`.
Injected SDK clients remain caller-owned; Agno does not close them.

| Example | Behavior |
| --- | --- |
| `route_team.py` | Minimal two-member team: Jev routes, the selected specialist answers |
| `workflow.py` | Linear pipeline: Jev classifies a ticket, a generative model explains next steps |
| `agent_os.py` | Serve a typed classifier and a Jev-routed tech team with code, HTML, shell, and web-search tools |
| `accuracy_eval.py` | Display a generated answer, then score that same run against a reference |
| `structured_output.py` | Validated input and annotated Pydantic output |
| `basic.py` | Customer-support department, urgency, and fractional frustration score |
| `raw_questions.py` | Refund-policy decisions using all three primitives and explicit thresholds |
| `questions.py` | SDK `Choice` and `Noul` questions; JSON values as content |
| `async_basic.py` | Concurrent review classification with sentiment, topic flags, and recommendation intent |
| `async_decisions.py` | Async SDK through `Agent.aprint_response` |
| `tool_use.py` | Select a support queue and return the tool result |
| `tools_use_with_fallback.py` | Smart-home tool selection with finite arguments and explicit generative fallback |

Additional integration examples live with their Agno feature. The support
router adds routing policies and a confidence fallback; the workflow classifier
adds conditional branching. They complement the minimal examples above.

| Example | Behavior |
| --- | --- |
| [Agent guardrails](../../02_agents/08_guardrails/jev_guardrail.py) | Named checks, custom questions, thresholds, and rejection details |
| [Grounding](../../02_agents/08_guardrails/jev_grounding.py) | Check a generated answer against explicit evidence |
| [Team guardrails](../../03_teams/18_guardrails/jev_guardrail.py) | Async input checks before the leader runs |
| [Support router](../../03_teams/02_modes/route/04_jev_router.py) | Literal routing policies and a fallback member |
| [Workflow classifier](../../04_workflows/05_conditional_branching/router_jev_classifier.py) | Classify once and branch through a Router |
| [Feature discovery](../../91_tools/jev_tools.py) | An LLM authors questions with `ask_jev` to compare reviews |
| [Draft checks](../../91_tools/jev_tools_fixed_schema.py) | Developer-defined questions check a customer-support reply |
| [Accuracy scoring](../../09_evals/accuracy/README.md#jev-accuracy-scoring) | Supplied answers, concurrent scoring, and reference-backed eval suites |

Run, for example, `python cookbook/90_models/typesafe/structured_output.py`.

Agent examples use `agent.print_response` or `await agent.aprint_response` for
response panels; team and workflow examples use their corresponding
`print_response` methods. Rich `pprint` displays diagnostics from saved runs
without repeating model calls.

The concurrent review example reuses one agent with a separate session per input.
Its topic flags are fixed boolean fields; the display derives the list of topics
from those fields. The smart-home example simulates device actions and selects
multiple doors using boolean arguments. A no-tool result is handled explicitly
by a generative agent; SDK failures are surfaced instead of triggering fallback.

Both `Jev` and `JevTools` lazily create the official `TypeSafeClient` for sync
calls and `AsyncTypeSafeClient` for async calls. You can inject them with `client`
and `async_client`. `Agent.run`/`arun` choose the model's corresponding path;
toolkit pairs include `evaluate`/`aevaluate` and `ask_jev`/`aask_jev`.

## Accuracy scoring

Import `JevAccuracyScorer` from `agno.scorer.typesafe` to compare completed Agent
or Team runs with a reference using `score(run, expected=...)` or
`await ascore(run, expected=...)`. One Noul question produces a correctness
probability; an inclusive threshold (default 0.8) determines pass/fail.
The reason is a threshold explanation, and `Score.detail` retains provider
metadata. Calibrate the threshold on your data; mean probability is not dataset
accuracy. SDK failures remain errors rather than ordinary failing scores.

The [accuracy cookbook](../../09_evals/accuracy/README.md#jev-accuracy-scoring)
contains three full examples and setup instructions. The supplied-answer and
async examples need only `TYPESAFE_API_KEY`; generated-answer examples also need
OpenAI credentials. `AccuracyEval(model=Jev())` remains unsupported; use the
custom scorer directly or through `Case(scorer=..., expected=...)`.

## Serve with AgentOS

Install the server dependencies and start the example from the repository root:

```sh
pip install -e 'libs/agno[typesafe,openai,os]' ddgs
python cookbook/90_models/typesafe/agent_os.py
```

Set `TYPESAFE_API_KEY` and `OPENAI_API_KEY`. Open `http://localhost:7777/docs`
to try the API, or connect `http://localhost:7777` at `https://os.agno.com`.

- **Ticket Classifier** (`POST /agents/ticket-classifier/runs`) returns typed
  department and urgency decisions using only Jev.
- **Tech Team** (`POST /teams/tech-team/runs`) uses Jev to choose one specialist,
  forwards the original request, and returns that specialist's response and artifacts.

The tech team reuses four agents with `OpenAIResponses`:

| Specialist | Built-in tool | Example request |
| --- | --- | --- |
| Backend Engineer | `FileGenerationTools.generate_code_file` | "Generate a Python FastAPI service with a health endpoint as health_api.py." |
| Backend Engineer | `FileGenerationTools.generate_code_file` | "Generate a Node.js HTTP server with a health endpoint as server.js." |
| Frontend Engineer | `FileGenerationTools.generate_html_file` | "Create a responsive HTML landing page for a developer conference." |
| Shell Engineer | `ShellTools.run_shell_command` | "Run a command to list the generated files and show the Python version." |
| Research Engineer | `WebSearchTools.web_search` | "Search the web for FastAPI deployment documentation and summarize the options." |

Submit a request in the `message` form field. Route mode selects one specialist
per request, so ask separately to generate code and then execute it. Source and
HTML files are returned as artifacts and also saved to `tmp/jev_tech_team`.
The shell uses that directory as its working directory and executes on the host;
the directory is not a sandbox. Web search uses `ddgs` and needs no extra API key.

One shared `JevGuardrail` checks user input through `pre_hooks` on the team and
each specialist. It checks for prompt injection, harmful requests, and requests
to create or execute harmful code, using a configurable `0.7` risk threshold.
This example checks user input only; generated code and tool calls are not reviewed.

The separate Ticket Classifier still accepts billing or technical tickets, such
as "I was charged twice" or "Nobody can log in", and returns department/urgency.

Set the `stream` form field to `false` for a single JSON response or `true`
for events. Sessions are stored locally in `tmp/jev_agent_os.db`.

## Model schemas and instructions

Use either `Jev(questions={...})` or an Agent `output_schema` annotated with
`JevField`. They are alternative sources of questions, so combining them is
rejected. An unannotated arbitrary JSON schema cannot be generated by Jev.
`JevField` preserves ordinary Pydantic validation and writes `x-jev` metadata
into JSON schema, allowing the same schema to be serialized and reused.
Fixed nested objects are supported; recursive objects and variable-length
output arrays are not.

| Primitive | Output field | Meaning |
| --- | --- | --- |
| `Noul` | `float` | Probability from 0 to 1 |
| `Noul` with explicit `threshold` | `bool` | Probability greater than or equal to threshold |
| `Choice` | `str`, string `Literal`, string `Enum` | One criterion label |
| `Score` | `float` | Fractional position in 2–10 ordered criteria, starting at zero |

String Literals/Enums must match the Choice labels. Scores are never silently
rounded to integers. Question IDs are not visible to Jev; give every question
meaningful instructions. Questions are answered independently against the same
state, so one question cannot reference another question's answer.

For the model, the latest user content is `state.input`; conversation messages
are retained in `state.messages` with their roles. JSON input is decoded when
possible. System/developer messages are attached to each question's instructions.
Thus Agent/Team instructions can describe routing and classification policies,
but cannot add free-text generation capabilities.

Normal values appear in `RunOutput.content`. Full answers, probabilities,
confidence (where provided), model, usage and request ID are retained under
`RunOutput.model_provider_data["typesafe"]`. Streaming emits one completed
decision, followed by any selected tool/member's native stream. There is no
simulated token stream from Jev.

Only questions mode supports model response caching. Cache keys include question
criteria, instructions, state, and complete output schemas. Dispatch caching is
rejected so a cached answer cannot bypass execution or approvals.

## Routing and finite tool calls

Configure the leader with `Jev(mode="route")`, the Team with `mode="route"`
and `determine_input_for_members=False`, and give every member an explicit
generative model. The current resolved roster supplies member IDs and
descriptions; Jev never generates a member ID or rewrites the member's task.
The original request is forwarded through Agno's member delegation path.
Additional leader tools and a leader output schema are unsupported; put output
schemas on members. Default routing chooses the best match.
Jev Team leaders support route mode only; broadcast, coordinate, and tasks modes
require a generative leader.

`min_confidence` optionally sets a routing threshold. Below it,
`fallback_member_id` selects a current member; without a fallback the model
raises `JevAbstentionError` and no member runs. `Agent.run`/`Team.run` follow
Agno's usual error handling and return an error status. Test thresholds on your
own cases; the integration does not establish calibration.

`Jev(mode="tools")` supports booleans and finite scalar enums/Literals,
including nullable values and optional/defaulted arguments. Unrestricted
strings, numbers, objects and arrays are rejected, including defaulted ones.
There are at most 255 choices (including the no-tool choice). The selector and
candidate arguments are evaluated together; each argument explicitly assumes
its tool was selected, and only the selected tool's arguments are consumed.
`tool_choice="none"`, `"required"` and a forced function are honored.

At most one tool is dispatched per run. Its result is returned directly.
Tool confirmations, external execution and resumes use Agno's existing flow;
resuming does not request another Jev decision. Original tool flags are preserved
across runs.

## Jev as a tool

Import `JevTools` from `agno.tools.typesafe`; the original
`agno.tools.models.typesafe` path remains supported.

`JevTools()` exposes `ask_jev(state, questions)`. The LLM supplies text or a
JSON-encoded object/array and a list of typed `JevQuestion` objects:

```python
{"id": "urgent", "type": "noul", "instructions": "Does state.ticket require immediate attention?", "options": []}
```

The toolkit translates `options` into SDK criteria: an empty list for Noul,
1–255 distinct labels for Choice, or 2–10 ordered descriptions for Score.
It validates the questions before calling Jev. JSON objects/arrays are decoded
and passed directly as state, so `{"ticket": "..."}` is read as `state.ticket`.
Toolkit instructions explain how to write independent questions and compare
texts using consistent rubrics. Override `instructions` or set
`add_instructions=False` to customize that guidance.

`JevTools(questions=...)` or `JevTools(output_schema=...)` exposes `evaluate`.
An optional `input_schema` validates the caller's state and describes it in the
function schema. The validated value is available at `state.input`.
Fixed configurations keep dynamic questions disabled by default; set
`enable_ask_jev=True` to expose both tools. `enable_evaluate=False` disables
the fixed operation. An `input_schema` also validates decoded `ask_jev` state.

The existing `allow_dynamic_questions=True` API still exposes
`evaluate_questions(state, questions)` with raw SDK question dictionaries and
`state.input`. Prefer `ask_jev` for LLM-authored questions: Noul uses `options=[]`,
avoiding the SDK's easy-to-mistype `criteria` keys (`true`/`false`, not `yes`/`no`).
All operations return JSON containing `values` and raw `typesafe` metadata.
Async variants register under the same tool names.

## Guardrails

Import `JevGuardrail` from `agno.guardrails` or `agno.guardrails.typesafe`.
Add it to `pre_hooks` for input checks or `post_hooks` for output checks:

```python
JevGuardrail(
    checks=["prompt_injection", "pii"],
    questions={
        "off_topic": {
            "instructions": "Is the content unrelated to travel?",
            "threshold": 0.8,
            "check_trigger": "off_topic",
        },
    },
    threshold=0.7,
)
```

Available checks: `prompt_injection`, `harmful_request`, `self_harm`,
`medical_advice`, `pii`, and `toxicity`. Presets have distinct questions for
input and output. The default constructor checks prompt injection and harmful
requests at 0.7. Supplying only custom `questions` runs only those questions.
`questions={"off_topic": "Is the content unrelated to travel?"}` is also accepted.
All checks are batched; a probability at or above its threshold blocks the run.
Custom dictionaries can include SDK Noul `criteria`, `threshold`, and
`check_trigger`. Errors include failed IDs, probabilities, thresholds, and raw
SDK answers. Validate thresholds against your own use cases.

For richer policies, use `JevGuardrail(questions=..., block_when=...)` or an
annotated `output_schema` with `block_when`. This advanced interface accepts
Choice, Noul, and Score decisions. The existing `pii(threshold=...)`,
`prompt_injection(threshold=...)`, and
`grounding(threshold=..., state_builder=...)` classmethods remain supported.

By default, guardrails receive `state.input` or `state.output`. A `state_builder`
can accept normal hook context such as `run_input`, `run_output`, `run_context`,
`agent`/`team`, and `session`. Async builders work with `arun`. Grounding requires
the builder to supply nonempty `evidence` and an `output` to check.

Rejections raise `InputCheckError`/`OutputCheckError` with raw answers in
`additional_data`. SDK and policy failures propagate through hooks, including
background-hook mode. Failed output checks clear the final content before Agno
returns an error run; inspect the run status. Successful output-check metadata
is stored in `model_provider_data["typesafe_guardrails"]`.

Output guardrails reject `stream=True` before generation, including continuation
runs. Input guardrails may precede a streamed answer. The check evaluates text/
JSON; supply extracted text explicitly for media. It does not undo tool effects
that happened before an output check.

Official references: [Python SDK](https://docs.typesafe.ai/sdk/python),
[Choice](https://docs.typesafe.ai/primitives/choice),
[Noul](https://docs.typesafe.ai/primitives/noul),
[Score](https://docs.typesafe.ai/primitives/score).

## Local tests

```sh
python -m pytest libs/agno/tests/unit/models/test_typesafe.py -q
```

The tests use mocked providers, including the real SDK's HTTP transport boundary.
See `TEST_LOG.md` for coverage and live-test limitations.
