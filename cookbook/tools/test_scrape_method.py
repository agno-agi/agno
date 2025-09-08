"""
Test script for the new scrape method in ScrapeGraphTools.

This script tests the scrape method functionality to ensure it works correctly.
"""

import json
import os
from dotenv import load_dotenv
from agno.tools.scrapegraph import ScrapeGraphTools

# Load environment variables
load_dotenv()


def test_scrape_method():
    """Test the scrape method with a simple website."""
    
    # Check if API key is available
    api_key = os.getenv("SGAI_API_KEY")
    if not api_key:
        print("❌ SGAI_API_KEY not found in environment variables")
        print("Please set SGAI_API_KEY in your .env file")
        return False
    
    try:
        # Initialize ScrapeGraphTools with scrape method enabled
        scrape_tools = ScrapeGraphTools(scrape=True, smartscraper=False)
        print("✅ ScrapeGraphTools initialized successfully")
        
        # Test URL
        test_url = "https://example.com"
        print(f"Testing scrape method with: {test_url}")
        
        # Call the scrape method
        result = scrape_tools.scrape(website_url=test_url, render_heavy_js=False)
        
        # Parse the result
        result_data = json.loads(result)
        
        # Check if we got HTML content
        html_content = result_data.get("html", "")
        if html_content:
            print("✅ Successfully retrieved HTML content")
            print(f"HTML length: {len(html_content)} characters")
            print(f"Status: {result_data.get('status', 'unknown')}")
            print(f"Request ID: {result_data.get('scrape_request_id', 'N/A')}")
            
            # Check for basic HTML structure
            if "<html" in html_content.lower() and "<body" in html_content.lower():
                print("✅ HTML structure looks correct")
            else:
                print("⚠️  HTML structure may be incomplete")
            
            # Show a preview
            preview = html_content[:200].replace("\n", " ").strip()
            print(f"Preview: {preview}...")
            
            return True
        else:
            print("❌ No HTML content received")
            print(f"Error: {result_data.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with error: {str(e)}")
        return False


def test_scrape_with_js():
    """Test the scrape method with JavaScript rendering."""
    
    try:
        scrape_tools = ScrapeGraphTools(scrape=True, smartscraper=False)
        print("\nTesting scrape method with JavaScript rendering...")
        
        # Test with a simple page that might have JS
        test_url = "https://httpbin.org/html"
        result = scrape_tools.scrape(website_url=test_url, render_heavy_js=True)
        
        result_data = json.loads(result)
        html_content = result_data.get("html", "")
        
        if html_content:
            print("✅ Successfully retrieved HTML content with JS rendering")
            print(f"HTML length: {len(html_content)} characters")
            return True
        else:
            print("❌ No HTML content received with JS rendering")
            return False
            
    except Exception as e:
        print(f"❌ JS rendering test failed: {str(e)}")
        return False


if __name__ == "__main__":
    print("Testing ScrapeGraphTools scrape method")
    print("=" * 50)
    
    # Test basic functionality
    success1 = test_scrape_method()
    
    # Test JavaScript rendering
    success2 = test_scrape_with_js()
    
    print("\n" + "=" * 50)
    if success1 and success2:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
