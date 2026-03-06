# Common Search Patterns

## Finding Policies and Handbooks

**Best approach:**
1. Start with S3 `company-docs/policies/`
2. Search for the policy name or related terms
3. Read the full document, not just snippets

**Known locations:**
- Employee Handbook: `s3://company-docs/policies/employee-handbook.md`
- PTO Policy: In the Employee Handbook, Section 4
- Data Retention: `s3://company-docs/policies/data-retention.md`
- Security Policy: `s3://company-docs/policies/security-policy.md`

**Gotcha:** PTO info is in the Employee Handbook, not a standalone doc.

---

## Finding Runbooks and Procedures

**Best approach:**
1. Start with S3 `engineering-docs/runbooks/`
2. Search for the procedure name
3. Read the full runbook

**Known locations:**
- Deployment: `s3://engineering-docs/runbooks/deployment.md`
- Incident Response: `s3://engineering-docs/runbooks/incident-response.md`
- On-Call Guide: `s3://engineering-docs/runbooks/oncall-guide.md`

---

## Finding OKRs and Planning Docs

**Best approach:**
1. Start with S3 `company-docs/planning/`
2. Search for the quarter (Q1, Q2, Q3, Q4) and year
3. Read the full OKR document

**Known locations:**
- Q4 2024 OKRs: `s3://company-docs/planning/q4-2024-okrs.md`
- Company Strategy: `s3://company-docs/planning/2024-strategy.md`

---

## Finding Technical Documentation

**Best approach:**
1. Start with S3 `engineering-docs/architecture/`
2. For RFCs, check `engineering-docs/rfcs/`
3. For wikis, fallback to Notion

**Known locations:**
- System Overview: `s3://engineering-docs/architecture/system-overview.md`
- API Design: `s3://engineering-docs/architecture/api-design.md`
- RFCs: `s3://engineering-docs/rfcs/`

---

## Finding Recent Decisions

**Best approach:**
1. Start with Slack - search relevant channels
2. Look for threads with many replies
3. Cross-reference with documented decisions

**Typical locations:**
- Slack: #product-decisions, #engineering, #leadership
- Notion: Decision Log or Meeting Notes

---

## Finding Who Knows Something

**Best approach:**
1. Start with Slack - find recent discussions
2. Note who participated actively
3. Check Notion for page owners

---

## Multi-Source Search Strategy

When information might be anywhere:

1. **Identify the information type**
   - Policies/formal docs → S3
   - Discussions/decisions → Slack
   - Living docs/wikis → Notion
   - Spreadsheets → Google Drive

2. **Search primary source first**

3. **Note timestamps** — Newer info may supersede older

4. **Cross-reference** — Important decisions often exist in multiple places

5. **Save what you learn** — If the location was surprising, save it

---

## Handling "Not Found" Results

If search returns nothing:

1. **Try synonyms** — "PTO" vs "vacation" vs "time off"
2. **Broaden the search** — Remove specific terms
3. **Check other sources** — Info might be in a different system
4. **Check parent documents** — Info might be in a section of a larger doc
5. **Ask for clarification** — User might know the exact location
