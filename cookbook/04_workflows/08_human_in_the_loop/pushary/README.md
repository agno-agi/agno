# Customer phone approval for a persisted Agno workflow

Pause before releasing an order, send its details to the customer's enrolled
phone through Pushary, then restore and continue the same Agno run in a new
worker. The demonstration writes one local SQLite order. It does not charge or
ship anything, and needs no model API key.

This independently maintained application example uses **Agno 3.0.9** and the
published **Pushary Python SDK 2.1.1**. It adds no toolkit, model-controlled
approval function, or new distributable package.

## Run

Use Python 3.12+ and a Pushary Partner API key for your enrolled test customer.
[Customer enrollment](https://github.com/Pushary/pushary-python#two-calls-to-add-human-in-the-loop) happens
in your backend; the model must not choose the tenant, recipient or credentials.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Inject PUSHARY_API_KEY securely; do not put it in source or shell history.
.venv/bin/python run.py start /tmp/agno-order-1 demo-store TEST_CUSTOMER_ID
# Answer the request on the customer's phone, then launch a new worker:
.venv/bin/python run.py resume /tmp/agno-order-1 demo-store TEST_CUSTOMER_ID
```

The first command starts Agno's native `HumanReview` confirmation and saves the
pause to `workflow.db` before requesting the phone decision. A pending result is
reported as `blocked`; no order is released. Only `resume` reuses that run.
`start` refuses an existing directory instead of starting another operation.

The fixed demo order is `order-1`, amount `1900` cents. On approval the output is
`{"result": {"order_id": "order-1", "status": "released"}}`. The `released` table
in `orders.db` contains one row with a unique business idempotency key.

## Enforcement and recovery

- The saved binding covers tenant, customer, exact order, deadline, code revision,
  session, run ID and native pause snapshot. Different identities, modified
  arguments, another requirement or changed stored state stop before permit use.
- Pushary's existing SDK creates an idempotent decision and consumes the remote
  one-use execution permit. Agno's `requirement.confirm()` and `continue_run()`
  run only inside that protected callback.
- The effect step has its own in-process gate. Calling native `confirm()` alone
  cannot release the order. This is an application boundary, not protection
  against a trusted administrator editing the Python code or database.
- The step uses `max_retries=0`. Denial, cancellation, expiry or a missing permit
  does not run it. Refused decisions leave the native run paused; discard or
  reconcile that run through your application's lifecycle.
- A permit is consumed before continuation. A lost permit response, worker crash,
  failed continuation or uncertain business result requires reconciliation. Never
  reset a consumed permit, delete the state directory to retry, or automatically
  start another workflow for the same action.
- Use protected persistent storage. The hash detects accidental modifications;
  it is not a signature against someone who controls storage. SQLite is for this
  single-host demo; use Agno's PostgreSQL backend and your own transactional order
  service for production. Preserve downstream idempotency when adapting the effect.
- Only this single, fixed order step is covered. This example does not intercept
  arbitrary agent tools or apply approval to every action in a larger workflow.

## Check without credentials

```bash
.venv/bin/python check_run.py
```

The checks use real Agno execution and SQLite persistence across separate Python
processes, plus the published Pushary SDK. Only the hosted Pushary HTTP service
is simulated. They cover pending/approved/refused decisions, identity and order
changes, duplicate workers, consumed permits, expiry and direct native-confirm
bypass. They do not claim a live phone or model-provider test.

## References

- [Agno workflow Human-in-the-Loop](https://docs.agno.com/workflows/hitl/overview)
- [Agno cookbook](https://github.com/agno-agi/agno/tree/main/cookbook/04_workflows/08_human_in_the_loop)
- [Pushary Python SDK and support](https://github.com/Pushary/pushary-python)

