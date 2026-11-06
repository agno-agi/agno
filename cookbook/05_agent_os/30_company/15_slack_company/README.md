# CompanyOS in Slack

`slack_company.py` connects the existing Super Agent, Company Manager, durable PostgreSQL queue and scheduler to signed Slack events. Normal Task acceptance, revision and completion are automatic within the mapped user's existing permissions. Tool confirmation and input requirements still pause execution.

Set `DATABASE_URL`, `JWT_SECRET`, `OPENAI_API_KEY`, `SLACK_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_WORKSPACE_ID`, `SLACK_APP_ID`, `SLACK_BOT_USER_ID`, `SLACK_CHANNEL_IDS` (comma-separated), `SLACK_PLATFORM_USERS` (JSON such as `{"U123":"alice"}`), and `COMPANY_UI_URL` (the configured OS's Company page). Run from this directory with the development environment. This configured-provider example is not an offline test; sending requests can call OpenAI and post to Slack.

Configure the existing Slack app's event URL `/slack/events` and interaction URL `/slack/interactions`. Enable mentions and channel message events, with `app_mentions:read`, `chat:write`, and the relevant channel history scope. Streaming also requires `assistant:write`. See the Slack cookbook for app setup.

Mention the bot with a delegated outcome, then ask for status or an unrelated answer in the same thread while its worker runs. Each participant has a separate platform-owned conversation. An explicit `cancel <task-id>` cancels the current execution and withdraws the Task; the success reply follows its persisted cancelled state. Links use the existing Company Task panel, including detailed results and artifact references.

The allowed channels are shared disclosure destinations: replies can be read by channel members. Configure only channels appropriate for these users and Company data. User mappings do not confer platform grants. Every action and delayed delivery rechecks current permissions and disabled-user state; mappings, installation and Company database scope fence receipts. Do not map several Slack users to the same principal when they require separate authority.

Receipt and notification intents persist in PostgreSQL. The existing scheduler poller retries delivery independently of the Company's automation cron. A provider outage does not rerun a completed model or Task. Lost provider acknowledgements can produce a duplicate reply (at-least-once delivery); stable run identities prevent duplicate execution. Receipt records are currently retained without automatic pruning to preserve duplicate fences. Streaming reuses the existing Slack stream transport for final generated output; durable token-by-token replay is not provided.

Offline integration tests use signed requests through the actual API, PostgreSQL queue, manager delegation and artifact assessment. They exercise one automatic revision, continued conversation, restart, outages, revoked/disabled access and cancellation. No live Slack workspace or paid model is used in those tests.


SlackCompany requires `user_isolation=True`; startup refuses configurations that cannot retain each participant's session ownership. Agent and Team worker tool confirmations and user-input requests can be resolved in the originating Slack thread. Workflow step approvals and administrative approvals retain their AgentOS resolution path. If an executor is moved to another database while paused, restore its original database before continuing the Task.
