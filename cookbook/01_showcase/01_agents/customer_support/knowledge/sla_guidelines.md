# SLA Guidelines

## Response Time Targets

| Priority | First Response | Resolution Target | Business Hours |
|----------|----------------|-------------------|----------------|
| P1 - Critical | 15 minutes | 4 hours | 24/7 |
| P2 - High | 1 hour | 8 hours | 24/7 |
| P3 - Medium | 4 hours | 24 hours | Business hours |
| P4 - Low | 1 business day | 3 business days | Business hours |

## Priority Definitions

### P1 - Critical
- Production environment completely down
- Security breach or data exposure
- Complete loss of core functionality
- Affects all users or customers

**Examples:**
- "Our entire platform is down"
- "We're seeing a security vulnerability"
- "All API calls are failing"

### P2 - High
- Major feature not working
- Significant impact on business operations
- No workaround available
- Affects multiple users

**Examples:**
- "Can't create new agents"
- "Knowledge search returns no results"
- "Database connection failing intermittently"

### P3 - Medium
- Feature partially working
- Limited impact on operations
- Workaround available
- Affects single user or small group

**Examples:**
- "Export to PDF not formatting correctly"
- "Slow response times on certain queries"
- "Minor UI display issue"

### P4 - Low
- General questions or inquiries
- Feature requests
- Documentation improvements
- Nice-to-have enhancements

**Examples:**
- "How do I configure X?"
- "Can you add support for Y?"
- "Documentation unclear on Z"

## SLA Compliance Rules

### What Counts as First Response
- Meaningful acknowledgment of the issue
- NOT auto-responders or ticket confirmations
- Must demonstrate understanding of the problem
- Should set expectations for next steps

### What Counts as Resolution
- Customer confirms issue is resolved
- Solution provided and verified working
- Workaround accepted by customer
- Issue determined to be working as designed (with explanation)

### SLA Clock Behavior
- **Starts:** When ticket is created
- **Pauses:** When waiting for customer response
- **Resumes:** When customer responds
- **Stops:** When ticket is resolved

### Business Hours
- Monday - Friday: 9:00 AM - 6:00 PM (local time)
- Excludes: Weekends and company holidays
- P1/P2: 24/7 coverage (on-call rotation)

## Breach Prevention

### Warning Thresholds
- **Yellow Alert:** 75% of SLA time elapsed
- **Red Alert:** 90% of SLA time elapsed
- **Breach:** 100% - requires immediate escalation

### Actions at Warning Levels

**Yellow Alert (75%):**
- Review ticket status
- Check if additional information needed
- Consider priority upgrade if warranted
- Notify team lead

**Red Alert (90%):**
- Immediate escalation to Tier 2
- Notify supervisor
- Customer communication about status
- All hands on deck

### Post-Breach Protocol
1. Resolve immediately - all other work pauses
2. Apologize to customer with explanation
3. Document root cause
4. Update internal process if needed
5. Report in weekly SLA review

## Customer Tier Considerations

### Enterprise Customers
- May have custom SLA terms
- Check account notes for specific agreements
- Priority boost for same issue type
- Dedicated account manager involvement

### Standard Customers
- Follow standard SLA matrix above
- Equal treatment within priority levels
- No custom exceptions without approval

### Trial/Free Users
- Best-effort response
- P4 priority maximum unless critical bug
- May redirect to community resources

## Metrics and Reporting

### Key Metrics
- **SLA Compliance Rate:** Target > 95%
- **Average First Response Time:** Track by priority
- **Average Resolution Time:** Track by priority
- **Breach Count:** Target zero

### Weekly Review
- Total tickets by priority
- SLA compliance percentage
- Breaches and root causes
- Trends and patterns

## Sources

Based on best practices from:
- [Freshworks - SLA Response Time](https://www.freshworks.com/itsm/sla/response-time/)
- [TimeToReply - Customer Service SLAs](https://timetoreply.com/blog/customer-service-sla/)
- [Zendesk - SLA Targets](https://support.zendesk.com/hc/en-us/articles/4408845755546-Workflow-How-to-automatically-set-priority-on-tickets-for-SLA-targets)
