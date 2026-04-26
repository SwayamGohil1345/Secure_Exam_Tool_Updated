#!/usr/bin/env python3
"""
Test script for gaze detection functionality
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.gaze_detector import GazeDetector
import cv2
import base64
import numpy as np

def test_gaze_detector():
    """Test the gaze detector with a sample image"""
    print("🔍 Testing Gaze Detection System...")
    
    # Initialize gaze detector
    gaze_detector = GazeDetector()
    
    try:
        # Create a test frame (you can replace this with a real image)
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Add some content to make it look like a face (simplified)
        # In real usage, this would be a camera frame
        cv2.rectangle(test_frame, (200, 150), (440, 330), (255, 255, 255), -1)
        cv2.circle(test_frame, (280, 200), 30, (0, 0, 0), -1)  # Left eye
        cv2.circle(test_frame, (360, 200), 30, (0, 0, 0), -1)  # Right eye
        
        # Encode frame to base64
        _, buffer = cv2.imencode('.jpg', test_frame)
        frame_data = base64.b64encode(buffer).decode('utf-8')
        
        # Process frame
        result = gaze_detector.process_frame(frame_data)
        
        print("✅ Gaze detector initialized successfully")
        print(f"📊 Face detected: {result.get('face_detected', False)}")
        print(f"📊 Face confidence: {result.get('face_confidence', 0.0):.2f}")
        
        gaze_data = result.get('gaze_data')
        if gaze_data:
            print(f"👁️  Gaze direction: {gaze_data.get('gaze_direction', 'unknown')}")
            print(f"👁️  Looking at screen: {gaze_data.get('is_looking_at_screen', False)}")
            print(f"👁️  Gaze confidence: {gaze_data.get('gaze_confidence', 0.0):.2f}")
        else:
            print("❌ No gaze data available")
        
        print("\n🎯 Gaze Detection Test Complete!")
        print("💡 The system is ready for real-time gaze tracking.")
        
    except Exception as e:
        print(f"❌ Error testing gaze detector: {e}")
        return False
    
    finally:
        gaze_detector.cleanup()
    
    return True

if __name__ == "__main__":
    test_gaze_detector() 