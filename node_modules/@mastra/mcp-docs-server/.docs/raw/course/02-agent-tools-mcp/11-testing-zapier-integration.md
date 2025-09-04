# Testing the Zapier Integration

Let's test the Zapier integration:

1. Make sure your development server is running with `npm run dev`
2. Open the playground at http://localhost:4111/
3. Try asking your agent to perform tasks that use Zapier, such as:
   - "Get my last email"
   - "Send an email to youremail@gmail.com with the subject 'Test' and body 'Hello, this is a test email'"

If everything is set up correctly, your agent should be able to use the Zapier tools to perform these tasks.

Testing your integration is an important step to ensure that your agent can properly access and use the Zapier tools. When you ask your agent to perform a task that requires Zapier, it should recognize the need to use the appropriate Zapier tool and make the necessary API calls to complete the task.
