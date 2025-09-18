"""
AWS SES (Simple Email Service) Setup Instructions:

1. Go to AWS SES Console and verify your domain or email address:
   - For production:
     a. Go to AWS SES Console > Verified Identities > Create Identity
     b. Choose "Domain" and follow DNS verification steps
     c. Add DKIM and SPF records to your domain's DNS
   - For testing:
     a. Choose "Email Address" verification
     b. Click verification link sent to your email

2. Configure AWS Credentials:
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

      Method 2 - Set environment variables:
      ```
      export AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
      export AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
      ```

3. Install required Python packages:
   ```
   pip install boto3 agno
   ```

4. Update the variables below with your configuration:
   - sender_email: Your verified sender email address
   - sender_name: Display name that appears in email clients
   - region_name: AWS region where SES is set up (e.g., 'us-east-1', 'ap-south-1')

"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.aws_ses import AWSSESTool
from agno.tools.duckduckgo import DuckDuckGoTools

# Configure email settings
sender_email = "coolmusta@gmail.com"  # Your verified SES email
sender_name = "AI Research Updates"
region_name = "us-west-2"  # Your AWS region

# Create an agent that can research and send personalized email updates
agent = Agent(
    name="Research Newsletter Agent",
    model=OpenAIChat(id="gpt-4o"),
    description="""You are an AI research specialist who creates and sends personalized email 
    newsletters about the latest developments in artificial intelligence and technology.""",
    instructions=[
        "When given a prompt:",
        "1. Extract the recipient's email address carefully. Look for the complete email in format 'user@domain.com'.",
        "2. Research the latest AI developments using DuckDuckGo",
        "3. Compose a concise, engaging email with:",
        "   - A compelling subject line",
        "   - 3-4 key developments or news items",
        "   - Brief explanations of why they matter",
        "   - Links to sources",
        "4. Format the content in a clean, readable way",
        "5. Send the email using AWS SES. IMPORTANT: The receiver_email parameter must be the COMPLETE email address including the @ symbol and domain (e.g., if the user says 'send to mustafa@agno.com', you must use receiver_email='mustafa@agno.com', NOT 'mustafacom' or any other variation).",
    ],
    tools=[
        AWSSESTool(
            sender_email=sender_email, sender_name=sender_name, region_name=region_name
        ),
        DuckDuckGoTools(),
    ],
    markdown=True,
)

# Example 1: Send an email
agent.print_response(
    "Research AI developments in healthcare from the past week with a focus on practical applications in clinical settings. Send the summary via email to mustafa@agno.com"
)

"""
Troubleshooting:
- If emails aren't sending, check:
  * Both sender and recipient are verified (in sandbox mode)
  * AWS credentials are correctly configured
  * You're within sending limits
  * Your IAM user has correct SES permissions
- Use SES Console's 'Send Test Email' feature to verify setup
"""
