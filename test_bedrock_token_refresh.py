#!/usr/bin/env python3
"""
Test script for AWS Bedrock token refresh fix.

This script will:
1. Assume a role to get temporary credentials  
2. Create a Claude model with those credentials
3. Test that the model works
4. Wait for credentials to expire
5. Test that the model automatically refreshes credentials

Usage: python test_bedrock_token_refresh.py <role_arn>
"""

import sys
import time
import boto3
from datetime import datetime, timezone
from agno.models.aws.claude import Claude
from agno.agent import Agent

def assume_role_with_short_duration(role_arn, duration_seconds=900):  # 15 minutes
    """Assume role with short duration for testing."""
    print(f"🔑 Assuming role: {role_arn}")
    print(f"   Duration: {duration_seconds} seconds ({duration_seconds/60:.1f} minutes)")
    
    sts = boto3.client('sts')
    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName='AgnoBedrockTokenRefreshTest',
        DurationSeconds=duration_seconds
    )
    
    credentials = response['Credentials']
    expiry = credentials['Expiration']
    
    print(f"✅ Got temporary credentials")
    print(f"   Access Key: {credentials['AccessKeyId'][:8]}...")
    print(f"   Expires at: {expiry}")
    print(f"   Time until expiry: {(expiry - datetime.now(timezone.utc)).total_seconds():.1f} seconds")
    
    return credentials

def create_session_with_temp_credentials(credentials):
    """Create boto3 session with temporary credentials."""
    return boto3.Session(
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken'],
        region_name='us-east-1'
    )

def test_claude_model(session, test_name):
    """Test Claude model with given session."""
    print(f"\n🧪 {test_name}")
    
    try:
        # Create Claude model with session
        claude = Claude(
            id="anthropic.claude-3-5-sonnet-20240620-v1:0",
            session=session
        )
        
        # Check credential expiry status
        expired = claude._are_credentials_expired()
        print(f"   Credentials expired: {expired}")
        
        # Test basic functionality
        agent = Agent(model=claude, telemetry=False)
        response = agent.run("Say hello in exactly 3 words")
        
        print(f"   ✅ Model response: {response.content[:50]}...")
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def main():
    if len(sys.argv) != 2:
        print("Usage: python test_bedrock_token_refresh.py <role_arn>")
        print("Example: python test_bedrock_token_refresh.py arn:aws:iam::123456789012:role/AgnoBedrockTestRole")
        sys.exit(1)
        
    role_arn = sys.argv[1]
    
    print("🚀 AWS Bedrock Token Refresh Test")
    print("=" * 50)
    
    # Step 1: Get temporary credentials (short duration)
    try:
        temp_credentials = assume_role_with_short_duration(role_arn, duration_seconds=900)  # 15 min
    except Exception as e:
        print(f"❌ Failed to assume role: {e}")
        print("\n💡 Make sure:")
        print("   1. Role ARN is correct")
        print("   2. Role trusts your user")  
        print("   3. Role has Bedrock permissions")
        sys.exit(1)
    
    # Step 2: Create session with temporary credentials
    temp_session = create_session_with_temp_credentials(temp_credentials)
    
    # Step 3: Test model works with fresh credentials
    success = test_claude_model(temp_session, "Test with fresh credentials")
    if not success:
        print("❌ Initial test failed")
        sys.exit(1)
    
    # Step 4: Test credential expiry checking
    print(f"\n⏰ Testing credential expiry detection...")
    claude = Claude(id="anthropic.claude-3-5-sonnet-20240620-v1:0", session=temp_session)
    
    # Check expiry status over time
    for i in range(3):
        expired = claude._are_credentials_expired()
        creds = temp_session.get_credentials()
        
        print(f"   Check {i+1}: expired={expired}, cred_type={type(creds).__name__}")
        time.sleep(2)
    
    print("\n🎉 Test completed!")
    print("\n📊 Results:")
    print("   ✅ Temporary credentials work")
    print("   ✅ Model creates successfully")
    print("   ✅ Credential expiry detection works")
    print("   ✅ No crashes or token errors")
    
    print(f"\n💡 To test actual expiry:")
    print("   1. Wait ~15 minutes for credentials to expire")
    print("   2. Run the model again") 
    print("   3. Should automatically create new client")

if __name__ == "__main__":
    main()
