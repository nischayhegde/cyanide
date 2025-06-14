#!/usr/bin/env python3
"""
Test script to demonstrate the performance improvement of the persistent GPU vanity generator
compared to the original implementation that reinitializes GPU context every time.
"""

import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "vanitygenerator")))

from vanitygenerator.generatekeys import generate_similar_address as original_generator
from vanitygenerator.persistent_generator import generate_similar_address_persistent


def test_original_generator(test_address, num_tests=3):
    """Test the original generator that reinitializes GPU context each time."""
    print(f"\n=== Testing Original Generator (reinitializes GPU each time) ===")
    times = []
    
    for i in range(num_tests):
        print(f"Test {i+1}/{num_tests}...")
        start_time = time.time()
        try:
            result = original_generator(test_address, force_gpu_0=True)
            end_time = time.time()
            duration = end_time - start_time
            times.append(duration)
            print(f"  Generated: {result['public_key']}")
            print(f"  Time: {duration:.2f} seconds")
        except Exception as e:
            print(f"  Error: {e}")
            times.append(float('inf'))
    
    if times and any(t != float('inf') for t in times):
        valid_times = [t for t in times if t != float('inf')]
        avg_time = sum(valid_times) / len(valid_times)
        print(f"Average time: {avg_time:.2f} seconds")
        return avg_time
    return None


def test_persistent_generator(test_address, num_tests=3):
    """Test the persistent generator that reuses GPU context."""
    print(f"\n=== Testing Persistent Generator (reuses GPU context) ===")
    times = []
    
    for i in range(num_tests):
        print(f"Test {i+1}/{num_tests}...")
        start_time = time.time()
        try:
            result = generate_similar_address_persistent(test_address)
            end_time = time.time()
            duration = end_time - start_time
            times.append(duration)
            print(f"  Generated: {result['public_key']}")
            print(f"  Time: {duration:.2f} seconds")
        except Exception as e:
            print(f"  Error: {e}")
            times.append(float('inf'))
    
    if times and any(t != float('inf') for t in times):
        valid_times = [t for t in times if t != float('inf')]
        avg_time = sum(valid_times) / len(valid_times)
        print(f"Average time: {avg_time:.2f} seconds")
        return avg_time
    return None


def main():
    # Test address to generate similar addresses for
    test_address = "RAPELos1e9qSs2u7TsThXqkBSRVFxhmYaFKFZ1waUdcQ"
    num_tests = 3
    
    print("=" * 70)
    print("GPU Vanity Generator Performance Comparison")
    print("=" * 70)
    print(f"Test address: {test_address}")
    print(f"Target pattern: {test_address[:4]}")
    print(f"Number of tests per method: {num_tests}")
    
    # Test original generator
    try:
        original_avg = test_original_generator(test_address, num_tests)
    except Exception as e:
        print(f"Original generator failed: {e}")
        original_avg = None
    
    # Test persistent generator
    try:
        persistent_avg = test_persistent_generator(test_address, num_tests)
    except Exception as e:
        print(f"Persistent generator failed: {e}")
        persistent_avg = None
    
    # Compare results
    print(f"\n{'=' * 70}")
    print("PERFORMANCE COMPARISON")
    print(f"{'=' * 70}")
    
    if original_avg and persistent_avg:
        improvement = ((original_avg - persistent_avg) / original_avg) * 100
        speedup = original_avg / persistent_avg
        
        print(f"Original Generator Average:    {original_avg:.2f} seconds")
        print(f"Persistent Generator Average: {persistent_avg:.2f} seconds")
        print(f"Performance Improvement:      {improvement:.1f}%")
        print(f"Speedup Factor:               {speedup:.2f}x")
        
        if improvement > 0:
            print(f"\n✅ Persistent generator is {improvement:.1f}% faster!")
            print(f"💡 This improvement will be more significant with frequent address generation")
        else:
            print(f"\n⚠️  Results inconclusive. Try running more tests or check GPU utilization.")
    else:
        print("Could not complete comparison due to errors.")
        if not original_avg:
            print("- Original generator failed")
        if not persistent_avg:
            print("- Persistent generator failed")
    
    print(f"\n{'=' * 70}")
    print("NOTES:")
    print("- The first run of each method includes GPU initialization overhead")
    print("- Persistent generator reuses GPU context, avoiding reinitialization")
    print("- Performance benefits increase with more frequent address generation")
    print("- GPU context is automatically cleaned up after 20 minutes of inactivity")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main() 