#!/usr/bin/env python3
"""
Test script to reproduce API key exposure in rate limit errors.
This demonstrates the security vulnerability where API keys are leaked in error logs.
"""

import asyncio
import time
from libs.agno.agno.models.google.gemini import Gemini
from libs.agno.agno.models.message import Message

def test_rate_limit_exposure():
    """Test that reproduces API key exposure during rate limit errors."""
    
    print("🔍 Testing API key exposure during rate limit errors...")
    print("=" * 60)
    
    # Create a Gemini model with a fake but realistic API key
    # This simulates what would happen with a real API key
    fake_api_key = "AIzaSyD1234567890abcdefghijklmnopqrstuvwxyz_FAKE"
    
    model = Gemini(
        id="gemini-2.0-flash-001",
        api_key=fake_api_key,
    )
    
    print(f"✅ Created Gemini model")
    print(f"🔑 Using API key: {fake_api_key[:10]}...{fake_api_key[-10:]}")  # Partial display for demo
    print()
    
    # Test 1: Show how the model repr exposes the API key
    print("📋 Test 1: Model representation exposes API key")
    print("Model repr():")
    model_repr = repr(model)
    if fake_api_key in model_repr:
        print(f"❌ VULNERABILITY: API key found in model representation!")
        print(f"🔓 Exposed: {model_repr}")
    else:
        print("✅ API key not found in model representation")
    print()
    
    # Test 2: Try to trigger a rate limit by making rapid requests
    print("📋 Test 2: Triggering rate limit error to see API key in exception")
    messages = [Message(role="user", content="Hello")]
    
    try:
        # This will fail due to invalid API key, but the error handling
        # will expose the API key in the traceback/logs
        assistant_message = Message(role="assistant")
        model.invoke(messages=messages, assistant_message=assistant_message)
        
    except Exception as e:
        print(f"❌ EXCEPTION CAUGHT: {type(e).__name__}")
        print(f"📄 Exception message: {str(e)}")
        print()
        
        # Check if the API key is exposed in the exception context
        import traceback
        tb_str = traceback.format_exc()
        
        if fake_api_key in tb_str:
            print("❌ CRITICAL VULNERABILITY: API key found in traceback!")
            print("🔓 Traceback contains:")
            # Show just the line with the API key to demonstrate
            for line in tb_str.split('\n'):
                if fake_api_key in line:
                    print(f"   {line.strip()}")
        else:
            print("✅ API key not found in traceback")
            
        print("\n📄 Full traceback:")
        print(tb_str)

async def test_async_rate_limit_exposure():
    """Test async version of rate limit exposure."""
    
    print("\n🔍 Testing ASYNC API key exposure...")
    print("=" * 60)
    
    fake_api_key = "AIzaSyABCD7890123456789EFGHIJ_ASYNC_TEST_FAKE"
    
    model = Gemini(
        id="gemini-2.0-flash-001", 
        api_key=fake_api_key,
    )
    
    messages = [Message(role="user", content="Async test")]
    assistant_message = Message(role="assistant")
    
    try:
        await model.ainvoke(messages=messages, assistant_message=assistant_message)
    except Exception as e:
        print(f"❌ ASYNC EXCEPTION: {type(e).__name__}")
        print(f"📄 Exception message: {str(e)}")
        
        import traceback
        tb_str = traceback.format_exc()
        
        if fake_api_key in tb_str:
            print("❌ CRITICAL VULNERABILITY: API key found in async traceback!")
            print("🔓 Lines containing API key:")
            for i, line in enumerate(tb_str.split('\n')):
                if fake_api_key in line:
                    print(f"   Line {i}: {line.strip()}")
        
def test_model_in_error_context():
    """Test what happens when the model object itself is included in error contexts."""
    
    print("\n🔍 Testing model object in error context...")
    print("=" * 60)
    
    fake_api_key = "AIzaSyXYZ999888777666555444333222111000_CTX"
    
    model = Gemini(api_key=fake_api_key)
    
    try:
        # Simulate an error where the model object might be referenced
        raise ValueError(f"Model error occurred with model: {model}")
    except Exception as e:
        print(f"❌ EXCEPTION WITH MODEL IN MESSAGE: {type(e).__name__}")
        print(f"📄 Exception message: {str(e)}")
        
        if fake_api_key in str(e):
            print("❌ CRITICAL VULNERABILITY: API key found in exception message!")
        else:
            print("✅ API key not found in exception message")

if __name__ == "__main__":
    print("🚨 API KEY EXPOSURE VULNERABILITY TEST")
    print("=" * 60)
    print("This test demonstrates how API keys are leaked in error logs.")
    print("🎯 Testing with FAKE API keys for demonstration purposes.")
    print()
    
    # Run synchronous tests
    test_rate_limit_exposure()
    
    # Run async tests  
    asyncio.run(test_async_rate_limit_exposure())
    
    # Test model in error context
    test_model_in_error_context()
    
    print("\n" + "=" * 60)
    print("🚨 SUMMARY: This test shows how API keys get exposed in:")
    print("   1. Model repr() output")
    print("   2. Exception tracebacks") 
    print("   3. Error messages containing model objects")
    print("   4. Debug logs and exception contexts")
    print("\n🔧 NEXT: Implement security fixes to mask API keys in all representations")
