# Memory Best Practices

As you build memory-enhanced agents, keep these best practices in mind:

1. **Be selective about what goes into working memory**
   - Focus on information that will be relevant across multiple conversations
   - Don't overload working memory with transient details

2. **Use clear instructions**
   - Give your agent explicit guidance on when and how to update working memory
   - Instruct it to check memory before asking for information the user has already provided

3. **Choose appropriate memory parameters**
   - Adjust `lastMessages`, `topK`, and `messageRange` based on your use case
   - More isn't always better - larger context windows can dilute focus

4. **Consider privacy implications**
   - Be transparent with users about what information is being stored
   - Implement appropriate security measures for sensitive information

5. **Test thoroughly**
   - Verify that your agent correctly recalls information across different scenarios
   - Test edge cases like conflicting information or corrections

6. **Design thoughtful templates**
   - Structure your working memory templates based on your agent's specific needs
   - Include clear sections and organization to make information easy to find

7. **Balance memory types**
   - Use conversation history for recent context
   - Use semantic recall for finding relevant past information
   - Use working memory for persistent user details and state

By following these best practices, you can create memory-enhanced agents that provide truly personalized and contextual experiences while avoiding common pitfalls like information overload, privacy concerns, and inconsistent behavior.
