from flask import Flask, render_template, request, jsonify, session, redirect, url_for, abort, make_response
from flask_socketio import SocketIO, emit, disconnect
import cv2
import mediapipe as mp
import numpy as np
import base64
import threading
import time
import json
from datetime import datetime
import os
from utils.gaze_detector import GazeDetector
import random

# Load enhanced questions at startup
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_QUESTIONS_CANDIDATES = [
    os.path.join(_BASE_DIR, '..', 'gate_questions_enhanced_20250718_131808.json'),
    os.path.join(_BASE_DIR, '..', 'gate_questions_enhanced_20250718_131808 copy.json'),
    os.path.join(_BASE_DIR, 'gate_questions_enhanced_20250718_131808.json'),
    os.path.join(_BASE_DIR, 'gate_questions_enhanced_20250718_131808 copy.json'),
]

_questions_path = next((p for p in _QUESTIONS_CANDIDATES if os.path.exists(p)), None)
if not _questions_path:
    raise FileNotFoundError(
        "Enhanced questions JSON not found. Tried: "
        + ", ".join(_QUESTIONS_CANDIDATES)
    )
with open(_questions_path, 'r', encoding='utf-8') as f:
    ENHANCED_QUESTIONS = json.load(f)

def get_questions_by_difficulty():
    # Returns dict: {'easy': [...], 'medium': [...], 'hard': [...]}
    diff_map = {'EASY': 'easy', 'MEDIUM': 'medium', 'HARD': 'hard'}
    by_diff = {'easy': [], 'medium': [], 'hard': []}
    for k, v in ENHANCED_QUESTIONS.items():
        for q in v:
            if diff_map.get(k):
                by_diff[diff_map[k]].append(q)
    return by_diff

QUESTIONS_BY_DIFF = get_questions_by_difficulty()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global variables for tracking - RESPONSIVE BUT CONTROLLED
active_sessions = {}
warning_counts = {}
tab_switch_warnings = 0
gaze_warnings = 0
MAX_TAB_SWITCH_WARNINGS = 3  # Tab switching warnings
MAX_GAZE_WARNINGS = 5  # Gaze warnings

# Initialize gaze detector
try:
    gaze_detector = GazeDetector()
except Exception as e:
    print(f"Warning: GazeDetector disabled (startup error: {e})")
    gaze_detector = None

class ProctorSession:
    def __init__(self, session_id, student_id):
        self.session_id = session_id
        self.student_id = student_id
        self.tab_switch_warnings = 0
        self.gaze_warnings = 0
        self.is_active = True
        self.start_time = datetime.now()
        self.last_activity = datetime.now()
        self.last_gaze_check = datetime.now()
        self.gaze_violation_start = None
        self.face_not_visible_start = None
        # Exam logic fields:
        self.question_sequence = []  # List of question dicts
        self.answers = []  # List of dicts: {question_id, selected, correct, time_taken}
        self.current_index = 0
        self.generate_dynamic_sequence()

    def generate_dynamic_sequence(self):
        # Generate a 60-question sequence with dynamic difficulty
        seq = []
        easy = QUESTIONS_BY_DIFF['easy'][:]
        medium = QUESTIONS_BY_DIFF['medium'][:]
        hard = QUESTIONS_BY_DIFF['hard'][:]
        random.shuffle(easy)
        random.shuffle(medium)
        random.shuffle(hard)
        idx_easy = idx_medium = idx_hard = 0
        difficulty = 'easy'
        wrong_streak = 0
        for i in range(60):
            if difficulty == 'easy':
                if idx_easy >= len(easy):
                    random.shuffle(easy)
                    idx_easy = 0
                q = easy[idx_easy]
                idx_easy += 1
            elif difficulty == 'medium':
                if idx_medium >= len(medium):
                    random.shuffle(medium)
                    idx_medium = 0
                q = medium[idx_medium]
                idx_medium += 1
            else:
                if idx_hard >= len(hard):
                    random.shuffle(hard)
                    idx_hard = 0
                q = hard[idx_hard]
                idx_hard += 1
            seq.append(q)
            # Dynamic difficulty logic: after each question, set next difficulty
            if len(self.answers) > 0 and not self.answers[-1]['correct']:
                # If last answer was wrong, next 3 questions same difficulty
                wrong_streak += 1
                if wrong_streak < 3:
                    # Stay on same difficulty
                    pass
                else:
                    wrong_streak = 0
                    difficulty = 'easy'  # Reset to easy after 3
            else:
                wrong_streak = 0
                if difficulty == 'easy':
                    difficulty = 'medium'
                elif difficulty == 'medium':
                    difficulty = 'hard'
                else:
                    difficulty = 'hard'
        self.question_sequence = seq
        self.answers = []
        self.current_index = 0

@app.route('/')
def welcome():
    return render_template('welcome.html')

@app.route('/instructions')
def instructions():
    return render_template('instructions.html')

@app.route('/login')
def login():
    """Display login page with blocked user check"""
    # Check for any blocked user data in cookies or session
    try:
        # Check if there are any blocked users
        blocked_data = load_blocked_users()
        blocked_users = blocked_data.get('blocked_users', [])
        
        # Check if there are any blocked users and redirect if necessary
        if blocked_users:
            # Add blocked users data to template context for frontend check
            # Also add a flag to indicate blocked users exist
            return render_template('index.html', blocked_users=blocked_users, has_blocked_users=True)
        else:
            return render_template('index.html', has_blocked_users=False)
    except Exception as e:
        print(f"Error checking blocked users in login route: {e}")
        return render_template('index.html', has_blocked_users=False)

# Add a middleware to check for blocked users on all routes
@app.before_request
def check_blocked_users():
    """Check for blocked users before processing any request"""
    try:
        # Only check on login page for now to avoid performance issues
        if request.endpoint == 'login':
            blocked_data = load_blocked_users()
            blocked_users = blocked_data.get('blocked_users', [])
            
            # If there are blocked users, we'll let the frontend handle the check
            # This ensures blocked users are caught by the comprehensive check
            pass
    except Exception as e:
        print(f"Error in before_request blocked user check: {e}")

# Add a route to completely block access for blocked users
@app.route('/blocked_access')
def blocked_access():
    """Redirect blocked users to violation page"""
    return redirect('/cheating_violation')

@app.route('/countdown')
def countdown():
    return render_template('countdown.html')

@app.route('/exam/<session_id>')
def exam_room(session_id):
    if session_id not in active_sessions:
        return redirect(url_for('index'))
    return render_template('exam_room.html', session_id=session_id)

@app.route('/api/start_session', methods=['POST'])
def start_session():
    data = request.get_json()
    student_id = data.get('student_id')
    exam_code = data.get('exam_code')  # This is actually the email
    session_id = f"session_{int(time.time())}"
    
    # Create session with both student_id and email
    session = ProctorSession(session_id, student_id)
    session.user_email = exam_code  # Store email in session
    active_sessions[session_id] = session
    
    return jsonify({
        'session_id': session_id,
        'status': 'started'
    })

@app.route('/api/end_session/<session_id>', methods=['POST'])
def end_session(session_id):
    if session_id in active_sessions:
        active_sessions[session_id].is_active = False
        del active_sessions[session_id]
    
    return jsonify({'status': 'ended'})

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('join_session')
def handle_join_session(data):
    session_id = data.get('session_id')
    if session_id in active_sessions:
        print(f'Student joined session: {session_id}')

@socketio.on('tab_switch_detected')
def handle_tab_switch(data):
    session_id = data.get('session_id')
    if session_id in active_sessions:
        session = active_sessions[session_id]
        session.tab_switch_warnings += 1
        
        if session.tab_switch_warnings >= MAX_TAB_SWITCH_WARNINGS:
            emit('session_terminated', {
                'reason': 'Maximum tab switch warnings exceeded',
                'warnings': session.tab_switch_warnings
            })
            session.is_active = False
        else:
            emit('warning', {
                'type': 'tab_switch',
                'message': f'Tab switching detected! Warning {session.tab_switch_warnings}/{MAX_TAB_SWITCH_WARNINGS}',
                'remaining': MAX_TAB_SWITCH_WARNINGS - session.tab_switch_warnings
            })

@socketio.on('gaze_violation')
def handle_gaze_violation(data):
    session_id = data.get('session_id')
    duration = data.get('duration', 0)  # Duration looking away in seconds
    severity = data.get('severity', 'moderate')
    
    if session_id in active_sessions:
        session = active_sessions[session_id]
        
        # Different penalty based on severity
        if severity == 'severe':
            session.gaze_warnings += 2  # Double penalty for severe violations
        elif severity == 'looking_down':
            session.gaze_warnings += 3  # Triple penalty for looking down (cheating behavior)
        elif severity == 'face_not_visible':
            session.gaze_warnings += 2  # Double penalty for face not visible (avoiding detection)
        else:
            session.gaze_warnings += 1
        
        if session.gaze_warnings >= MAX_GAZE_WARNINGS:
            emit('session_terminated', {
                'reason': 'Maximum gaze violation warnings exceeded',
                'warnings': session.gaze_warnings
            })
            session.is_active = False
        else:
            if severity == 'looking_down':
                severity_text = "LOOKING DOWN"
                custom_message = data.get('message', f'You have been looking down (likely at papers/notes) for {duration}s ({int(duration/60)}m {duration%60}s). This is a serious violation.')
            elif severity == 'face_not_visible':
                severity_text = "FACE NOT VISIBLE"
                custom_message = data.get('message', f'Your face is not visible in the camera for {duration}s. Please return to camera view immediately. Warning {session.gaze_warnings}/{MAX_GAZE_WARNINGS}')
            elif severity == 'severe':
                severity_text = "SEVERE"
                custom_message = f'{severity_text} gaze violation! You looked away for {duration}s ({int(duration/60)}m {duration%60}s). Warning {session.gaze_warnings}/{MAX_GAZE_WARNINGS}'
            else:
                severity_text = "MODERATE"
                custom_message = f'{severity_text} gaze violation! You looked away for {duration}s ({int(duration/60)}m {duration%60}s). Warning {session.gaze_warnings}/{MAX_GAZE_WARNINGS}'
            
            emit('warning', {
                'type': 'gaze_violation',
                'message': custom_message,
                'remaining': MAX_GAZE_WARNINGS - session.gaze_warnings,
                'severity': severity
            })

@socketio.on('process_frame')
def handle_process_frame(data):
    """Process video frame for gaze detection"""
    session_id = data.get('session_id')
    frame_data = data.get('frame_data')
    
    if session_id not in active_sessions:
        return
    
    session = active_sessions[session_id]
    if not session.is_active:
        return

    if gaze_detector is None:
        emit('gaze_update', {
            'gaze_data': None,
            'face_detected': False,
            'face_confidence': 0.0,
            'error': 'GazeDetector disabled due to startup error. Install a supported Python (<=3.11) and mediapipe to enable proctoring.'
        })
        return
    
    # Initialize frame counter for this session if not exists
    if not hasattr(session, 'frame_count'):
        session.frame_count = 0
    session.frame_count += 1
    
    try:
        # Process frame with gaze detector
        result = gaze_detector.process_frame(frame_data)
        
        # Update session with gaze data
        session.last_gaze_check = datetime.now()
        
        # Check for face detection violations
        face_detected = result.get('face_detected', False)
        print(f"Face detected: {face_detected}")
        
        if not face_detected:
            # Face not visible
            if session.face_not_visible_start is None:
                session.face_not_visible_start = datetime.now()
                print(f"Face not visible started for session {session_id}")
            
            # Check if face not visible for more than 8 seconds (responsive)
            time_face_not_visible = (datetime.now() - session.face_not_visible_start).total_seconds()
            
            if time_face_not_visible > 8:  # 8 seconds - face not visible violation (responsive)
                print(f"Face not visible violation: {time_face_not_visible:.1f}s for session {session_id}")
                handle_gaze_violation({
                    'session_id': session_id,
                    'duration': int(time_face_not_visible),
                    'severity': 'face_not_visible',
                    'message': f'Your face is not visible in the camera for {int(time_face_not_visible)} seconds. Please return to camera view immediately.'
                })
                session.face_not_visible_start = None
        else:
            # Face is visible
            if session.face_not_visible_start is not None:
                time_face_not_visible = (datetime.now() - session.face_not_visible_start).total_seconds()
                print(f"Face became visible after {time_face_not_visible:.1f}s for session {session_id}")
                session.face_not_visible_start = None
        
        # Check for gaze violations
        gaze_data = result.get('gaze_data')
        print(f"Gaze data: {gaze_data}")
        
        if gaze_data and not gaze_data.get('is_looking_at_screen', True):
            # Student is looking away
            if session.gaze_violation_start is None:
                session.gaze_violation_start = datetime.now()
                print(f"Gaze violation started for session {session_id}")
            
            # Check if looking away for too long (more realistic for exam scenarios)
            time_away = (datetime.now() - session.gaze_violation_start).total_seconds()
            
            # REALISTIC warning system for exam proctoring:
            # - Warning after 15 seconds (allows natural eye movements)
            # - Violation after 30 seconds (detects actual looking away)
            # - Severe violation after 60 seconds (detects cheating attempts)
            # - Special violation for looking down after 90 seconds (detects note reading)
            
            # Check for specific "looking down" violation (90 seconds)
            if time_away > 90:  # 90 seconds - looking down violation
                print(f"Looking down violation: {time_away:.1f}s away for session {session_id}")
                handle_gaze_violation({
                    'session_id': session_id,
                    'duration': int(time_away),
                    'severity': 'looking_down',
                    'message': f'You have been looking down (likely at papers/notes) for {int(time_away)} seconds. This is a violation.'
                })
                session.gaze_violation_start = None
            elif time_away > 60:  # 60 seconds - severe violation
                print(f"Severe gaze violation: {time_away:.1f}s away for session {session_id}")
                handle_gaze_violation({
                    'session_id': session_id,
                    'duration': int(time_away),
                    'severity': 'severe'
                })
                session.gaze_violation_start = None
            elif time_away > 30:  # 30 seconds - violation
                print(f"Gaze violation: {time_away:.1f}s away for session {session_id}")
                handle_gaze_violation({
                    'session_id': session_id,
                    'duration': int(time_away),
                    'severity': 'moderate'
                })
                session.gaze_violation_start = None
            elif time_away > 15:  # 15 seconds - warning
                print(f"Gaze warning: {time_away:.1f}s away for session {session_id}")
                
                # Send warning without counting as violation
                emit('gaze_warning', {
                    'session_id': session_id,
                    'duration': int(time_away),
                    'message': f'You have been looking away for {int(time_away)} seconds. Please focus on the screen.'
                })
        else:
            # Student is looking at screen
            if session.gaze_violation_start is not None:
                time_away = (datetime.now() - session.gaze_violation_start).total_seconds()
                print(f"Student returned to screen after {time_away:.1f}s for session {session_id}")
                session.gaze_violation_start = None
        
        # Check for specific cheating behaviors using new detection system
        detection_data = result.get('detection_data')
        if detection_data:
            # Check for eye direction cheating (looking left/right/up/down for 5+ seconds)
            if detection_data.get('cheating_detected', False):
                current_direction = detection_data.get('eye_direction', 'unknown')
                duration = detection_data.get('current_direction_duration', 0)
                
                print(f"Cheating behavior detected: {current_direction} for {duration:.1f}s")
                
                # Send unified warning for cheating behavior (includes voice support)
                emit('warning', {
                    'type': 'cheating_behavior',
                    'message': f'Cheating behavior detected: Looking {current_direction} for {int(duration)} seconds. This is a violation.',
                    'severity': 'severe',
                    'session_id': session_id,
                    'duration': int(duration)
                })
                
                # Handle cheating violation
                handle_gaze_violation({
                    'session_id': session_id,
                    'duration': int(duration),
                    'severity': 'cheating_behavior',
                    'message': f'Cheating behavior detected: Looking {current_direction} for {int(duration)} seconds. This is a violation.'
                })
                
                # Reset tracking
                if hasattr(gaze_detector, 'reset_lip_tracking'):
                    gaze_detector.reset_lip_tracking()
            
            # Check for lip movement (talking/whispering)
            lip_movement = detection_data.get('lip_movement', False)
            if lip_movement:
                print(f"Lip movement detected for session {session_id}")
                
                # Get detailed lip movement status for debugging
                lip_status = "Unknown"
                if hasattr(gaze_detector, 'get_lip_movement_status'):
                    lip_status = gaze_detector.get_lip_movement_status()
                print(f"Lip movement status: {lip_status}")
                
                # Send unified warning for lip movement (includes voice support)
                emit('warning', {
                    'type': 'lip_movement',
                    'message': 'Lip movement detected. Please do not talk or whisper during the exam.',
                    'severity': 'normal',
                    'session_id': session_id,
                    'debug_info': lip_status
                })
                
                # Also send legacy event for backward compatibility
                emit('lip_movement_warning', {
                    'session_id': session_id,
                    'message': 'Lip movement detected. Please do not talk or whisper during the exam.',
                    'debug_info': lip_status
                })
                
                # Reset lip tracking to avoid spam warnings
                if hasattr(gaze_detector, 'reset_lip_tracking'):
                    gaze_detector.reset_lip_tracking()
                    print(f"Lip tracking reset for session {session_id}")
            else:
                # Debug: Log when no lip movement is detected
                if session.frame_count % 30 == 0:  # Log every 30 frames to avoid spam
                    print(f"Session {session_id}: No lip movement detected (frame {session.frame_count})")
        
        # Send gaze data back to client
        emit('gaze_update', {
            'gaze_data': gaze_data,
            'face_detected': result.get('face_detected', False),
            'face_confidence': result.get('face_confidence', 0.0)
        })
        
    except Exception as e:
        print(f"Error processing frame: {e}")
        emit('gaze_update', {
            'gaze_data': None,
            'face_detected': False,
            'face_confidence': 0.0,
            'error': str(e)
        })

@socketio.on('heartbeat')
def handle_heartbeat(data):
    session_id = data.get('session_id')
    if session_id in active_sessions:
        active_sessions[session_id].last_activity = datetime.now()

@socketio.on('analyze_mobile_phone')
def handle_mobile_phone_analysis(data):
    """Analyze camera frame for mobile phone detection"""
    session_id = data.get('session_id')
    frame_data = data.get('frame_data')
    check_type = data.get('check_type')
    
    print(f"Analyzing mobile phone detection for session {session_id}")
    
    try:
        # Decode base64 frame data
        import base64
        import cv2
        import numpy as np
        
        # Remove data URL prefix if present
        if frame_data.startswith('data:image'):
            frame_data = frame_data.split(',')[1]
        
        # Decode base64 to image
        image_data = base64.b64decode(frame_data)
        nparr = np.frombuffer(image_data, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Simulate mobile phone detection using computer vision
        # In real implementation, use object detection models
        has_mobile_phone = detect_mobile_phone(frame)
        
        # Send result back to client
        socketio.emit('mobile_phone_result', {
            'session_id': session_id,
            'has_mobile_phone': has_mobile_phone,
            'confidence': 0.85 if has_mobile_phone else 0.95
        })
        
    except Exception as e:
        print(f"Error analyzing mobile phone: {e}")
        socketio.emit('mobile_phone_result', {
            'session_id': session_id,
            'has_mobile_phone': False,
            'confidence': 0.0,
            'error': str(e)
        })

@socketio.on('analyze_electronics')
def handle_electronics_analysis(data):
    """Analyze camera frame for electronic devices detection"""
    session_id = data.get('session_id')
    frame_data = data.get('frame_data')
    check_type = data.get('check_type')
    
    print(f"Analyzing electronics detection for session {session_id}")
    
    try:
        # Decode base64 frame data
        import base64
        import cv2
        import numpy as np
        
        # Remove data URL prefix if present
        if frame_data.startswith('data:image'):
            frame_data = frame_data.split(',')[1]
        
        # Decode base64 to image
        image_data = base64.b64decode(frame_data)
        nparr = np.frombuffer(image_data, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Enhanced electronics detection with better accuracy
        has_electronics = detect_electronics(frame)
        
        # Be more lenient - only flag if very confident
        if has_electronics:
            # Double-check with additional analysis
            confidence = 0.85
            # Only flag if very confident about electronics
            if confidence > 0.8:
                has_electronics = True
            else:
                has_electronics = False  # Be lenient if not very confident
        
        # Send result back to client
        socketio.emit('electronics_result', {
            'session_id': session_id,
            'has_electronics': has_electronics,
            'confidence': confidence if has_electronics else 0.95
        })
        
    except Exception as e:
        print(f"Error analyzing electronics: {e}")
        socketio.emit('electronics_result', {
            'session_id': session_id,
            'has_electronics': False,
            'confidence': 0.0,
            'error': str(e)
        })

@socketio.on('analyze_background_people')
def handle_background_people_analysis(data):
    """Analyze camera frame for background people detection"""
    session_id = data.get('session_id')
    frame_data = data.get('frame_data')
    check_type = data.get('check_type')
    
    print(f"Analyzing background people detection for session {session_id}")
    
    try:
        # Decode base64 frame data
        import base64
        import cv2
        import numpy as np
        
        # Remove data URL prefix if present
        if frame_data.startswith('data:image'):
            frame_data = frame_data.split(',')[1]
        
        # Decode base64 to image
        image_data = base64.b64decode(frame_data)
        nparr = np.frombuffer(image_data, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Enhanced people detection with better accuracy
        has_people = detect_background_people(frame)
        
        # Be more lenient - only flag if very confident about multiple people
        if has_people:
            # Additional verification - only flag if clearly multiple people
            confidence = 0.75
            # Only flag if very confident about multiple people
            if confidence > 0.7:
                has_people = True
            else:
                has_people = False  # Be lenient if not very confident
        
        # Send result back to client
        socketio.emit('background_people_result', {
            'session_id': session_id,
            'has_people': has_people,
            'confidence': confidence if has_people else 0.90
        })
        
    except Exception as e:
        print(f"Error analyzing background people: {e}")
        socketio.emit('background_people_result', {
            'session_id': session_id,
            'has_people': False,
            'confidence': 0.0,
            'error': str(e)
        })

def detect_mobile_phone(frame):
    """Detect mobile phones in the frame using enhanced computer vision"""
    try:
        # Convert to grayscale for processing
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Method 1: Enhanced edge detection for rectangular objects (phones)
        edges = cv2.Canny(gray, 30, 150)
        
        # Method 2: Look for bright areas (phone screens)
        _, bright_mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        
        # Method 3: Color-based detection for phone screens (blue light, white screens)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        # Detect blue light (common in phone screens)
        lower_blue = np.array([100, 50, 50])
        upper_blue = np.array([130, 255, 255])
        blue_mask = cv2.inRange(hsv, lower_blue, upper_blue)
        
        # Detect white/light areas (phone screens)
        lower_white = np.array([0, 0, 200])
        upper_white = np.array([180, 30, 255])
        white_mask = cv2.inRange(hsv, lower_white, upper_white)
        
        # Combine all detection methods
        combined_mask = cv2.bitwise_or(edges, bright_mask)
        combined_mask = cv2.bitwise_or(combined_mask, blue_mask)
        combined_mask = cv2.bitwise_or(combined_mask, white_mask)
        
        # Find contours
        contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        phone_detected = False
        detection_confidence = 0.0
        
        # Enhanced phone detection logic
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > 500:  # Minimum area threshold
                # Approximate contour to polygon
                epsilon = 0.02 * cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, epsilon, True)
                
                # Check if it's roughly rectangular (4 corners)
                if len(approx) == 4:
                    # Calculate aspect ratio
                    x, y, w, h = cv2.boundingRect(approx)
                    aspect_ratio = float(w) / h
                    
                    # Mobile phones typically have aspect ratio between 0.5 and 2.0
                    if 0.5 <= aspect_ratio <= 2.0:
                        # Additional check for phone-like characteristics
                        phone_detected = True
                        detection_confidence = 0.8
                        break
                
                # Check for bright rectangular areas (phone screens)
                elif len(approx) >= 4 and len(approx) <= 6:
                    x, y, w, h = cv2.boundingRect(approx)
                    aspect_ratio = float(w) / h
                    
                    # Look for bright areas that could be phone screens
                    roi = gray[y:y+h, x:x+w]
                    if roi.size > 0:
                        avg_brightness = np.mean(roi)
                        if avg_brightness > 150 and 0.5 <= aspect_ratio <= 2.0:
                            phone_detected = True
                            detection_confidence = 0.85
                            break
        
        # Method 4: Template matching for common phone shapes
        if not phone_detected:
            # Look for pairs of bright spots (common in phone screens)
            bright_spots = []
            for contour in contours:
                area = cv2.contourArea(contour)
                if 100 < area < 5000:
                    x, y, w, h = cv2.boundingRect(contour)
                    roi = gray[y:y+h, x:x+w]
                    if roi.size > 0:
                        avg_brightness = np.mean(roi)
                        if avg_brightness > 180:  # Very bright areas
                            bright_spots.append((x, y, w, h))
            
            # Check if we have bright areas that could be phone screens
            if len(bright_spots) >= 1:
                for spot in bright_spots:
                    x, y, w, h = spot
                    aspect_ratio = float(w) / h
                    if 0.5 <= aspect_ratio <= 2.0:
                        phone_detected = True
                        detection_confidence = 0.9
                        break
        
        # Method 5: Check for hand-phone interaction patterns
        if not phone_detected:
            # Look for hand-like shapes near rectangular objects
            hand_phone_patterns = 0
            for contour in contours:
                area = cv2.contourArea(contour)
                if 1000 < area < 20000:  # Medium to large objects
                    x, y, w, h = cv2.boundingRect(contour)
                    aspect_ratio = float(w) / h
                    
                    # Check if object is being held (hand-phone interaction)
                    if 0.3 <= aspect_ratio <= 3.0:
                        # Look for bright areas within the object (phone screen)
                        roi = gray[y:y+h, x:x+w]
                        if roi.size > 0:
                            avg_brightness = np.mean(roi)
                            if avg_brightness > 120:  # Moderately bright
                                hand_phone_patterns += 1
                                if hand_phone_patterns >= 2:
                                    phone_detected = True
                                    detection_confidence = 0.75
                                    break
        
        # Enhanced logging for debugging
        print(f"Mobile phone detection - Contours found: {len(contours)}")
        print(f"Phone detected: {phone_detected}")
        print(f"Confidence: {detection_confidence}")
        
        return phone_detected
        
    except Exception as e:
        print(f"Error in mobile phone detection: {e}")
        return False

def detect_electronics(frame):
    """Detect electronic devices in the frame with enhanced sensitivity for earbuds"""
    try:
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Focus on ear area - upper part of frame
        frame_height, frame_width = frame.shape[:2]
        ear_region_height = int(frame_height * 0.4)  # Upper 40% for ears
        ear_region = gray[0:ear_region_height, :]
        
        # Method 1: Enhanced threshold for small dark objects (earbuds)
        _, thresh = cv2.threshold(ear_region, 70, 255, cv2.THRESH_BINARY_INV)  # More sensitive threshold
        
        # Method 2: Edge detection for small circular objects in ear area
        edges = cv2.Canny(ear_region, 15, 60)  # More sensitive edge detection
        
        # Method 3: Color-based detection for black/dark earbuds in ear area
        ear_region_color = frame[0:ear_region_height, :]
        hsv = cv2.cvtColor(ear_region_color, cv2.COLOR_BGR2HSV)
        lower_black = np.array([0, 0, 0])
        upper_black = np.array([180, 255, 100])  # More sensitive to dark objects
        black_mask = cv2.inRange(hsv, lower_black, upper_black)
        
        # Method 4: Look for small bright spots (earbud tips) in ear area
        _, bright_mask = cv2.threshold(ear_region, 160, 255, cv2.THRESH_BINARY)
        
        # Combine detection methods for ear area
        combined_mask = cv2.bitwise_or(thresh, black_mask)
        combined_mask = cv2.bitwise_or(combined_mask, bright_mask)
        
        # Find contours in ear area
        contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        electronics_detected = False
        detection_confidence = 0.0
        
        # Enhanced earbud detection logic focused on ear area
        for contour in contours:
            area = cv2.contourArea(contour)
            
            # Very sensitive size range for earbuds in ears
            if 15 < area < 2000:  # Smaller range for earbuds in ears
                # Check if contour is roughly circular or oval (earbuds are usually round)
                perimeter = cv2.arcLength(contour, True)
                if perimeter > 0:
                    circularity = 4 * np.pi * area / (perimeter * perimeter)
                    
                    # More lenient circularity check for earbuds
                    if circularity > 0.1:  # Very lenient threshold for earbuds
                        # Additional checks for earbud-like characteristics
                        x, y, w, h = cv2.boundingRect(contour)
                        aspect_ratio = float(w) / h
                        
                        # Earbuds typically have aspect ratio close to 1 (circular)
                        if 0.2 <= aspect_ratio <= 3.0:  # More flexible aspect ratio
                            electronics_detected = True
                            detection_confidence = min(0.9, circularity * 3)
                            print(f"Earbud detected in ear area: area={area}, circularity={circularity}, pos=({x},{y})")
                            break
        
        # Method 5: Look for pairs of small objects (left and right earbuds)
        if not electronics_detected:
            small_objects = []
            for contour in contours:
                area = cv2.contourArea(contour)
                if 8 < area < 1200:  # Very small objects for earbuds
                    x, y, w, h = cv2.boundingRect(contour)
                    small_objects.append((x, y, w, h))
            
            # Check if we have pairs of objects that could be earbuds
            if len(small_objects) >= 2:
                # Look for objects that are roughly the same size and positioned symmetrically
                for i in range(len(small_objects)):
                    for j in range(i + 1, len(small_objects)):
                        x1, y1, w1, h1 = small_objects[i]
                        x2, y2, w2, h2 = small_objects[j]
                        
                        # Check if objects are similar in size
                        size_diff = abs(w1 * h1 - w2 * h2) / max(w1 * h1, w2 * h2)
                        
                        # Check if they're positioned symmetrically (left and right ears)
                        horizontal_distance = abs(x1 - x2)
                        
                        if (size_diff < 0.8 and  # More lenient size difference
                            horizontal_distance > frame_width * 0.05):  # Must be separated horizontally
                            electronics_detected = True
                            detection_confidence = 0.85
                            print(f"Earbud pair detected in ears: left=({x1},{y1}), right=({x2},{y2})")
                            break
                    if electronics_detected:
                        break
        
        # Method 6: Check for headphone-like objects (larger than earbuds)
        if not electronics_detected:
            for contour in contours:
                area = cv2.contourArea(contour)
                if 300 < area < 15000:  # Larger objects for headphones
                    x, y, w, h = cv2.boundingRect(contour)
                    aspect_ratio = float(w) / h
                    
                    # Headphones are typically wider than they are tall
                    if aspect_ratio > 1.1 and h < w:
                        electronics_detected = True
                        detection_confidence = 0.9
                        print(f"Headphones detected in ear area: area={area}, aspect_ratio={aspect_ratio}")
                        break
        
        # Method 7: Check for small bright spots that could be earbud tips
        if not electronics_detected:
            bright_spots = []
            for contour in contours:
                area = cv2.contourArea(contour)
                if 3 < area < 400:  # Very small bright spots
                    x, y, w, h = cv2.boundingRect(contour)
                    roi = ear_region[y:y+h, x:x+w]
                    if roi.size > 0:
                        avg_brightness = np.mean(roi)
                        if avg_brightness > 170:  # Very bright spots
                            bright_spots.append((x, y, w, h))
            
            # Check if we have bright spots that could be earbud tips
            if len(bright_spots) >= 1:
                for spot in bright_spots:
                    x, y, w, h = spot
                    electronics_detected = True
                    detection_confidence = 0.8
                    print(f"Bright earbud tip detected in ear area: pos=({x},{y})")
                    break
        
        # Enhanced logging for debugging
        print(f"Electronics detection in ear area - Objects found: {len(contours)}")
        print(f"Electronics detected: {electronics_detected}")
        print(f"Confidence: {detection_confidence}")
        
        return electronics_detected
        
    except Exception as e:
        print(f"Error in electronics detection: {e}")
        return False
        
    except Exception as e:
        print(f"Error in electronics detection: {e}")
        return False

def detect_background_people(frame):
    """Detect people in the background of the frame"""
    try:
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Use HOG (Histogram of Oriented Gradients) for people detection
        # This is a simplified version - in production, use more sophisticated models
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        
        # Detect people
        boxes, weights = hog.detectMultiScale(gray, winStride=(8, 8), padding=(4, 4), scale=1.05)
        
        # If multiple people detected (more than just the main person)
        if len(boxes) > 1:
            return True
        
        return False
        
    except Exception as e:
        print(f"Error in background people detection: {e}")
        return False

@app.route('/api/next_question/<session_id>', methods=['GET'])
def api_next_question(session_id):
    session = active_sessions.get(session_id)
    if not session or not session.is_active:
        return abort(404)
    idx = session.current_index
    if idx >= len(session.question_sequence):
        return jsonify({'done': True})
    q = session.question_sequence[idx].copy()
    # Remove solution from question sent to frontend
    q.pop('solution', None)
    return jsonify({'done': False, 'question': q, 'index': idx+1, 'total': len(session.question_sequence)})

@app.route('/api/submit_answer/<session_id>', methods=['POST'])
def api_submit_answer(session_id):
    session = active_sessions.get(session_id)
    if not session or not session.is_active:
        return abort(404)
    data = request.get_json()
    selected = data.get('selected')
    time_taken = data.get('time_taken')
    idx = session.current_index
    if idx >= len(session.question_sequence):
        return jsonify({'error': 'No more questions'})
    q = session.question_sequence[idx]
    correct = (selected == q['solution'])
    session.answers.append({
        'question_id': q['id'],
        'selected': selected,
        'correct': correct,
        'time_taken': time_taken,
        'difficulty': q.get('type', 1),
        'category': q.get('category', '')
    })
    session.current_index += 1
    return jsonify({'correct': correct, 'next_index': session.current_index})

@app.route('/api/exam_result/<session_id>', methods=['GET'])
def api_exam_result(session_id):
    session = active_sessions.get(session_id)
    if not session:
        return abort(404)
    total = len(session.answers)
    correct = sum(1 for a in session.answers if a['correct'])
    incorrect = total - correct
    total_time = sum(a['time_taken'] for a in session.answers if a.get('time_taken') is not None)
    avg_time = total_time / total if total else 0
    # Breakdown by difficulty and category
    diff_map = {1: 'easy', 2: 'medium', 3: 'hard'}
    by_diff = {'easy': {'correct': 0, 'total': 0}, 'medium': {'correct': 0, 'total': 0}, 'hard': {'correct': 0, 'total': 0}}
    by_cat = {}
    for a in session.answers:
        diff = diff_map.get(a.get('difficulty'), 'easy')
        by_diff[diff]['total'] += 1
        if a['correct']:
            by_diff[diff]['correct'] += 1
        cat = a.get('category', 'other')
        if cat not in by_cat:
            by_cat[cat] = {'correct': 0, 'total': 0}
        by_cat[cat]['total'] += 1
        if a['correct']:
            by_cat[cat]['correct'] += 1
    # Find weak areas
    weak_areas = [cat for cat, v in by_cat.items() if v['correct'] / v['total'] < 0.6]
    suggestions = []
    if weak_areas:
        suggestions.append('Focus on improving: ' + ', '.join(weak_areas))
    if by_diff['hard']['correct'] / by_diff['hard']['total'] if by_diff['hard']['total'] else 1 < 0.5:
        suggestions.append('Practice more hard-level questions.')
    if avg_time > 60:
        suggestions.append('Try to answer questions faster to improve your average time.')

    # Store verification status in file with username and email
    percent = (correct / total) * 100 if total else 0
    student_id = getattr(session, 'student_id', 'Unknown')
    user_email = getattr(session, 'user_email', 'Unknown')
    
    # Create detailed result line with timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"Timestamp: {timestamp}, Username: {student_id}, Email: {user_email}, Score: {percent:.2f}%, Correct: {correct}/{total}\n"
    
    if percent > 65:
        # Store high performers in verified.txt
        with open('verified.txt', 'a', encoding='utf-8') as vf:
            vf.write(line)
    else:
        # Store low performers in Notverified.txt
        with open('Notverified.txt', 'a', encoding='utf-8') as nvf:
            nvf.write(line)

    # Build a question lookup for all difficulties
    question_lookup = {}
    for diff_list in ENHANCED_QUESTIONS.values():
        for q in diff_list:
            question_lookup[q['id']] = q

    # Per-question review list
    review = []
    for a in session.answers:
        q = question_lookup.get(a['question_id'])
        if not q:
            continue
        review.append({
            'question_id': a['question_id'],
            'question': q['question'],
            'options': q['options'],
            'selected': a['selected'],
            'correct_option': q['solution'],
            'is_correct': a['correct'],
            'category': q.get('category', ''),
            'difficulty': q.get('type', 1),
            'time_taken': a.get('time_taken', 0)
        })

    return jsonify({
        'total': total,
        'correct': correct,
        'incorrect': incorrect,
        'avg_time': avg_time,
        'total_time': total_time,
        'by_difficulty': by_diff,
        'by_category': by_cat,
        'suggestions': suggestions,
        'review': review
    })

@app.route('/exam_analysis/<session_id>')
def exam_analysis(session_id):
    session = active_sessions.get(session_id)
    if not session:
        return abort(404)
    total = len(session.answers)
    correct = sum(1 for a in session.answers if a['correct'])
    percent = (correct / total) * 100 if total else 0
    
    # Store results in text files for analysis
    student_id = getattr(session, 'student_id', 'Unknown')
    user_email = getattr(session, 'user_email', 'Unknown')
    
    # Create detailed result line with timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"Timestamp: {timestamp}, Username: {student_id}, Email: {user_email}, Score: {percent:.2f}%, Correct: {correct}/{total}\n"
    
    if percent > 65:
        # Store high performers in verified.txt
        with open('verified.txt', 'a', encoding='utf-8') as vf:
            vf.write(line)
    else:
        # Store low performers in Notverified.txt
        with open('Notverified.txt', 'a', encoding='utf-8') as nvf:
            nvf.write(line)
    
    # You can add more analysis data here as needed
    return render_template('exam_analysis.html', score=percent, correct=correct, total=total, show_popup=percent <= 80)

@app.errorhandler(404)
def page_not_found(e):
    return make_response(render_template('404.html'), 404)

@app.route('/api/validate_aadhaar', methods=['POST'])
def validate_aadhaar():
    data = request.get_json()
    aadhaar_number = data.get('aadhaar_number')
    # For demo: consider any 12-digit number as valid
    is_valid = aadhaar_number and len(aadhaar_number) == 12 and aadhaar_number.isdigit()
    return jsonify({'valid': is_valid})

# User management functions
def load_user_data():
    """Load user data from JSON file"""
    try:
        with open('user_data.json', 'r') as f:
            content = f.read().strip()
            if not content:  # File is empty
                return {"users": []}
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"users": []}

def save_user_data(user_data):
    """Save user data to JSON file"""
    with open('user_data.json', 'w') as f:
        json.dump(user_data, f, indent=2)

def load_blocked_users():
    """Load blocked users data from JSON file"""
    try:
        with open('blocked_users.json', 'r') as f:
            content = f.read().strip()
            if not content:  # File is empty
                return {"blocked_users": []}
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"blocked_users": []}

def save_blocked_users(blocked_data):
    """Save blocked users data to JSON file"""
    with open('blocked_users.json', 'w') as f:
        json.dump(blocked_data, f, indent=2)

def is_user_blocked(email, username):
    """Check if user is blocked"""
    blocked_data = load_blocked_users()
    return any(user['email'] == email or user['username'] == username 
               for user in blocked_data['blocked_users'])

def block_user(email, username, reason="Cheating violation"):
    """Block a user and add to blocked users list"""
    blocked_data = load_blocked_users()
    blocked_user = {
        'email': email,
        'username': username,
        'blocked_at': datetime.now().isoformat(),
        'reason': reason
    }
    blocked_data['blocked_users'].append(blocked_user)
    save_blocked_users(blocked_data)
    return blocked_user

def user_exists(email, username):
    """Check if user exists by email or username"""
    user_data = load_user_data()
    return any(user['email'] == email or user['username'] == username 
               for user in user_data['users'])

def check_email_exists(email):
    """Check if email already exists"""
    user_data = load_user_data()
    return any(user['email'] == email for user in user_data['users'])

def check_username_exists(username):
    """Check if username already exists"""
    user_data = load_user_data()
    return any(user['username'] == username for user in user_data['users'])

def validate_user_login(email, username):
    """Validate user login credentials"""
    user_data = load_user_data()
    return any(user['email'] == email and user['username'] == username 
               for user in user_data['users'])

def add_user(email, username):
    """Add new user to the system"""
    user_data = load_user_data()
    new_user = {
        'email': email,
        'username': username,
        'registeredAt': datetime.now().isoformat()
    }
    user_data['users'].append(new_user)
    save_user_data(user_data)
    return new_user

@app.route('/api/register', methods=['POST'])
def register_user():
    """Register a new user"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        username = data.get('username', '').strip()
        
        if not email or not username:
            return jsonify({'success': False, 'message': 'Email and username are required'}), 400
        
        # Check if user is blocked
        if is_user_blocked(email, username):
            return jsonify({'success': False, 'message': 'This account has been blocked due to cheating violations. You are not allowed to register again.'}), 403
        
        # Check if email already exists
        if check_email_exists(email):
            return jsonify({'success': False, 'message': f'Email "{email}" is already registered. Please use a different email or login with existing credentials.'}), 409
        
        # Check if username already exists
        if check_username_exists(username):
            return jsonify({'success': False, 'message': f'Username "{username}" is already taken. Please choose a different username.'}), 409
        
        new_user = add_user(email, username)
        return jsonify({
            'success': True, 
            'message': 'Registration successful',
            'user': new_user
        }), 201
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Registration failed: {str(e)}'}), 500

@app.route('/api/login', methods=['POST'])
def login_user():
    """Login user"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        username = data.get('username', '').strip()
        
        if not email or not username:
            return jsonify({'success': False, 'message': 'Email and username are required'}), 400
        
        # Check if user is blocked
        if is_user_blocked(email, username):
            return jsonify({'success': False, 'message': 'This account has been blocked due to cheating violations. You are not allowed to access the exam system.'}), 403
        
        if not validate_user_login(email, username):
            return jsonify({'success': False, 'message': 'Invalid email or username'}), 401
        
        return jsonify({
            'success': True, 
            'message': 'Login successful'
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Login failed: {str(e)}'}), 500

@app.route('/api/users', methods=['GET'])
def get_users():
    """Get all registered users (for admin purposes)"""
    try:
        user_data = load_user_data()
        return jsonify({
            'success': True,
            'users': user_data['users']
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to load users: {str(e)}'}), 500

@app.route('/api/check_availability', methods=['POST'])
def check_availability():
    """Check if email or username is available"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        username = data.get('username', '').strip()
        
        email_exists = check_email_exists(email) if email else False
        username_exists = check_username_exists(username) if username else False
        
        return jsonify({
            'success': True,
            'email_available': not email_exists,
            'username_available': not username_exists,
            'email_exists': email_exists,
            'username_exists': username_exists
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Check failed: {str(e)}'}), 500

@app.route('/api/blocked_users', methods=['GET'])
def get_blocked_users():
    """Get all blocked users (for admin purposes)"""
    try:
        blocked_data = load_blocked_users()
        return jsonify({
            'success': True,
            'blocked_users': blocked_data['blocked_users']
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to load blocked users: {str(e)}'}), 500

@app.route('/api/clear_users', methods=['POST'])
def clear_users():
    """Clear all user data from server"""
    try:
        # Reset user_data.json to empty state
        empty_user_data = {"users": []}
        save_user_data(empty_user_data)
        
        return jsonify({
            'success': True,
            'message': 'All server-side user data has been cleared successfully'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Failed to clear server data: {str(e)}'
        }), 500

@app.route('/api/clear_blocked_users', methods=['POST'])
def clear_blocked_users():
    """Clear all blocked users data from server"""
    try:
        # Reset blocked_users.json to empty state
        empty_blocked_data = {"blocked_users": []}
        save_blocked_users(empty_blocked_data)
        
        return jsonify({
            'success': True,
            'message': 'All blocked users data has been cleared successfully'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Failed to clear blocked users data: {str(e)}'
        }), 500

@app.route('/api/check_blocked_status', methods=['POST'])
def check_blocked_status():
    """Check if a user is blocked"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        username = data.get('username', '').strip()
        
        if not email or not username:
            return jsonify({'success': False, 'message': 'Email and username are required'}), 400
        
        is_blocked = is_user_blocked(email, username)
        
        return jsonify({
            'success': True,
            'is_blocked': is_blocked,
            'message': 'User is blocked' if is_blocked else 'User is not blocked'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Failed to check blocked status: {str(e)}'
        }), 500

@app.route('/api/block_user', methods=['POST'])
def api_block_user():
    """Block a user due to cheating violations"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        username = data.get('username', '').strip()
        reason = data.get('reason', 'Cheating violation').strip()
        
        if not email or not username:
            return jsonify({'success': False, 'message': 'Email and username are required'}), 400
        
        # Block the user
        blocked_user = block_user(email, username, reason)
        
        return jsonify({
            'success': True,
            'message': f'User {username} has been blocked due to {reason}',
            'blocked_user': blocked_user
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Failed to block user: {str(e)}'
        }), 500

@app.route('/cheating_violation')
def cheating_violation():
    """Display cheating violation page"""
    return render_template('cheating_violation.html')

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)