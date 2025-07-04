#!/usr/bin/env python3
"""
Script to run all async AWS Bedrock integration tests.

This script runs all async tests for the AWS Bedrock model integration,
including basic functionality, tool usage, and multimodal tests.
"""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import List, Optional
import dotenv

dotenv.load_dotenv()

def setup_logging():
    """Set up logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bedrock_async_tests.log'),
            logging.StreamHandler()
        ]
    )

def check_dependencies() -> bool:
    """Check if required dependencies are installed."""
    required_packages = [
        'aioboto3',
        'exa_py', 
        'yfinance',
        'duckduckgo-search'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"Missing required packages: {', '.join(missing_packages)}")
        print("Installing missing packages...")
        for package in missing_packages:
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", package], 
                              check=True, capture_output=True, text=True)
                print(f"[PASS] Installed {package}")
            except subprocess.CalledProcessError as e:
                print(f"[FAIL] Failed to install {package}: {e}")
                return False
    else:
        print("[PASS] All required packages are installed")
    
    return True

def check_aws_credentials() -> bool:
    """Check if AWS credentials are configured."""
    import os
    
    aws_keys = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_REGION']
    missing_keys = [key for key in aws_keys if not os.getenv(key)]
    
    if missing_keys:
        print(f"[FAIL] Missing AWS credentials: {', '.join(missing_keys)}")
        print("Please set the following environment variables:")
        for key in missing_keys:
            print(f"  - {key}")
        return False
    
    print("[PASS] AWS credentials are configured")
    return True

async def run_test_file(test_file: str) -> bool:
    """Run a specific test file and return success status."""
    print(f"\n=== Running {test_file} ===")
    
    try:
        result = subprocess.run([
            sys.executable, '-m', 'pytest', 
            test_file, 
            '-v', '--tb=short', '--no-header'
        ], capture_output=True, text=True, cwd=Path(__file__).parent)
        
        # Filter out emoji characters for Windows compatibility
        stdout_clean = result.stdout.encode('ascii', 'ignore').decode('ascii')
        stderr_clean = result.stderr.encode('ascii', 'ignore').decode('ascii')
        
        if result.returncode == 0:
            print(f"[PASS] {test_file}")
            print(stdout_clean)
            return True
        else:
            print(f"[FAIL] {test_file}")
            print("STDOUT:", stdout_clean)
            print("STDERR:", stderr_clean)
            return False
            
    except Exception as e:
        print(f"[FAIL] {test_file} - Exception: {e}")
        return False

async def main():
    """Main test runner function."""
    setup_logging()
    
    # Check dependencies and credentials
    if not check_dependencies():
        print("[FAIL] Dependency check failed")
        return 1
    
    if not check_aws_credentials():
        print("[FAIL] AWS credentials check failed")
        return 1
    
    # Run all async tests
    test_files = [
        # 'test_basic.py',
        'test_tool_use.py',
        # 'test_multimodal.py'
    ]
    
    print(f"Running {len(test_files)} test file(s)...")
    
    results = []
    for test_file in test_files:
        result = await run_test_file(test_file)
        results.append((test_file, result))
    
    # Summary
    print("\n=== Test Summary ===")
    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed
    
    for test_file, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} {test_file}")
    
    print(f"\nTotal: {len(results)} files, {passed} passed, {failed} failed")
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 