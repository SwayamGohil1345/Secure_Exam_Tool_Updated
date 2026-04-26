import cv2
import mediapipe as mp
import numpy as np
import base64
from datetime import datetime
import logging
import time

# Configure logging for better debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GazeDetector:
    def __init__(self):
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        
        # Eye landmark indices for MediaPipe face mesh
        self.left_eye_landmarks = [362, 385, 387, 263, 373, 380]
        self.right_eye_landmarks = [33, 7, 163, 144, 145, 153]
        
        # Iris landmarks for precise gaze detection
        self.left_iris_landmarks = [468, 469, 470, 471, 472]
        self.right_iris_landmarks = [473, 474, 475, 476, 477]
        
        # Lip landmarks for movement detection - Updated MediaPipe indices
        self.upper_lip_landmarks = [61, 84, 17, 314, 405, 320, 307, 375, 321, 308, 324, 318]
        self.lower_lip_landmarks = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308]
        
        # Additional lip landmarks for better detection
        self.lip_corner_landmarks = [61, 84, 17, 314, 405, 320, 307, 375, 321, 308, 324, 318, 78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308]
        
        # Screen center reference
        self.screen_center = None
        
        # Tracking variables for cheating detection
        self.eye_direction_start = None
        self.current_eye_direction = None
        self.lip_movement_start = None
        self.last_lip_position = None
        
        # Thresholds for detection
        self.cheating_threshold = 5.0  # 5 seconds for cheating detection
        self.lip_movement_threshold = 0.015  # Reduced threshold for better lip movement detection
        self.lip_movement_cooldown = 2.0  # Cooldown period between lip movement warnings 
    
    def process_frame(self, frame_data):
        """Process frame data and return simplified detection information"""
        try:
            # Decode base64 frame
            frame = self.decode_frame(frame_data)
            if frame is None:
                return self.get_default_response()
            
            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width = frame.shape[:2]
            
            # Update screen center
            self.screen_center = (width // 2, height // 2)
            
            # Process with MediaPipe
            results = self.face_mesh.process(rgb_frame)
            
            # Debug: Log face detection results
            if results.multi_face_landmarks:
                logger.info(f"Face detected with {len(results.multi_face_landmarks)} landmarks")
            else:
                logger.warning("No face landmarks detected in frame")
                return self.get_default_response(face_detected=False)
            
            # Get the first face
            face_landmarks = results.multi_face_landmarks[0]
            
            # Extract detection data
            detection_data = self.extract_detection_data(face_landmarks, width, height)
            
            return {
                'face_detected': True,
                'detection_data': detection_data,
                'face_confidence': 0.9,
                'timestamp': datetime.now().isoformat(),
                'frame_size': {'width': width, 'height': height}
            }
            
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            return self.get_default_response()
    
    def extract_detection_data(self, landmarks, width, height):
        """Extract simplified detection data for cheating prevention"""
        try:
            # Get eye centers and iris positions
            left_eye_center = self.get_eye_center(landmarks, self.left_eye_landmarks, width, height)
            right_eye_center = self.get_eye_center(landmarks, self.right_eye_landmarks, width, height)
            left_iris_center = self.get_iris_center(landmarks, self.left_iris_landmarks, width, height)
            right_iris_center = self.get_iris_center(landmarks, self.right_iris_landmarks, width, height)
            
            # Validate eye data
            if not left_eye_center or not right_eye_center:
                return None
            
            # Detect precise eye direction
            eye_direction = self.detect_precise_eye_direction(
                left_eye_center, right_eye_center, 
                left_iris_center, right_iris_center,
                width, height
            )
            
            # Check for lip movement
            lip_movement = self.detect_lip_movement(landmarks, width, height)
            
            # Debug lip movement status
            if lip_movement:
                logger.info(f"Lip movement detected - Status: {self.get_lip_movement_status()}")
            
            # Track eye direction for cheating detection
            self.track_eye_direction(eye_direction)
            
            # Check if cheating behavior detected
            cheating_detected = self.check_cheating_behavior()
            
            return {
                'eye_direction': eye_direction,
                'lip_movement': lip_movement,
                'cheating_detected': cheating_detected,
                'current_direction_duration': self.get_current_direction_duration(),
                'is_looking_at_screen': eye_direction in ['center', 'slight_left', 'slight_right', 'slight_up', 'slight_down']
            }
            
        except Exception as e:
            logger.error(f"Error extracting detection data: {e}")
            return None 
    
    def detect_precise_eye_direction(self, left_eye, right_eye, left_iris, right_iris, width, height):
        """Detect precise eye direction for cheating detection"""
        if not left_eye or not right_eye:
            return 'unknown'
        
        # Calculate center point between eyes
        eye_center_x = (left_eye[0] + right_eye[0]) / 2
        eye_center_y = (left_eye[1] + right_eye[1]) / 2
        
        # Calculate iris center if available
        if left_iris and right_iris:
            iris_center_x = (left_iris[0] + right_iris[0]) / 2
            iris_center_y = (left_iris[1] + right_iris[1]) / 2
        else:
            iris_center_x = eye_center_x
            iris_center_y = eye_center_y
        
        # Screen center
        screen_center_x = width / 2
        screen_center_y = height / 2
        
        # Calculate distances from screen center
        distance_x = iris_center_x - screen_center_x
        distance_y = iris_center_y - screen_center_y
        
        # Normalize distances by screen size
        normalized_x = distance_x / (width / 2)
        normalized_y = distance_y / (height / 2)
        
        # PRECISE thresholds for cheating detection
        threshold_slight = 0.12    # Slight movements (normal)
        threshold_moderate = 0.20  # Moderate movements (suspicious)
        threshold_large = 0.30     # Large movements (likely cheating)
        
        # Determine horizontal direction
        if abs(normalized_x) < threshold_slight:
            horizontal = 'center'
        elif abs(normalized_x) < threshold_moderate:
            horizontal = 'slight_left' if normalized_x < 0 else 'slight_right'
        elif abs(normalized_x) < threshold_large:
            horizontal = 'left' if normalized_x < 0 else 'right'
        else:
            horizontal = 'far_left' if normalized_x < 0 else 'far_right'
        
        # Determine vertical direction
        if abs(normalized_y) < threshold_slight:
            vertical = 'center'
        elif abs(normalized_y) < threshold_moderate:
            vertical = 'slight_up' if normalized_y < 0 else 'slight_down'
        elif abs(normalized_y) < threshold_large:
            vertical = 'up' if normalized_y < 0 else 'down'
        else:
            vertical = 'far_up' if normalized_y < 0 else 'far_down'
        
        # Return combined direction
        if horizontal == 'center' and vertical == 'center':
            return 'center'
        elif horizontal == 'center':
            return vertical
        elif vertical == 'center':
            return horizontal
        else:
            return f"{horizontal}_{vertical}"
    
    def detect_lip_movement(self, landmarks, width, height):
        """Detect lip movement for talking/whispering detection"""
        try:
            current_time = time.time()
            
            # Check cooldown period
            if (self.lip_movement_start is not None and 
                current_time - self.lip_movement_start < self.lip_movement_cooldown):
                return False
            
            # Get current lip position using all lip landmarks
            lip_points = []
            
            # Extract all lip landmarks
            for idx in self.lip_corner_landmarks:
                if idx < len(landmarks.landmark):
                    landmark = landmarks.landmark[idx]
                    lip_points.append((landmark.x * width, landmark.y * height))
            
            # Debug: Log lip landmark extraction
            logger.debug(f"Extracted {len(lip_points)} lip landmarks from {len(self.lip_corner_landmarks)} total indices")
            
            if len(lip_points) < 5:  # Need minimum points for detection
                logger.warning(f"Insufficient lip points: {len(lip_points)} < 5 required")
                return False
            
            # Calculate current lip center
            current_lip_center = self.calculate_lip_center_from_points(lip_points)
            
            # Check for movement
            if self.last_lip_position is not None:
                movement_distance = np.sqrt(
                    (current_lip_center[0] - self.last_lip_position[0])**2 +
                    (current_lip_center[1] - self.last_lip_position[1])**2
                )
                
                # Normalize by screen size
                normalized_movement = movement_distance / np.sqrt(width**2 + height**2)
                
                # Debug logging
                if normalized_movement > 0.01:  # Log significant movements
                    logger.debug(f"Lip movement detected: {normalized_movement:.4f} (threshold: {self.lip_movement_threshold:.4f})")
                
                if normalized_movement > self.lip_movement_threshold:
                    # Lip movement detected
                    if self.lip_movement_start is None:
                        self.lip_movement_start = current_time
                        logger.info(f"Lip movement started at {current_time}")
                    return True
            
            # Update last position
            self.last_lip_position = current_lip_center
            return False
            
        except Exception as e:
            logger.error(f"Error detecting lip movement: {e}")
            return False
    
    def calculate_lip_center_from_points(self, lip_points):
        """Calculate the center point of the lips from all lip landmarks"""
        if not lip_points or len(lip_points) < 3:
            return (0, 0)
        
        # Calculate center
        center_x = sum(point[0] for point in lip_points) / len(lip_points)
        center_y = sum(point[1] for point in lip_points) / len(lip_points)
        
        return (center_x, center_y)
    
    def calculate_lip_center(self, upper_points, lower_points):
        """Calculate the center point of the lips (legacy method)"""
        if not upper_points or not lower_points:
            return (0, 0)
        
        # Combine all lip points
        all_points = upper_points + lower_points
        
        # Calculate center
        center_x = sum(point[0] for point in all_points) / len(all_points)
        center_y = sum(point[1] for point in all_points) / len(all_points)
        
        return (center_x, center_y)
    
    def track_eye_direction(self, new_direction):
        """Track eye direction for cheating detection"""
        current_time = time.time()
        
        if new_direction != self.current_eye_direction:
            # Direction changed
            if self.eye_direction_start is not None:
                # Check if previous direction was held long enough to be suspicious
                duration = current_time - self.eye_direction_start
                if duration >= self.cheating_threshold:
                    logger.warning(f"Suspicious eye direction detected: {self.current_eye_direction} for {duration:.1f}s")
            
            # Start tracking new direction
            self.current_eye_direction = new_direction
            self.eye_direction_start = current_time
        else:
            # Same direction, continue tracking
            if self.eye_direction_start is None:
                self.eye_direction_start = current_time
    
    def check_cheating_behavior(self):
        """Check if current eye direction indicates cheating"""
        if self.eye_direction_start is None or self.current_eye_direction is None:
            return False
        
        current_time = time.time()
        duration = current_time - self.eye_direction_start
        
        # Check for suspicious directions held for 5+ seconds
        suspicious_directions = ['left', 'right', 'up', 'down', 'far_left', 'far_right', 'far_up', 'far_down']
        
        if self.current_eye_direction in suspicious_directions and duration >= self.cheating_threshold:
            return True
        
        return False
    
    def get_current_direction_duration(self):
        """Get duration of current eye direction"""
        if self.eye_direction_start is None:
            return 0.0
        
        return time.time() - self.eye_direction_start
    
    def reset_lip_tracking(self):
        """Reset lip movement tracking"""
        self.lip_movement_start = None
        self.last_lip_position = None
        logger.info("Lip movement tracking reset")
    
    def get_lip_movement_status(self):
        """Get current lip movement status for debugging"""
        if self.lip_movement_start is None:
            return "No lip movement detected"
        
        duration = time.time() - self.lip_movement_start
        if duration < self.lip_movement_cooldown:
            return f"Lip movement in cooldown ({self.lip_movement_cooldown - duration:.1f}s remaining)"
        else:
            return f"Lip movement detected for {duration:.1f}s" 
    
    def get_eye_center(self, landmarks, eye_indices, width, height):
        """Calculate the center of an eye"""
        try:
            x_coords = [landmarks.landmark[idx].x * width for idx in eye_indices]
            y_coords = [landmarks.landmark[idx].y * height for idx in eye_indices]
            
            center_x = sum(x_coords) / len(x_coords)
            center_y = sum(y_coords) / len(y_coords)
            
            return (int(center_x), int(center_y))
        except Exception as e:
            logger.error(f"Error calculating eye center: {e}")
            return None
    
    def get_iris_center(self, landmarks, iris_indices, width, height):
        """Calculate the center of the iris"""
        try:
            x_coords = [landmarks.landmark[idx].x * width for idx in iris_indices]
            y_coords = [landmarks.landmark[idx].y * height for idx in iris_indices]
            
            center_x = sum(x_coords) / len(x_coords)
            center_y = sum(y_coords) / len(y_coords)
            
            return (int(center_x), int(center_y))
        except Exception as e:
            logger.error(f"Error calculating iris center: {e}")
            return None
    
    def decode_frame(self, frame_data):
        """Decode base64 frame data to numpy array"""
        try:
            frame_bytes = base64.b64decode(frame_data)
            frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
            frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
            return frame
        except Exception as e:
            logger.error(f"Error decoding frame: {e}")
            return None
    
    def get_default_response(self, face_detected=False):
        """Return default response when face is not detected or error occurs"""
        return {
            'face_detected': face_detected,
            'detection_data': None,
            'face_confidence': 0.0,
            'timestamp': datetime.now().isoformat(),
            'frame_size': None
        }
    
    def cleanup(self):
        """Cleanup resources"""
        if hasattr(self, 'face_mesh'):
            self.face_mesh.close() 