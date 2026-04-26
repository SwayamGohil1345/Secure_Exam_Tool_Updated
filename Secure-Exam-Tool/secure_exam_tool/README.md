<!-- "I want to implement a secure functionality in my remote proctoring-based exam tool where, once a user submits the exam, the system should automatically check their total score. If the user has scored greater than or equal to 70%, then I (the admin) should receive a mobile phone notification containing the user's login details (like name, email, phone, or any data they filled during login). This feature must be fully secure, should not disturb or alter any existing functionality, and must operate only when the exam is submitted and the criteria is met."
 -->


# Secure Exam Tool with Remote Proctoring

A comprehensive web-based examination system with advanced remote proctoring capabilities including camera monitoring, tab switching detection, and gaze tracking.

## Features

### 🔒 Security Features
- **Camera Monitoring**: Real-time face detection and tracking
- **Tab Switching Detection**: Detects when students switch tabs or applications
- **Gaze Tracking**: Monitors student eye movement and attention
- **Session Management**: Automatic session termination for violations
- **Warning System**: Progressive warning system with configurable limits

### 📊 Proctoring Capabilities
- **Face Detection**: Ensures student presence in front of camera
- **Gaze Violation Detection**: Monitors if student looks away from screen
- **Tab Switch Monitoring**: Detects switching to other applications/tabs
- **Real-time Alerts**: Instant notifications for violations
- **Session Logging**: Comprehensive logging of all activities

### 🎯 Exam Features
- **Secure Interface**: Prevents right-click, copy-paste, and keyboard shortcuts
- **Timer**: Real-time exam timer with countdown
- **Question Display**: Clean, professional question interface
- **Responsive Design**: Works on desktop and mobile devices

## Installation

### Prerequisites
- Python 3.8 or higher
- Webcam for proctoring features
- Modern web browser with camera permissions

### Setup Instructions

1. **Clone or download the project files**
   ```bash
   # If you have the files in a folder, navigate to it
   cd secure_exam_tool
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**
   ```bash
   python app.py
   ```

4. **Access the application**
   - Open your web browser
   - Navigate to `http://localhost:5000`
   - Allow camera permissions when prompted

## Usage

### For Students

1. **Start Exam Session**
   - Enter your Student ID
   - Enter the Exam Code
   - Click "Start Exam"

2. **During Exam**
   - Stay in front of the camera
   - Don't switch tabs or applications
   - Keep your gaze on the screen
   - Answer questions using the provided interface

3. **Warnings and Violations**
   - You'll receive warnings for violations
   - Multiple violations may result in session termination
   - Tab switching: 5 warnings maximum
   - Gaze violations: 10 warnings maximum

### For Administrators

1. **Monitor Sessions**
   - View active sessions in real-time
   - Check violation logs
   - Monitor student activity

2. **Configure Settings**
   - Adjust warning limits
   - Set session timeouts
   - Configure camera settings

## Configuration

### Warning Limits
You can modify the warning limits in `app.py`:

```python
MAX_TAB_SWITCH_WARNINGS = 5    # Maximum tab switch warnings
MAX_GAZE_WARNINGS = 10         # Maximum gaze violation warnings
```

### Camera Settings
Adjust camera resolution and quality in `templates/exam_room.html`:

```javascript
const stream = await navigator.mediaDevices.getUserMedia({ 
    video: { 
        width: 640, 
        height: 480,
        facingMode: 'user'
    } 
});
```

## File Structure

```
secure_exam_tool/
├── app.py                     # Main Flask application
├── requirements.txt           # Python dependencies
├── README.md                 # This file
├── templates/
│   ├── index.html            # Landing page
│   └── exam_room.html        # Exam interface
├── static/
│   ├── css/
│   │   └── styles.css        # Custom styles
│   └── js/
│       └── proctor.js        # Proctoring JavaScript
└── utils/
    └── proctor_utils.py      # Proctoring utilities
```

## Technical Details

### Backend (Python/Flask)
- **Flask**: Web framework for the application
- **Socket.IO**: Real-time communication
- **OpenCV**: Computer vision for face detection
- **MediaPipe**: Advanced face mesh and gaze tracking
- **NumPy**: Numerical computations

### Frontend (HTML/CSS/JavaScript)
- **Bootstrap**: UI framework for responsive design
- **Socket.IO Client**: Real-time communication
- **MediaDevices API**: Camera access
- **Canvas API**: Image processing

### Security Features
- **Tab Switching Detection**: Uses `visibilitychange` and `blur` events
- **Gaze Tracking**: Computer vision-based eye tracking
- **Face Detection**: Real-time face presence monitoring
- **Session Management**: Automatic violation tracking and termination

## Troubleshooting

### Common Issues

1. **Camera not working**
   - Ensure camera permissions are granted
   - Check if camera is being used by another application
   - Try refreshing the page

2. **Face detection not working**
   - Ensure good lighting
   - Position yourself clearly in front of camera
   - Check camera resolution settings

3. **Tab switching detection too sensitive**
   - Adjust the debounce timing in the JavaScript code
   - Modify warning thresholds

4. **Performance issues**
   - Reduce camera resolution
   - Close other applications
   - Check system resources

### Browser Compatibility
- **Chrome**: Full support (recommended)
- **Firefox**: Full support
- **Safari**: Limited support
- **Edge**: Full support

## Development

### Adding New Features

1. **New Proctoring Rules**
   - Add detection logic in `proctor_utils.py`
   - Update frontend JavaScript
   - Modify warning system

2. **Custom Exam Interface**
   - Modify `templates/exam_room.html`
   - Add custom CSS in `static/css/styles.css`
   - Update JavaScript functionality

3. **Backend Extensions**
   - Add new routes in `app.py`
   - Extend `ProctorSession` class
   - Implement new Socket.IO events

### Testing

1. **Local Testing**
   ```bash
   python app.py
   # Open multiple browser tabs to test tab switching
   # Move away from camera to test gaze tracking
   ```

2. **Production Deployment**
   - Use a production WSGI server (Gunicorn)
   - Set up proper SSL certificates
   - Configure firewall rules
   - Use a reverse proxy (Nginx)

## Security Considerations

### Data Privacy
- Camera data is processed locally
- No video recordings are stored
- Session logs contain only metadata
- All data is encrypted in transit

### Access Control
- Implement proper authentication
- Use HTTPS in production
- Regular security updates
- Monitor for suspicious activity

## License

This project is provided as-is for educational and development purposes. Please ensure compliance with local privacy and data protection laws when using this tool.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review the configuration options
3. Test with different browsers
4. Verify camera permissions

## Future Enhancements

- [ ] Multi-language support
- [ ] Advanced AI proctoring
- [ ] Mobile app version
- [ ] Integration with LMS systems
- [ ] Advanced analytics dashboard
- [ ] Custom exam templates
- [ ] Multi-camera support
- [ ] Voice detection
- [ ] Screen recording
- [ ] Automated grading system 