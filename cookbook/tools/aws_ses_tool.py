"""
AWS SES (Simple Email Service) Setup Instructions:

1. Create an AWS account if you don't have one
   - Go to https://aws.amazon.com and sign up
   - Add a payment method (required even for free tier)

2. Go to AWS SES Console and verify your domain or email address:
   - For production:
     a. Go to AWS SES Console > Verified Identities > Create Identity
     b. Choose "Domain" and follow DNS verification steps
     c. Add DKIM and SPF records to your domain's DNS
   - For testing:
     a. Choose "Email Address" verification
     b. Click verification link sent to your email

3. Check SES Sending Limits:
   - New accounts start in sandbox mode with limits:
     * 200 emails per 24-hour period
     * 1 email per second
   - To increase limits:
     a. Go to SES Console > Account Dashboard
     b. Click "Request Production Access"
     c. Fill out the form with your use case

4. Configure AWS Credentials:
   a. Create an IAM user:
      - Go to IAM Console > Users > Add User
      - Enable "Programmatic access"
      - Attach 'AmazonSESFullAccess' policy

   b. Set up credentials (choose one method):
      Method 1 - Using AWS CLI:
      ```
      aws configure
      # Enter your AWS Access Key ID
      # Enter your AWS Secret Access Key
      # Enter your default region
      ```

      Method 2 - Manual credentials file:
      Create ~/.aws/credentials with:
      ```
      [default]
      aws_access_key_id = YOUR_ACCESS_KEY
      aws_secret_access_key = YOUR_SECRET_KEY
      ```

      Method 3 - Environment variables:
      ```
      export AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
      export AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
      ```

5. Configure OpenAI API:
   a. Get your API key from https://platform.openai.com/api-keys
   b. Set the environment variable:
      ```
      export OPENAI_API_KEY=your_openai_api_key
      ```

6. Install required Python packages:
   ```
   pip install boto3 agno
   ```

7. Update the variables below with your configuration:
   - sender_email: Your verified sender email address
   - sender_name: Display name that appears in email clients
   - region_name: AWS region where SES is set up (e.g., 'us-east-1', 'ap-south-1')

Troubleshooting:
- If emails aren't sending, check:
  * Both sender and recipient are verified (in sandbox mode)
  * AWS credentials are correctly configured
  * You're within sending limits
  * Your IAM user has correct SES permissions
- Check CloudWatch for delivery metrics and errors
- Use SES Console's 'Send Test Email' feature to verify setup
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.aws_ses import AWSSESTool
from agno.tools.duckduckgo import DuckDuckGoTools

# Configure email settings
sender_email = "<sender_email>"  # Your verified SES email
sender_name = "AI Research Updates"
region_name = "ap-south-1"  # Your AWS region

# Create an agent that can research and send personalized email updates
agent = Agent(
    name="Research Newsletter Agent",
    model=OpenAIChat(id="gpt-4o"),
    description="""You are an AI research specialist who creates and sends personalized email 
    newsletters about the latest developments in artificial intelligence and technology.""",
    instructions=[
        "When given a prompt:",
        "1. Extract the recipient's email from the natural language prompt",
        "2. Research the latest AI developments using DuckDuckGo",
        "3. Compose a concise, engaging email with:",
        "   - A compelling subject line",
        "   - 3-4 key developments or news items",
        "   - Brief explanations of why they matter",
        "   - Links to sources",
        "4. Format the content in a clean, readable way",
        "5. Send the email using AWS SES to the extracted recipient",
    ],
    tools=[
        AWSSESTool(
            sender_email=sender_email, sender_name=sender_name, region_name=region_name
        ),
        DuckDuckGoTools(),
    ],
    markdown=True,
    show_tool_calls=True,
)

if __name__ == "__main__":
    # Example prompts showing different ways to specify recipients and content
    prompts = [
        """Research AI developments in healthcare from the past week and email a summary 
        to health-team@company.com. Focus on practical applications in clinical settings.""",
        """Send jane@research.org a detailed update about recent breakthroughs in 
        quantum computing and their potential impact on AI.""",
        """Compile a weekly digest of AI safety developments and send it to 
        safety-team@company.com. Include both technical and policy updates.""",
        """Find the latest news about AI in autonomous vehicles and email the findings 
        to autonomous@mobility.org. Highlight real-world deployments and testing.""",
        """Research MLOps tools released in the last month and send a technical summary 
        to devops@tech.com. Include setup instructions and GitHub links.""",
    ]

    # Choose one prompt to run
    agent.print_response(prompts[0])

"""
The agent will now handle recipient emails as part of natural language prompts.
This allows for more flexible and context-aware email sending. For example:

- "Send weekly AI updates to team@company.com"
- "Research LLM developments and email findings to alice@research.org"
- "Compile AI safety news and send it to safety-team@org.com"
- "Find AI startup news and email a summary to vc@investor.com"
- "Get latest AI paper summaries and send them to researcher@university.edu"
"""
