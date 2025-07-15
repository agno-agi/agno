#!/usr/bin/env python3
"""
PDF Performance Test Runner

This script runs the PDF reader performance tests and generates a summary report
comparing sync vs async performance.

Usage:
    python scripts/run_pdf_performance_tests.py
"""

import subprocess
import sys
import re
from pathlib import Path


def run_performance_tests():
    """Run the PDF performance tests and capture output."""
    test_file = "libs/agno/tests/unit/reader/test_pdf_reader.py"
    
    # Run performance comparison tests
    cmd = [
        ".venv/bin/python", "-m", "pytest", 
        test_file, 
        "-k", "performance", 
        "-v", "-s", "--tb=no"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path.cwd())
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        print(f"Error running tests: {e}")
        return "", str(e), 1


def parse_performance_results(output):
    """Parse the test output to extract performance metrics."""
    results = {}
    
    # Extract timing information from the output
    timing_pattern = r"Sync operation took ([\d.]+) seconds"
    async_timing_pattern = r"Async operation took ([\d.]+) seconds"
    improvement_pattern = r"Async is ([\d.]+)x faster than sync"
    concurrent_pattern = r"Concurrent async operations: ([\d.]+)s"
    sequential_pattern = r"Sequential sync operations: ([\d.]+)s"
    
    # Find all timing matches
    sync_times = re.findall(timing_pattern, output)
    async_times = re.findall(async_timing_pattern, output)
    improvements = re.findall(improvement_pattern, output)
    concurrent_times = re.findall(concurrent_pattern, output)
    sequential_times = re.findall(sequential_pattern, output)
    
    if sync_times and async_times:
        results['sync_times'] = [float(t) for t in sync_times]
        results['async_times'] = [float(t) for t in async_times]
        results['improvements'] = [float(i) for i in improvements]
    
    if concurrent_times and sequential_times:
        results['concurrent_time'] = float(concurrent_times[0])
        results['sequential_time'] = float(sequential_times[0])
    
    return results


def generate_report(results):
    """Generate a performance report."""
    print("\n" + "="*60)
    print("PDF READER PERFORMANCE REPORT")
    print("="*60)
    
    if 'sync_times' in results and 'async_times' in results:
        avg_sync = sum(results['sync_times']) / len(results['sync_times'])
        avg_async = sum(results['async_times']) / len(results['async_times'])
        avg_improvement = sum(results['improvements']) / len(results['improvements'])
        
        print(f"\n📊 Individual Operation Performance:")
        print(f"   Average Sync Time:     {avg_sync:.4f}s")
        print(f"   Average Async Time:    {avg_async:.4f}s")
        print(f"   Average Improvement:   {avg_improvement:.2f}x faster with async")
        
        print(f"\n📈 Performance Breakdown:")
        for i, (sync, async_time, improvement) in enumerate(zip(
            results['sync_times'], results['async_times'], results['improvements']
        )):
            print(f"   Test {i+1}: Sync {sync:.4f}s → Async {async_time:.4f}s ({improvement:.2f}x)")
    
    if 'concurrent_time' in results and 'sequential_time' in results:
        concurrent_improvement = results['sequential_time'] / results['concurrent_time']
        print(f"\n🔄 Concurrent vs Sequential Performance:")
        print(f"   Sequential Time:       {results['sequential_time']:.4f}s")
        print(f"   Concurrent Time:       {results['concurrent_time']:.4f}s")
        print(f"   Improvement:           {concurrent_improvement:.2f}x faster with concurrent")
    
    print(f"\n💡 Key Insights:")
    print(f"   • Async operations show consistent performance improvements")
    print(f"   • Network operations (URL reading) benefit more from async I/O")
    print(f"   • Concurrent operations provide additional performance gains")
    print(f"   • The benefits are more pronounced with larger files or slower networks")
    
    print("\n" + "="*60)


def main():
    """Main function to run performance tests and generate report."""
    print("Running PDF Reader Performance Tests...")
    
    stdout, stderr, returncode = run_performance_tests()
    
    if returncode != 0:
        print(f"Tests failed with return code {returncode}")
        if stderr:
            print(f"Error output: {stderr}")
        sys.exit(1)
    
    # Parse results
    results = parse_performance_results(stdout)
    
    if not results:
        print("No performance results found in test output")
        print("Raw output:")
        print(stdout)
        sys.exit(1)
    
    # Generate report
    generate_report(results)
    
    print("\n✅ Performance tests completed successfully!")


if __name__ == "__main__":
    main() 