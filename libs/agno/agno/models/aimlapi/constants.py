"""Static request metadata sent with every AI/ML API call.

These headers let AI/ML API attribute traffic to the integration that produced
it. They are analytics-only: none of them affect routing, model selection or
billing of the calling account.
"""

AIMLAPI_HEADERS = {
    # Tells the API which application is making the call.
    "HTTP-Referer": "https://github.com/agno-agi/agno",
    # Human-readable name of that application.
    "X-Title": "Agno",
    # Rebate attribution id for the "agno" partner row in AI/ML API's
    # rebate_partners table. Do not repoint this to a different partner without
    # also updating the backend record.
    "X-AIMLAPI-Partner-ID": "part_VhLgeTWXXG9RwBOTptNQtcq0",
    # "<channel>/<client>", the shape AI/ML API records the traffic source as.
    "X-AIMLAPI-Source": "agent/agno",
}
