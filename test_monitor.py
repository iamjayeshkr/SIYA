#!/usr/bin/env python3
"""
Quick test script for attention monitor.
Tests that all dependencies are working and monitor can start without crashes.
"""

import sys
import time

def test_imports():
    """Test that all required packages can be imported."""
    print("Testing imports...")
    try:
        import numpy
        print(f"✅ numpy {numpy.__version__}")
    except Exception as e:
        print(f"❌ numpy import failed: {e}")
        return False
    
    try:
        import cv2
        print(f"✅ opencv {cv2.__version__}")
    except Exception as e:
        print(f"❌ opencv import failed: {e}")
        return False
    
    try:
        import mediapipe
        print(f"✅ mediapipe {mediapipe.__version__}")
    except Exception as e:
        print(f"❌ mediapipe import failed: {e}")
        return False
    
    return True

def test_monitor():
    """Test that attention monitor can be initialized and started."""
    print("\nTesting attention monitor...")
    try:
        from vani.monitor.attention_monitor import AttentionMonitor
        
        def on_distraction(reason, score):
            print(f"📢 Distraction detected: {reason} (score: {score:.2f})")
        
        monitor = AttentionMonitor(on_distraction_callback=on_distraction)
        print("✅ Monitor initialized")
        
        print("Starting monitor for 5 seconds...")
        monitor.start()
        print("✅ Monitor started")
        
        time.sleep(5)
        
        print("Stopping monitor...")
        monitor.stop()
        print("✅ Monitor stopped")
        
        return True
    except Exception as e:
        print(f"❌ Monitor test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("=" * 60)
    print("Vani Attention Monitor Test")
    print("=" * 60)
    print()
    
    # Test imports
    if not test_imports():
        print("\n❌ Import test failed!")
        sys.exit(1)
    
    print("\n✅ All imports successful!")
    
    # Test monitor
    if not test_monitor():
        print("\n❌ Monitor test failed!")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
    print("\nThe attention monitor is ready to use.")
    print("Start Vani and say: 'study session shuru karo'")

if __name__ == "__main__":
    main()
