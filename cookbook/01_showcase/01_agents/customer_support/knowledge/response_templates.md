# Response Templates and Empathy Guidelines

## Opening Statements by Sentiment

### For Calm Customers
```
Thank you for reaching out to Agno support! I'd be happy to help you with this.
```
```
Thanks for contacting us! Let me look into this for you.
```

### For Frustrated Customers
```
I understand how frustrating this must be, and I truly appreciate your patience. Let me help you resolve this right away.
```
```
I can see how this issue would be frustrating, especially when you're trying to get work done. I'm committed to finding a solution for you.
```
```
I'm sorry you've had to deal with this. That should never have happened, and I completely understand how frustrating this must be for you.
```

### For Urgent Customers
```
I understand this is urgent and I'm prioritizing your issue right now. Let me look into this immediately.
```
```
I can see this is impacting your work, and I'm treating this as a top priority. Here's what I'm doing to help you right now.
```

## Empathy Statements

### Acknowledging the Issue
- "I can see how that would be incredibly frustrating."
- "If I were in your position, I'd feel the same way."
- "I appreciate you bringing this to our attention."
- "Thank you for your patience while we work through this."

### For Technical Issues
- "I understand how frustrating technical issues are, especially when you have important tasks to complete."
- "I can imagine how disruptive this must be to your workflow."
- "This issue is impacting your ability to work, and I want to resolve it as quickly as possible."

### For Repeated Issues
- "I see this isn't the first time you've experienced this, and I understand how frustrating that must be."
- "I'm looking at your history and I can see you've been dealing with this for a while. Let's get this resolved once and for all."
- "I apologize that this is still happening. I'm going to make sure we find a permanent solution."

### Avoid These Phrases
- "I understand" (without specifics - feels dismissive)
- "That's not possible" (find alternatives instead)
- "You should have..." (never blame the customer)
- "Our policy says..." (lead with solutions, not restrictions)

## Response Structure

### For Questions (How-to)

```
[Opening based on sentiment]

[Direct answer to the question]

Here's how to [accomplish the task]:
1. [Step 1]
2. [Step 2]
3. [Step 3]

[Additional context or tips if helpful]

[Closing - offer further help]
```

### For Bug Reports

```
[Empathetic opening - acknowledge the frustration]

Thank you for the detailed report. I've been able to reproduce this issue.

[Explain what's happening and why, if known]

[Immediate workaround if available]

I'm escalating this to our engineering team with priority [level]. You can expect [timeline for fix/update].

[Offer to keep them updated]
```

### For Feature Requests

```
Thank you for sharing this suggestion! I can see how [feature] would be valuable for [use case].

I've logged this as a feature request with our product team. While I can't promise a specific timeline, your feedback directly influences our roadmap.

[If similar feature exists] In the meantime, you might find [alternative] helpful for accomplishing something similar.

Is there anything else I can help you with?
```

### For Account/Billing Issues

```
[Opening - extra care with financial matters]

I understand how important it is to get [billing/access] issues resolved quickly.

[Explain what you can see and verify]

[Clear next steps and timeline]

[If need more info] To help you further, I'll need to verify [information] for security purposes.

[Reassure about resolution]
```

## Closing Statements

### When Resolved
```
I'm glad we could get this sorted out! Is there anything else I can help you with today?
```
```
Great, it looks like everything is working now. Don't hesitate to reach out if you have any other questions.
```

### When Pending Customer Response
```
Please let me know if this resolves your issue, or if you need any clarification on the steps above.
```
```
I'll keep this ticket open while you try these steps. Just reply here if you run into any issues.
```

### When Escalated
```
I've escalated this to our [team] who will reach out within [timeframe]. You'll receive updates on this ticket as we make progress.
```

### When Cannot Resolve
```
I'm sorry I wasn't able to fully resolve this today. I've documented everything and escalated to [team/person] who has the expertise to help.

You'll hear back within [timeframe]. In the meantime, if you discover any additional information, please add it to this ticket.
```

## Common Issue Responses

### API Key Not Set
```
It looks like the API key might not be configured correctly. Here's how to fix this:

1. Get your API key from [dashboard/settings location]
2. Set it as an environment variable:
   ```
   export OPENAI_API_KEY=your-key-here
   ```
3. Restart your application

If you're using a .env file, make sure the variable is loaded before your application starts.
```

### Database Connection Error
```
This error typically means the database isn't running or accessible. Let's troubleshoot:

1. Verify PostgreSQL is running:
   ```
   ./cookbook/scripts/run_pgvector.sh
   ```
2. Check the connection string in your configuration
3. Ensure the port (default: 5532) isn't blocked

If you're using Docker, make sure the container is running with `docker ps`.
```

### Installation Issues
```
Let's make sure everything is set up correctly:

1. Verify Python version (3.9+ required):
   ```
   python --version
   ```
2. Install or update Agno:
   ```
   pip install -U agno
   ```
3. Install any additional dependencies for your use case

What error message are you seeing during installation?
```

## Sources

Based on best practices from:
- [HubSpot - Empathy Phrases](https://blog.hubspot.com/service/empathy-phrases-customer-service)
- [TextExpander - Empathy Statements](https://textexpander.com/blog/30-phrases-to-show-empathy-in-customer-service)
- [AnswerConnect - Empathy Statements](https://www.answerconnect.com/blog/business-tips/empathy-statements-customer-service/)
