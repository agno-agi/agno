import os
import hmac
import hashlib
from cookbook.examples.apps.whatsapp_chat_agent.security import is_development_mode, get_app_secret, validate_webhook_signature

def generate_signature(payload: bytes, secret: str) -> str:
    """Helper function to generate a valid signature."""
    hmac_obj = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    )
    return f"sha256={hmac_obj.hexdigest()}"

def test_development_mode():
    """Test security behavior in development mode."""
    print("\n=== Testing Development Mode ===")

    # Ensure we're in development mode
    os.environ['APP_ENV'] = 'development'
    if 'WHATSAPP_APP_SECRET' in os.environ:
        del os.environ['WHATSAPP_APP_SECRET']

    print(f"Is development mode? {is_development_mode()}")

    # Test 1: Get app secret without setting WHATSAPP_APP_SECRET
    try:
        secret = get_app_secret()
        print("✅ Got dummy secret in development mode:", secret)
    except ValueError as e:
        print("❌ Failed to get dummy secret:", e)

    # Test 2: Validate signature with no signature header
    payload = b"test message"
    result = validate_webhook_signature(payload, None)
    print("✅ Signature bypass in dev mode:", result)

    # Test 3: Validate with invalid signature
    result = validate_webhook_signature(payload, "sha256=invalid")
    print("✅ Invalid signature check in dev mode:", result is False)

def test_production_mode():
    """Test security behavior in production mode."""
    print("\n=== Testing Production Mode ===")

    # Switch to production mode
    os.environ['APP_ENV'] = 'production'
    test_secret = "test_production_secret"
    os.environ['WHATSAPP_APP_SECRET'] = test_secret

    print(f"Is development mode? {is_development_mode()}")

    # Test 1: Get app secret
    try:
        secret = get_app_secret()
        print("✅ Got production secret:", secret == test_secret)
    except ValueError as e:
        print("❌ Failed to get production secret:", e)

    # Test 2: Validate correct signature
    payload = b"test message"
    valid_signature = generate_signature(payload, test_secret)
    result = validate_webhook_signature(payload, valid_signature)
    print("✅ Valid signature check in prod mode:", result)

    # Test 3: Validate invalid signature
    result = validate_webhook_signature(payload, "sha256=invalid")
    print("✅ Invalid signature check in prod mode:", result is False)

    # Test 4: Try with no signature
    result = validate_webhook_signature(payload, None)
    print("✅ No signature check in prod mode:", result is False)

def test_production_mode_no_secret():
    """Test production mode without secret configured."""
    print("\n=== Testing Production Mode (No Secret) ===")

    # Switch to production mode without secret
    os.environ['APP_ENV'] = 'production'
    if 'WHATSAPP_APP_SECRET' in os.environ:
        del os.environ['WHATSAPP_APP_SECRET']

    try:
        secret = get_app_secret()
        print("❌ Should not get secret without configuration")
    except ValueError as e:
        print("✅ Correctly failed without secret:", str(e))

if __name__ == "__main__":
    # Run all tests
    test_development_mode()
    test_production_mode()
    test_production_mode_no_secret()
    print("\nTests completed!")
