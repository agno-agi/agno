# Support summaries — synthetic audit fixture

SUP-201: Northstar repeated the C-101 CSV export problem. This is the same customer incident, not another independent report. Workaround: split the export at midnight; combine CSV files manually.

SUP-202: Birch requested that CSV exports include the timezone in the generated report header. Today header says "Created at" with no zone. Their finance team cannot distinguish UTC from local time. No implementation is committed.

SUP-203: Juniper independently requested timezone labels on exported reports after spending an hour reconciling UTC and local timestamps. This affects interpretation, not data accuracy.

SUP-204: Reset-password email was delayed in September, but support confirmed the provider fix shipped and all affected customers verified resolution. No new recurrence. Do not reopen solely from this historical mention.
