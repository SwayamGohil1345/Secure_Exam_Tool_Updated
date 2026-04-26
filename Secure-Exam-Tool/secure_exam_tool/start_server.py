#!/usr/bin/env python3
"""
Simple server startup script
"""

from app import app, socketio

if __name__ == '__main__':
    print("🚀 Starting Secure Exam Tool Server...")
    print("📝 Application will be available at: http://localhost:5000")
    print("⏹️  Press Ctrl+C to stop the server")
    print("-" * 50)
    
    try:
        socketio.run(app, debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Error starting server: {e}") 