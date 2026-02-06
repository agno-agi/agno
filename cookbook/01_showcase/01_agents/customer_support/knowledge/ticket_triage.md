# Ticket Triage Best Practices

## What is Ticket Triage?

Ticket triage is the process of categorizing, prioritizing, and routing customer support tickets to ensure efficient resolution. It helps support teams manage high volumes by addressing urgent matters first.

## Priority Classification

### P1 - Critical (Urgent)
- **Response Time:** 15 minutes
- **Resolution Target:** 4 hours
- **Triggers:** Production down, security incidents, data loss, complete service outage
- **Indicators:** "ASAP", "critical", "blocking", "production down", "urgent", "emergency"
- **Action:** Immediate escalation to Tier 2/3, notify on-call engineer

### P2 - High
- **Response Time:** 1 hour
- **Resolution Target:** 8 hours
- **Triggers:** Major feature broken, significant impact on workflow, multiple users affected
- **Indicators:** "not working", "broken", "error", "can't access", "blocking my work"
- **Action:** Prioritize in queue, assign to experienced agent

### P3 - Medium (Normal)
- **Response Time:** 4 hours
- **Resolution Target:** 24 hours
- **Triggers:** Limited scope issues, single user affected, workaround available
- **Indicators:** "issue with", "having trouble", "doesn't seem to work"
- **Action:** Standard queue processing

### P4 - Low
- **Response Time:** 1 business day
- **Resolution Target:** 3 business days
- **Triggers:** Minor questions, feature requests, documentation inquiries
- **Indicators:** "How do I...", "Can I...", "Would be nice if...", "suggestion"
- **Action:** Queue for batch processing

## Ticket Classification Categories

### Question
- How-to inquiries about using the product
- Documentation clarification requests
- Best practice guidance
- Keywords: "how do I", "what is", "can I", "where do I find"

### Bug Report
- Something not working as expected
- Error messages or crashes
- Unexpected behavior
- Keywords: "error", "not working", "broken", "fails", "crash", "exception"

### Feature Request
- New functionality suggestions
- Enhancement ideas
- Integration requests
- Keywords: "can you add", "would be nice", "suggestion", "request", "wish"

### Account/Billing
- Login issues, access problems
- Subscription questions
- Payment inquiries
- Keywords: "billing", "access", "login", "subscription", "payment", "invoice"

## Sentiment Detection

### Calm
- Neutral tone, polite language
- No urgency indicators
- Standard greeting and sign-off
- Action: Standard response, maintain professional tone

### Frustrated
- Repeated issues mentioned ("still", "again", "multiple times")
- Expressions of disappointment
- History of previous contacts
- Action: Acknowledge frustration, prioritize resolution, consider supervisor involvement

### Urgent
- Time-sensitive language ("ASAP", "immediately", "deadline")
- Business impact mentioned
- Escalation threats
- Action: Immediate attention, expedite resolution, keep customer updated frequently

## Triage Workflow

1. **Read ticket thoroughly** - Understand the full context before categorizing
2. **Identify keywords** - Look for priority and category indicators
3. **Check customer history** - Review past tickets for patterns
4. **Assign priority** - Use the classification matrix above
5. **Route appropriately** - Direct to correct team/tier
6. **Set expectations** - Inform customer of timeline
7. **Document** - Add internal notes for next agent

## Key Metrics to Monitor

- **Time to First Response** - Should match SLA targets
- **SLA Breach Rate** - Target less than 5%
- **Reassignment Rate** - Indicates triage accuracy
- **First Contact Resolution** - Higher is better

## Sources

Based on best practices from:
- [ChatBees - Ticket Triage Strategies](https://www.chatbees.ai/blog/ticket-triage)
- [Wrangle - Ticket Triage Best Practices](https://www.wrangle.io/post/ticket-triage)
- [Kommunicate - Support Ticket Triage](https://www.kommunicate.io/blog/support-ticket-triage/)
