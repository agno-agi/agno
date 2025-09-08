#!/usr/bin/env python3
"""
Test runner for ScrapeGraphTools scrape method tests.

This script runs all tests related to the ScrapeGraphTools scrape functionality.
"""

import subprocess
import sys
from pathlib import Path


def run_tests():
    """Run all ScrapeGraphTools tests."""
    # Get the project root directory
    project_root = Path(__file__).parent.parent.parent.parent
    
    # Define test files
    test_files = [
        "libs/agno/tests/unit/tools/test_scrapegraph.py",
        "libs/agno/tests/unit/tools/test_scrapegraph_error_handling.py",
        "libs/agno/tests/integration/tools/test_scrapegraph_integration.py",
    ]
    
    # Run pytest for each test file
    results = []
    for test_file in test_files:
        test_path = project_root / test_file
        if test_path.exists():
            print(f"\n{'='*60}")
            print(f"Running tests: {test_file}")
            print(f"{'='*60}")
            
            try:
                result = subprocess.run([
                    sys.executable, "-m", "pytest", 
                    str(test_path),
                    "-v",
                    "--tb=short",
                    "--color=yes"
                ], cwd=project_root, capture_output=True, text=True)
                
                print(result.stdout)
                if result.stderr:
                    print("STDERR:", result.stderr)
                
                results.append((test_file, result.returncode == 0))
                
            except Exception as e:
                print(f"Error running tests for {test_file}: {e}")
                results.append((test_file, False))
        else:
            print(f"Test file not found: {test_file}")
            results.append((test_file, False))
    
    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    
    passed = 0
    failed = 0
    
    for test_file, success in results:
        status = "PASSED" if success else "FAILED"
        print(f"{test_file}: {status}")
        if success:
            passed += 1
        else:
            failed += 1
    
    print(f"\nTotal: {len(results)} test suites")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    if failed > 0:
        print("\n❌ Some tests failed!")
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)


def run_specific_test(test_name):
    """Run a specific test by name."""
    project_root = Path(__file__).parent.parent.parent.parent
    
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest",
            f"libs/agno/tests/unit/tools/test_scrapegraph.py::{test_name}",
            "-v",
            "--tb=short",
            "--color=yes"
        ], cwd=project_root)
        
        return result.returncode == 0
    except Exception as e:
        print(f"Error running test {test_name}: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Run specific test
        test_name = sys.argv[1]
        success = run_specific_test(test_name)
        sys.exit(0 if success else 1)
    else:
        # Run all tests
        run_tests()
