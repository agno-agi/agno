"""Static request metadata sent with every AI/ML API call.

These headers let AI/ML API attribute traffic to the integration that produced
it. They are analytics-only: none of them affect routing, model selection or
billing of the calling account.
"""

# Identifies the framework making the call, for analytics and debugging.
AIMLAPI_HEADERS = {
    # Tells the API which application is making the call
    "HTTP-Referer": "https://github.com/agno-agi/agno",
    # Identifies the client or library name for tracking
    "X-Title": "Agno",
    # Rebate attribution id (part_...) for the "agno" partner row in AI/ML API's
    # rebate_partners table. Do not repoint this to a different partner without
    # also updating the backend record.
    # TODO(aimlapi): placeholder: swap for the real part_... id once the "agno"
    # rebate_partners row is provisioned.
    "X-AIMLAPI-Partner-ID": "part_PLACEHOLDER_AGNO",
    "X-AIMLAPI-Source": "agent/agno",
}
