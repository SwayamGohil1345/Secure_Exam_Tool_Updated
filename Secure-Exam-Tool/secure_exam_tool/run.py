#!/usr/bin/env python3
"""
Secure Exam Tool Runner
Simple script to start the secure exam application
"""

import os
import sys
import subprocess
import webbrowser
import time
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        import flask
        import cv2
        import mediapipe
        import numpy
        import flask_socketio
        import werkzeug
        print("✅ All dependencies are installed")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please install dependencies with: pip install -r requirements.txt")
        return False

def install_dependencies():
    """Install required dependencies"""
    print("Installing dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError:
        print("❌ Failed to install dependencies")
        return False

def create_test_users():
    """Create test users if they don't exist"""
    try:
        from create_user import create_test_users
        create_test_users()
        return True
    except Exception as e:
        print(f"⚠️  Could not create test users: {e}")
        return False

def start_application():
    """Start the Flask application"""
    print("🚀 Starting Secure Exam Tool...")
    print("📝 Application will be available at: http://localhost:5000")
    print("📹 Make sure your camera is available for proctoring features")
    print("⏹️  Press Ctrl+C to stop the application")
    print("-" * 50)
    
    try:
        # Import and run the app
        from app import app, socketio
        socketio.run(app, debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\n🛑 Application stopped by user")
    except Exception as e:
        print(f"❌ Error starting application: {e}")

def open_browser():
    """Open the application in default browser"""
    time.sleep(2)  # Wait for server to start
    try:
        webbrowser.open('http://localhost:5000')
        print("🌐 Opened application in browser")
    except Exception as e:
        print(f"⚠️  Could not open browser automatically: {e}")
        print("Please manually open: http://localhost:5000")

def main():
    """Main function"""
    print("🔒 Secure Exam Tool")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not Path("app.py").exists():
        print("❌ Error: app.py not found")
        print("Please run this script from the secure_exam_tool directory")
        sys.exit(1)
    
    # Check dependencies
    if not check_dependencies():
        print("\n📦 Installing dependencies...")
        if not install_dependencies():
            sys.exit(1)
    
    # Create test users
    print("\n👥 Setting up test users...")
    create_test_users()
    
    # Start application
    print("\n🎯 Starting application...")
    start_application()

if __name__ == "__main__":
    main() 