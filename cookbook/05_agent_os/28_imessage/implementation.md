# iMessage interface implementation

## Contract

BlueBubbles on a Mac forwards `new-message` events to AgentOS. An authenticated,
allowlisted direct iMessage invokes one reusable Agent, Team, or Workflow and
sends its final text back through BlueBubbles' AppleScript send endpoint.

This first version follows the existing AgentOS webhook interfaces.

## Implemented, not runtime-verified

- [x] Importable `IMessage` interface with explicit or environment configuration.
- [x] Required shared webhook token, separate from the BlueBubbles password.
- [x] Direct-message text filtering, sender allowlist, and echo suppression.
- [x] Stable sender identity and isolated persistent conversation sessions.
- [x] Background processing, serialized runs, and bounded in-memory deduplication.
- [x] Async and offloaded synchronous entity execution.
- [x] Text replies through `POST /api/v1/message/text`.
- [x] Cookbook and setup/operating-limit documentation.

## Pending authorization to verify

- [ ] Add and run focused interface tests.
- [x] Run formatting.
- [ ] Complete static validation.
- [ ] Run the cookbook with BlueBubbles and verify a real iMessage round trip.

## Follow-up scope

Durable delivery tracking/retries, multiple workers, group-chat policy, media,
streaming, and interactive approvals are outside this first implementation.
