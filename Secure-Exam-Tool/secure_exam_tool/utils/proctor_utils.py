import cv2
import mediapipe as mp
import numpy as np
import base64
from PIL import Image
import io
import json
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProctorUtils:
    def __init__(self):
        self.mp_face_detection = mp.solutions.face_detection
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles
        
        # Initialize face detection
        self.face_detection = self.mp_face_detection.FaceDetection(
            model_selection=0, min_detection_confidence=0.5
        )
        
        # Initialize face mesh for gaze tracking
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        
        self.eye_landmarks = {
            'left_eye': [362, 385, 387, 263, 373, 380],
            'right_eye': [33, 7, 163, 144, 145, 153]
        }
        
    def process_frame(self, frame):
        """Process a frame for face detection and gaze tracking"""
        try:
            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Process for face detection
            face_results = self.face_detection.process(rgb_frame)
            
            # Process for face mesh (gaze tracking)
            mesh_results = self.face_mesh.process(rgb_frame)
            
            return {
                'face_detected': len(face_results.detections) > 0,
                'gaze_data': self.extract_gaze_data(mesh_results, frame.shape),
                'face_confidence': self.get_face_confidence(face_results),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            return {
                'face_detected': False,
                'gaze_data': None,
                'face_confidence': 0.0,
                'timestamp': datetime.now().isoformat()
            }
    
    def extract_gaze_data(self, mesh_results, frame_shape):
        """Extract gaze direction from face mesh results"""
        if not mesh_results.multi_face_landmarks:
            return None
            
        try:
            landmarks = mesh_results.multi_face_landmarks[0]
            height, width = frame_shape[:2]
            
            # Get eye landmarks
            left_eye_center = self.get_eye_center(landmarks, self.eye_landmarks['left_eye'], width, height)
            right_eye_center = self.get_eye_center(landmarks, self.eye_landmarks['right_eye'], width, height)
            
            # Calculate gaze direction (simplified)
            gaze_direction = self.calculate_gaze_direction(left_eye_center, right_eye_center, width, height)
            
            return {
                'left_eye_center': left_eye_center,
                'right_eye_center': right_eye_center,
                'gaze_direction': gaze_direction,
                'gaze_confidence': self.calculate_gaze_confidence(landmarks)
            }
            
        except Exception as e:
            logger.error(f"Error extracting gaze data: {e}")
            return None
    
    def get_eye_center(self, landmarks, eye_indices, width, height):
        """Calculate the center of an eye"""
        x_coords = [landmarks.landmark[idx].x * width for idx in eye_indices]
        y_coords = [landmarks.landmark[idx].y * height for idx in eye_indices]
        
        center_x = sum(x_coords) / len(x_coords)
        center_y = sum(y_coords) / len(y_coords)
        
        return (int(center_x), int(center_y))
    
    def calculate_gaze_direction(self, left_eye, right_eye, width, height):
        """Calculate gaze direction based on eye positions"""
        if not left_eye or not right_eye:
            return 'unknown'
            
        # Calculate center point between eyes
        center_x = (left_eye[0] + right_eye[0]) / 2
        center_y = (left_eye[1] + right_eye[1]) / 2
        
        # Determine gaze direction based on position relative to screen center
        screen_center_x = width / 2
        screen_center_y = height / 2
        
        # Calculate distance from screen center
        distance_x = abs(center_x - screen_center_x)
        distance_y = abs(center_y - screen_center_y)
        
        # Define thresholds for gaze direction
        threshold_x = width * 0.3
        threshold_y = height * 0.3
        
        if distance_x > threshold_x:
            if center_x < screen_center_x:
                return 'left'
            else:
                return 'right'
        elif distance_y > threshold_y:
            if center_y < screen_center_y:
                return 'up'
            else:
                return 'down'
        else:
            return 'center'
    
    def calculate_gaze_confidence(self, landmarks):
        """Calculate confidence in gaze tracking"""
        # This is a simplified confidence calculation
        # In a real implementation, you would use more sophisticated methods
        return 0.8  # Placeholder value
    
    def get_face_confidence(self, face_results):
        """Get confidence score for face detection"""
        if not face_results.detections:
            return 0.0
        
        # Return the highest confidence score
        confidences = [detection.score[0] for detection in face_results.detections]
        return max(confidences) if confidences else 0.0
    
    def detect_violations(self, proctor_data, session_config):
        """Detect violations based on proctor data"""
        violations = []
        
        # Check face detection
        if not proctor_data.get('face_detected', False):
            violations.append({
                'type': 'face_not_detected',
                'severity': 'high',
                'message': 'Face not detected in camera view'
            })
        
        # Check gaze violations
        gaze_data = proctor_data.get('gaze_data')
        if gaze_data and gaze_data.get('gaze_direction') not in ['center', 'unknown']:
            violations.append({
                'type': 'gaze_violation',
                'severity': 'medium',
                'message': f'Gaze direction: {gaze_data.get("gaze_direction")}'
            })
        
        # Check face confidence
        face_confidence = proctor_data.get('face_confidence', 0.0)
        if face_confidence < 0.5:
            violations.append({
                'type': 'low_face_confidence',
                'severity': 'medium',
                'message': f'Low face detection confidence: {face_confidence:.2f}'
            })
        
        return violations
    
    def encode_frame(self, frame):
        """Encode frame to base64 for transmission"""
        try:
            # Convert frame to JPEG
            _, buffer = cv2.imencode('.jpg', frame)
            # Encode to base64
            encoded_frame = base64.b64encode(buffer).decode('utf-8')
            return encoded_frame
        except Exception as e:
            logger.error(f"Error encoding frame: {e}")
            return None
    
    def decode_frame(self, encoded_frame):
        """Decode base64 frame back to numpy array"""
        try:
            # Decode from base64
            frame_data = base64.b64decode(encoded_frame)
            # Convert to numpy array
            frame_array = np.frombuffer(frame_data, dtype=np.uint8)
            # Decode image
            frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
            return frame
        except Exception as e:
            logger.error(f"Error decoding frame: {e}")
            return None
    
    def create_session_log(self, session_id, student_id):
        """Create a log entry for the session"""
        return {
            'session_id': session_id,
            'student_id': student_id,
            'start_time': datetime.now().isoformat(),
            'status': 'active',
            'violations': [],
            'warnings': {
                'tab_switch': 0,
                'gaze_violation': 0,
                'face_not_detected': 0
            }
        }
    
    def update_session_log(self, session_log, violation_type, message):
        """Update session log with new violation"""
        session_log['violations'].append({
            'type': violation_type,
            'message': message,
            'timestamp': datetime.now().isoformat()
        })
        
        if violation_type in session_log['warnings']:
            session_log['warnings'][violation_type] += 1
        
        return session_log
    
    def should_terminate_session(self, session_log, max_warnings):
        """Check if session should be terminated based on warnings"""
        for warning_type, count in session_log['warnings'].items():
            if count >= max_warnings.get(warning_type, 5):
                return True, f"Maximum {warning_type} warnings exceeded"
        
        return False, None
    
    def cleanup(self):
        """Cleanup resources"""
        if hasattr(self, 'face_detection'):
            self.face_detection.close()
        if hasattr(self, 'face_mesh'):
            self.face_mesh.close()

# Utility functions for session management
def create_session_id():
    """Create a unique session ID"""
    return f"session_{int(datetime.now().timestamp())}"

def validate_session(session_id, active_sessions):
    """Validate if a session exists and is active"""
    return session_id in active_sessions and active_sessions[session_id].is_active

def format_time_elapsed(start_time):
    """Format elapsed time since start"""
    elapsed = datetime.now() - start_time
    hours = elapsed.seconds // 3600
    minutes = (elapsed.seconds % 3600) // 60
    seconds = elapsed.seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def save_session_data(session_data, filename=None):
    """Save session data to file"""
    if filename is None:
        filename = f"session_{session_data['session_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    try:
        with open(filename, 'w') as f:
            json.dump(session_data, f, indent=2, default=str)
        logger.info(f"Session data saved to {filename}")
        return True
    except Exception as e:
        logger.error(f"Error saving session data: {e}")
        return False 