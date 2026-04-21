"""
Slack HITL UX Verification Harness
===================================

Standalone FastAPI server that logs every /slack/interactions payload,
plus a CLI to post test layouts to a Slack DM. Use this to empirically
verify which Block Kit elements ship state on SUBMIT and which don't,
BEFORE committing to an HITL design.

Replaces any running cookbook on port 7778 for the duration of the test.
Ngrok tunnel at https://<tunnel>/slack/interactions must be pointed at 7778.

Usage:
  # Terminal A — start the log server
  python cookbook/05_agent_os/interfaces/slack/hitl_ux_verify.py serve

  # Terminal B — post each test layout; click in Slack; watch Terminal A.
  python cookbook/05_agent_os/interfaces/slack/hitl_ux_verify.py post input_only
  python cookbook/05_agent_os/interfaces/slack/hitl_ux_verify.py post buttons_only
  python cookbook/05_agent_os/interfaces/slack/hitl_ux_verify.py post mixed
  python cookbook/05_agent_os/interfaces/slack/hitl_ux_verify.py post full_pause_card

Each test proves or disproves a specific claim about Slack's behavior.
Read the docstrings on each layout function below.
"""

import json
import os
import sys

import httpx
from fastapi import FastAPI, HTTPException, Request
from slack_sdk.signature import SignatureVerifier

# ---------------------------------------------------------------------------
# Config — change this to your target Slack DM/channel ID before running
# ---------------------------------------------------------------------------

CHANNEL_ID = os.environ.get("SLACK_TEST_CHANNEL_ID", "D0AGXPEGJ8M")
SLACK_TOKEN = os.environ["SLACK_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

app = FastAPI()
verifier = SignatureVerifier(SLACK_SIGNING_SECRET)


# ---------------------------------------------------------------------------
# Server — logs every block_actions payload
# ---------------------------------------------------------------------------


@app.post("/slack/events")
async def events(request: Request):
    body = await request.body()
    ts = request.headers.get("X-Slack-Request-Timestamp", "")
    sig = request.headers.get("X-Slack-Signature", "")
    if not verifier.is_valid(body=body.decode(), timestamp=ts, signature=sig):
        raise HTTPException(403, "bad signature")
    payload = json.loads(body)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
    return {"ok": True}


@app.post("/slack/interactions")
async def interactions(request: Request):
    body = await request.body()
    ts = request.headers.get("X-Slack-Request-Timestamp", "")
    sig = request.headers.get("X-Slack-Signature", "")
    if not verifier.is_valid(body=body.decode(), timestamp=ts, signature=sig):
        raise HTTPException(403, "bad signature")
    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))

    action = (payload.get("actions") or [{}])[0]
    state_values = (payload.get("state") or {}).get("values") or {}

    print("=" * 72)
    print(f"TYPE:          {payload.get('type')}")
    print(f"ACTION_ID:     {action.get('action_id')}")
    print(f"BLOCK_ID:      {action.get('block_id')}")
    print(f"ACTION_VALUE:  {action.get('value')}")
    print(f"USER:          {payload.get('user', {}).get('username')}")
    print(f"")
    print(f"STATE.VALUES  (everything that ships to us):")
    print(json.dumps(state_values, indent=2) if state_values else "  <empty>")
    print("=" * 72)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Test layouts — each proves or disproves a specific claim
# ---------------------------------------------------------------------------


def layout_input_only():
    """CLAIM: Input blocks ship state.values on any button click in the same
    message. This is the baseline — if this fails, the whole design is wrong.

    Expected on SUBMIT: state.values has {'b_decision': {'e': {'selected_option': ...}}}
    """
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "TEST 1: Input block state"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "*Claim:* radio_buttons in Input block ships state.values on SUBMIT.",
                }
            ],
        },
        {
            "type": "input",
            "block_id": "b_decision",
            "label": {"type": "plain_text", "text": "Decision"},
            "element": {
                "type": "radio_buttons",
                "action_id": "e",
                "options": [
                    {
                        "text": {"type": "plain_text", "text": "Confirm"},
                        "value": "confirm",
                    },
                    {
                        "text": {"type": "plain_text", "text": "Reject"},
                        "value": "reject",
                    },
                ],
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": "submit",
            "elements": [
                {
                    "type": "button",
                    "action_id": "submit",
                    "text": {"type": "plain_text", "text": "SUBMIT"},
                    "style": "primary",
                    "value": "go",
                },
            ],
        },
    ]


def layout_buttons_only():
    """CLAIM: Regular buttons DO NOT carry state. Two buttons per row + SUBMIT.
    Click Confirm on row 1, Reject on row 2, then SUBMIT.

    Expected on SUBMIT: state.values is empty. Button click history is lost.
    This is what forces us to use chat.update OR switch to state-bearing elements.
    """

    def row(name, args):
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"🔧 *{name}*\n    `{args}`"},
            },
            {
                "type": "actions",
                "block_id": f"row_{name}",
                "elements": [
                    {
                        "type": "button",
                        "action_id": f"confirm_{name}",
                        "text": {"type": "plain_text", "text": "✓ Confirm"},
                        "style": "primary",
                        "value": f"{name}:confirm",
                    },
                    {
                        "type": "button",
                        "action_id": f"reject_{name}",
                        "text": {"type": "plain_text", "text": "✗ Reject"},
                        "style": "danger",
                        "value": f"{name}:reject",
                    },
                ],
            },
        ]

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "TEST 2: Button-only (stateless)"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "*Claim:* buttons do NOT ship state. SUBMIT's payload will have `state.values == {}` even after clicking buttons.",
                }
            ],
        },
        *row("delete_file", "path: /tmp/demo.txt"),
        *row("transfer_funds", "account: 42, $500"),
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": "submit",
            "elements": [
                {
                    "type": "button",
                    "action_id": "submit",
                    "text": {"type": "plain_text", "text": "SUBMIT"},
                    "style": "primary",
                    "value": "go",
                },
            ],
        },
    ]


def layout_mixed():
    """CLAIM: This is the UX user asked for — regular Confirm/Reject buttons
    + multiline plain_text_input + SUBMIT. Multiline input DOES ship state;
    buttons DO NOT.

    Expected on SUBMIT: state.values = {'b_note': {'e': {'value': '<whatever was typed>'}}}
    Buttons are absent.
    """
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "TEST 3: Mixed — buttons + multiline input",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "*Claim:* multiline input ships state; buttons don't. Click Confirm, type a note, SUBMIT.",
                }
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🔧 *delete_file*\n    `path: /tmp/demo.txt`",
            },
        },
        {
            "type": "actions",
            "block_id": "row_delete",
            "elements": [
                {
                    "type": "button",
                    "action_id": "confirm_delete",
                    "text": {"type": "plain_text", "text": "✓ Confirm"},
                    "style": "primary",
                    "value": "delete:confirm",
                },
                {
                    "type": "button",
                    "action_id": "reject_delete",
                    "text": {"type": "plain_text", "text": "✗ Reject"},
                    "style": "danger",
                    "value": "delete:reject",
                },
            ],
        },
        {
            "type": "input",
            "block_id": "b_note",
            "label": {"type": "plain_text", "text": "Optional note"},
            "element": {
                "type": "plain_text_input",
                "action_id": "e",
                "multiline": True,
                "placeholder": {"type": "plain_text", "text": "Type a reason here…"},
            },
            "optional": True,
        },
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": "submit",
            "elements": [
                {
                    "type": "button",
                    "action_id": "submit",
                    "text": {"type": "plain_text", "text": "SUBMIT"},
                    "style": "primary",
                    "value": "go",
                },
            ],
        },
    ]


def layout_full_pause_card():
    """CLAIM: All 4 HITL pause types can render inline in one message using
    state-bearing elements. On SUBMIT, state.values carries every field.

    Includes: confirmation (radio), user_input (plain_text_input),
    user_feedback (radio), external_execution (multiline plain_text_input).
    """
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "TEST 4: Full pause card (all 4 pause types)",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "*Claim:* one message can host all 4 pause types with state.",
                }
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🔧 *delete_file* (confirmation)\n    `path: /tmp/demo.txt`",
            },
        },
        {
            "type": "input",
            "block_id": "b_confirm",
            "label": {"type": "plain_text", "text": "Decision"},
            "element": {
                "type": "radio_buttons",
                "action_id": "e",
                "options": [
                    {
                        "text": {"type": "plain_text", "text": "Confirm"},
                        "value": "confirm",
                    },
                    {
                        "text": {"type": "plain_text", "text": "Reject"},
                        "value": "reject",
                    },
                ],
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "🔧 *send_email* (user_input)"},
        },
        {
            "type": "input",
            "block_id": "b_to_address",
            "label": {"type": "plain_text", "text": "to_address"},
            "element": {
                "type": "plain_text_input",
                "action_id": "e",
                "placeholder": {"type": "plain_text", "text": "user@example.com"},
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "❓ *vacation_style* (user_feedback — what kind of vacation?)",
            },
        },
        {
            "type": "input",
            "block_id": "b_feedback",
            "label": {"type": "plain_text", "text": "Choose one"},
            "element": {
                "type": "radio_buttons",
                "action_id": "e",
                "options": [
                    {"text": {"type": "plain_text", "text": "Beach"}, "value": "beach"},
                    {"text": {"type": "plain_text", "text": "City"}, "value": "city"},
                    {
                        "text": {"type": "plain_text", "text": "Nature"},
                        "value": "nature",
                    },
                ],
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🚀 *execute_shell_command* (external_execution)\n    `command: ls`",
            },
        },
        {
            "type": "input",
            "block_id": "b_ext_result",
            "label": {"type": "plain_text", "text": "Paste result"},
            "element": {
                "type": "plain_text_input",
                "action_id": "e",
                "multiline": True,
                "placeholder": {
                    "type": "plain_text",
                    "text": "e.g. file1.txt\nfile2.txt",
                },
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": "submit",
            "elements": [
                {
                    "type": "button",
                    "action_id": "submit",
                    "text": {"type": "plain_text", "text": "SUBMIT"},
                    "style": "primary",
                    "value": "go",
                },
                {
                    "type": "button",
                    "action_id": "cancel",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "style": "danger",
                    "value": "cancel",
                },
            ],
        },
    ]


def layout_card_minimal():
    """CLAIM: Slack accepts the new `card` block via raw chat.postMessage.

    Probes the API: does Slack's REST endpoint accept type=card today, in this
    workspace? If chat.postMessage returns ok=False with invalid_blocks, the
    spec's card-based design needs a fallback.

    Expected on success: a single card with title + body + Confirm/Reject.
    """
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "TEST: card block (minimal)"},
        },
        {
            "type": "card",
            "block_id": "card_min",
            "title": {"type": "plain_text", "text": "delete_file"},
            "subtitle": {"type": "mrkdwn", "text": "_confirmation required_"},
            "body": [
                {"type": "mrkdwn", "text": "path: `/tmp/demo.txt`"},
            ],
            "actions": {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "card_confirm",
                        "text": {"type": "plain_text", "text": "Confirm"},
                        "style": "primary",
                        "value": "go",
                    },
                    {
                        "type": "button",
                        "action_id": "card_reject",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "value": "no",
                    },
                ],
            },
        },
    ]


def layout_card_with_input():
    """CLAIM: card and Input can coexist as siblings at message level.

    Spec's claim: card.actions can't hold inputs, but card next to a separate
    Input block renders fine. Verify that a SUBMIT click on a card button OR
    on a sibling Actions block ships state.values.
    """
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "TEST: card + sibling Input"},
        },
        {
            "type": "card",
            "block_id": "card_send",
            "title": {"type": "plain_text", "text": "send_email"},
            "subtitle": {"type": "mrkdwn", "text": "_user_input required_"},
            "body": [
                {"type": "mrkdwn", "text": "to: `priti@example.com`"},
            ],
            "actions": {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "card2_confirm",
                        "text": {"type": "plain_text", "text": "Confirm"},
                        "style": "primary",
                        "value": "go",
                    },
                    {
                        "type": "button",
                        "action_id": "card2_reject",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "value": "no",
                    },
                ],
            },
        },
        {
            "type": "input",
            "block_id": "subj",
            "label": {"type": "plain_text", "text": "subject"},
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "placeholder": {"type": "plain_text", "text": "Weekly update"},
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": "submit_row",
            "elements": [
                {
                    "type": "button",
                    "action_id": "submit",
                    "text": {"type": "plain_text", "text": "SUBMIT"},
                    "style": "primary",
                    "value": "go",
                },
            ],
        },
    ]


def layout_card_no_subtitle():
    """CLAIM: card without subtitle is also accepted (flexibility check).

    If the minimal card requires every field, our builder needs to always set
    them. If subtitle is optional, we can omit it for tools without args.
    """
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "TEST: card without subtitle"},
        },
        {
            "type": "card",
            "block_id": "card_terse",
            "title": {"type": "plain_text", "text": "noop_tool"},
            "body": [
                {"type": "mrkdwn", "text": "_no arguments_"},
            ],
            "actions": {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "card3_confirm",
                        "text": {"type": "plain_text", "text": "Confirm"},
                        "style": "primary",
                        "value": "go",
                    },
                ],
            },
        },
    ]


LAYOUTS = {
    "input_only": (
        "Baseline — radio_buttons in Input block ships state",
        layout_input_only,
    ),
    "buttons_only": (
        "Buttons ONLY — verify they don't carry state",
        layout_buttons_only,
    ),
    "mixed": (
        "Buttons + multiline input + SUBMIT — the UX you asked about",
        layout_mixed,
    ),
    "full_pause_card": (
        "All 4 pause types inline in one message",
        layout_full_pause_card,
    ),
    "card_minimal": (
        "New card block — minimal title+body+actions",
        layout_card_minimal,
    ),
    "card_with_input": (
        "Card + sibling Input — production scenario",
        layout_card_with_input,
    ),
    "card_no_subtitle": (
        "Card without subtitle — flexibility check",
        layout_card_no_subtitle,
    ),
}


# ---------------------------------------------------------------------------
# CLI dispatcher
# ---------------------------------------------------------------------------


def post_layout(layout_name: str):
    if layout_name not in LAYOUTS:
        print(f"Unknown layout '{layout_name}'. Available: {', '.join(LAYOUTS)}")
        sys.exit(1)
    description, fn = LAYOUTS[layout_name]
    blocks = fn()
    resp = httpx.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={"channel": CHANNEL_ID, "text": description, "blocks": blocks},
    )
    data = resp.json()
    if data.get("ok"):
        print(f"Posted '{layout_name}' — {description}")
        print(f"  Slack message ts: {data.get('ts')}")
        print(f"  Channel:          {CHANNEL_ID}")
        print(f"  Now click in Slack and watch the server console for payloads.")
    else:
        print(f"Failed: {data}")
        sys.exit(1)


def serve():
    import uvicorn

    print("HITL UX verification server on http://localhost:7778")
    print("Point Slack app Event Subscriptions and Interactivity URLs at:")
    print("  https://<your-ngrok>/slack/events")
    print("  https://<your-ngrok>/slack/interactions")
    print("Post test layouts with:  python this_file.py post <layout>")
    uvicorn.run(app, host="0.0.0.0", port=7778)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python hitl_ux_verify.py [serve|post <layout>]")
        print("Layouts:")
        for name, (desc, _) in LAYOUTS.items():
            print(f"  {name:20s}  {desc}")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "serve":
        serve()
    elif cmd == "post" and len(sys.argv) >= 3:
        post_layout(sys.argv[2])
    else:
        print(f"Unknown command '{cmd}'. Use 'serve' or 'post <layout>'.")
        sys.exit(1)
