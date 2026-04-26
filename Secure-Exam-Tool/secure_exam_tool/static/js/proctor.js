// Advanced Proctoring System
class ProctorSystem {
    constructor(sessionId) {
        this.sessionId = sessionId;
        this.isActive = true;
        this.camera = null;
        this.faceDetector = null;
        this.gazeTracker = null;
        this.warnings = {
            tabSwitch: 0,
            gazeViolation: 0,
            faceNotDetected: 0
        };
        this.maxWarnings = {
            tabSwitch: 5,
            gazeViolation: 10,
            faceNotDetected: 3
        };
        this.socket = io();
        
        // Voice warning system
        this.voiceEnabled = true;
        this.speechSynthesis = window.speechSynthesis;
        this.voiceQueue = [];
        this.isSpeaking = false;
        this.voiceVolume = 0.8; // Default volume
        
        this.init();
    }

    async init() {
        await this.initializeCamera();
        this.setupEventListeners();
        this.startMonitoring();
        this.initializeVoiceSystem();
    }

    async initializeCamera() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: 640,
                    height: 480,
                    facingMode: 'user'
                }
            });
            
            this.camera = stream;
            const videoElement = document.getElementById('cameraFeed');
            if (videoElement) {
                videoElement.srcObject = stream;
            }
            
            // Initialize face detection
            this.initializeFaceDetection();
            
        } catch (error) {
            console.error('Camera initialization failed:', error);
            this.showWarning('Camera access is required for this exam!', 'danger');
        }
    }

    initializeFaceDetection() {
        // Using MediaPipe for face detection
        if (typeof mp !== 'undefined') {
            this.faceDetector = new mp.FaceDetection({
                modelSelection: 0,
                minDetectionConfidence: 0.5
            });
            
            this.faceDetector.setOptions({
                modelSelection: 0,
                minDetectionConfidence: 0.5
            });
            
            this.faceDetector.onResults((results) => {
                this.handleFaceDetectionResults(results);
            });
        }
    }

    handleFaceDetectionResults(results) {
        if (!this.isActive) return;
        
        const faceStatus = document.getElementById('faceStatus');
        if (results.detections.length > 0) {
            faceStatus.textContent = '✅ Face Detected';
            faceStatus.style.color = '#28a745';
            this.warnings.faceNotDetected = 0;
        } else {
            faceStatus.textContent = '❌ Face Not Detected';
            faceStatus.style.color = '#dc3545';
            this.warnings.faceNotDetected++;
            
            if (this.warnings.faceNotDetected >= this.maxWarnings.faceNotDetected) {
                this.terminateSession('Face not detected for extended period');
            } else {
                // Voice warning for face not detected
                const warningMessage = this.getWarningMessage('face_not_visible', { count: this.warnings.faceNotDetected });
                const priority = this.warnings.faceNotDetected >= 2 ? 'high' : 'normal';
                this.speakWarning(warningMessage, priority);
            }
        }
    }

    setupEventListeners() {
        // Tab switching detection
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && this.isActive) {
                this.handleTabSwitch();
            }
        });

        // Window focus detection
        window.addEventListener('blur', () => {
            if (this.isActive) {
                this.handleTabSwitch();
            }
        });

        // Prevent right-click
        document.addEventListener('contextmenu', (e) => e.preventDefault());

        // Prevent keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.altKey || e.metaKey) && this.isActive) {
                e.preventDefault();
                this.showWarning('Keyboard shortcuts are disabled during the exam', 'warning');
            }
        });

        // Prevent copy-paste
        document.addEventListener('copy', (e) => {
            if (this.isActive) {
                e.preventDefault();
                this.showWarning('Copying is disabled during the exam', 'warning');
            }
        });

        document.addEventListener('paste', (e) => {
            if (this.isActive) {
                e.preventDefault();
                this.showWarning('Pasting is disabled during the exam', 'warning');
            }
        });
    }

    handleTabSwitch() {
        if (!this.isActive) return;
        
        this.warnings.tabSwitch++;
        this.updateWarningDisplay();
        
        this.socket.emit('tab_switch_detected', { session_id: this.sessionId });
        
        if (this.warnings.tabSwitch >= this.maxWarnings.tabSwitch) {
            this.terminateSession('Maximum tab switch warnings exceeded');
        } else {
            this.showWarning(`Tab switching detected! Warning ${this.warnings.tabSwitch}/${this.maxWarnings.tabSwitch}`, 'warning');
            
            // Voice warning for tab switching
            const warningMessage = this.getWarningMessage('tab_switch', { count: this.warnings.tabSwitch });
            const priority = this.warnings.tabSwitch >= 3 ? 'high' : 'normal';
            this.speakWarning(warningMessage, priority);
        }
    }

    handleGazeViolation() {
        if (!this.isActive) return;
        
        this.warnings.gazeViolation++;
        this.updateWarningDisplay();
        
        // Calculate duration looking away
        const duration = this.gazeAwayStartTime ? Math.round((Date.now() - this.gazeAwayStartTime) / 1000) : 0;
        
        this.socket.emit('gaze_violation', { 
            session_id: this.sessionId,
            duration: duration
        });
        
        if (this.warnings.gazeViolation >= this.maxWarnings.gazeViolation) {
            this.terminateSession('Maximum gaze violation warnings exceeded');
        } else {
            this.showWarning(`Gaze violation detected! You looked away for ${duration}s. Warning ${this.warnings.gazeViolation}/${this.maxWarnings.gazeViolation}`, 'warning');
            
            // Voice warning for gaze violations
            const warningMessage = this.getWarningMessage('gaze_violation', { duration: duration });
            const priority = duration > 60 ? 'high' : duration > 30 ? 'moderate' : 'normal';
            this.speakWarning(warningMessage, priority);
        }
    }

    updateWarningDisplay() {
        const tabWarningsElement = document.getElementById('tabWarnings');
        const gazeWarningsElement = document.getElementById('gazeWarnings');
        
        if (tabWarningsElement) {
            tabWarningsElement.textContent = `${this.warnings.tabSwitch}/${this.maxWarnings.tabSwitch}`;
        }
        
        if (gazeWarningsElement) {
            gazeWarningsElement.textContent = `${this.warnings.gazeViolation}/${this.maxWarnings.gazeViolation}`;
        }
    }

    startMonitoring() {
        // Enhanced gaze tracking with real-time detection
        let gazeAwayStartTime = null;
        let gazeViolationTimer = null;
        
        // Send camera frames to backend for gaze detection
        this.startFrameCapture();
        
        // Heartbeat
        setInterval(() => {
            if (this.isActive) {
                this.socket.emit('heartbeat', { session_id: this.sessionId });
            }
        }, 30000);
    }
    
    startFrameCapture() {
        // Capture frames from camera and send to backend for gaze detection
        if (!this.camera) return;
        
        const videoElement = document.getElementById('cameraFeed');
        if (!videoElement) return;
        
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        canvas.width = 640;
        canvas.height = 480;
        
        const captureFrame = () => {
            if (!this.isActive || document.hidden) {
                setTimeout(captureFrame, 100);
                return;
            }
            
            try {
                context.drawImage(videoElement, 0, 0, canvas.width, canvas.height);
                const frameData = canvas.toDataURL('image/jpeg', 0.8);
                
                // Send frame to backend for gaze detection
                this.socket.emit('process_frame', {
                    session_id: this.sessionId,
                    frame_data: frameData.split(',')[1] // Remove data:image/jpeg;base64, prefix
                });
                
                setTimeout(captureFrame, 200); // Capture every 200ms for smooth tracking
            } catch (error) {
                console.error('Error capturing frame:', error);
                setTimeout(captureFrame, 500);
            }
        };
        
        // Start frame capture when video is ready
        videoElement.addEventListener('loadeddata', () => {
            captureFrame();
        });
        
        // Set up socket event listeners for gaze updates
        this.socket.on('gaze_update', (data) => {
            this.handleGazeUpdate(data);
        });
        
        // Unified warning handler for all types of warnings
        this.socket.on('warning', (data) => {
            this.handleUnifiedWarning(data);
        });
        
        // Legacy handlers for backward compatibility
        this.socket.on('gaze_warning', (data) => {
            this.handleGazeWarning(data);
        });
        
        this.socket.on('lip_movement_warning', (data) => {
            this.handleLipMovementWarning(data);
        });
    }
    
    handleGazeUpdate(data) {
        if (!this.isActive) return;
        
        const gazeData = data.gaze_data;
        if (gazeData) {
            // Update gaze status display
            const gazeStatus = document.getElementById('gazeStatus');
            if (gazeStatus) {
                if (gazeData.is_looking_at_screen) {
                    gazeStatus.textContent = '✅ Looking at Screen';
                    gazeStatus.style.color = '#28a745';
                } else {
                    gazeStatus.textContent = '❌ Looking Away';
                    gazeStatus.style.color = '#dc3545';
                }
            }
        }
        
        // Handle detection data for cheating behavior
        const detectionData = data.detection_data;
        if (detectionData) {
            // Update detection status
            const detectionStatus = document.getElementById('detectionStatus');
            if (detectionStatus) {
                if (detectionData.cheating_detected) {
                    detectionStatus.textContent = '🚨 Cheating Detected!';
                    detectionStatus.style.color = '#dc3545';
                    
                    // Voice warning for cheating behavior
                    const warningMessage = this.getWarningMessage('cheating_behavior', { severity: 'severe' });
                    this.speakWarning(warningMessage, 'high');
                } else if (detectionData.lip_movement) {
                    detectionStatus.textContent = '👄 Lip Movement';
                    detectionStatus.style.color = '#ffc107';
                } else {
                    detectionStatus.textContent = '✅ Normal Behavior';
                    detectionStatus.style.color = '#28a745';
                }
            }
        }
    }
    
    handleGazeWarning(data) {
        if (!this.isActive) return;
        
        this.showWarning(data.message, 'warning');
        
        // Voice warning for gaze violations
        const warningMessage = this.getWarningMessage('gaze_violation', data);
        const priority = data.duration > 60 ? 'high' : 'normal';
        this.speakWarning(warningMessage, priority);
    }
    
    handleLipMovementWarning(data) {
        if (!this.isActive) return;
        
        this.showWarning(data.message, 'danger');
        
        // Voice warning for lip movement
        const warningMessage = this.getWarningMessage('lip_movement', data);
        this.speakWarning(warningMessage, 'normal');
    }
    
    handleUnifiedWarning(data) {
        if (!this.isActive) return;
        
        // Determine warning type and severity
        const warningType = data.type || 'general';
        const severity = data.severity || 'normal';
        const duration = data.duration || 0;
        
        // Show visual warning
        this.showWarning(data.message, this.getWarningAlertType(warningType, severity));
        
        // Generate and speak voice warning
        const warningMessage = this.getWarningMessage(warningType, { 
            duration: duration, 
            severity: severity,
            count: data.remaining !== undefined ? (3 - data.remaining) : undefined
        });
        
        // Determine priority based on severity and duration
        let priority = 'normal';
        if (severity === 'severe' || severity === 'looking_down' || duration > 60) {
            priority = 'high';
        } else if (severity === 'moderate' || duration > 30) {
            priority = 'moderate';
        }
        
        // Speak the warning
        this.speakWarning(warningMessage, priority);
        
        console.log(`Unified warning handled: ${warningType} - ${severity} - ${warningMessage}`);
    }
    
    getWarningAlertType(warningType, severity) {
        // Map warning types to Bootstrap alert classes
        const alertTypes = {
            'gaze_violation': severity === 'severe' ? 'danger' : 'warning',
            'lip_movement': 'danger',
            'tab_switch': 'warning',
            'face_not_visible': severity === 'severe' ? 'danger' : 'warning',
            'cheating_behavior': 'danger',
            'general': 'info'
        };
        
        return alertTypes[warningType] || 'info';
    }

    showWarning(message, type = 'warning') {
        const warningContainer = document.getElementById('warningContainer');
        if (!warningContainer) return;
        
        const warningDiv = document.createElement('div');
        warningDiv.className = `alert alert-${type} alert-dismissible fade show warning-alert`;
        warningDiv.innerHTML = `
            <strong>⚠️ Warning!</strong> ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        warningContainer.appendChild(warningDiv);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (warningDiv.parentNode) {
                warningDiv.remove();
            }
        }, 5000);
    }

    terminateSession(reason) {
        this.isActive = false;
        
        const statusIndicator = document.getElementById('statusIndicator');
        if (statusIndicator) {
            statusIndicator.className = 'status-indicator status-danger';
            statusIndicator.textContent = '❌ Session Terminated';
        }
        
        this.showWarning(`Session terminated: ${reason}`, 'danger');
        
        // Stop camera stream
        if (this.camera) {
            this.camera.getTracks().forEach(track => track.stop());
        }
        
        setTimeout(() => {
            alert('Your exam session has been terminated due to violations.');
            window.location.href = '/';
        }, 3000);
    }

    endSession() {
        if (confirm('Are you sure you want to end this exam session?')) {
            this.isActive = false;
            
            if (this.camera) {
                this.camera.getTracks().forEach(track => track.stop());
            }
            
            fetch(`/api/end_session/${this.sessionId}`, {
                method: 'POST'
            }).then(() => {
                window.location.href = '/';
            });
        }
    }
    
    // Voice Warning System Methods
    initializeVoiceSystem() {
        if (!this.speechSynthesis) {
            console.warn('Speech synthesis not supported in this browser');
            this.voiceEnabled = false;
            return;
        }
        
        // Wait for voices to load
        this.speechSynthesis.onvoiceschanged = () => {
            this.voices = this.speechSynthesis.getVoices();
            // Try to find a good voice for warnings
            this.warningVoice = this.voices.find(voice => 
                voice.lang.includes('en') && voice.name.includes('Google')
            ) || this.voices.find(voice => 
                voice.lang.includes('en')
            ) || this.voices[0];
            
            console.log('Voice system initialized with voice:', this.warningVoice?.name || 'Default');
        };
        
        // Get initial voices
        this.voices = this.speechSynthesis.getVoices();
        this.warningVoice = this.voices.find(voice => 
            voice.lang.includes('en') && voice.name.includes('Google')
        ) || this.voices.find(voice => 
            voice.lang.includes('en')
        ) || this.voices[0];
    }
    
    speakWarning(message, priority = 'normal') {
        if (!this.voiceEnabled || !this.speechSynthesis) {
            return;
        }
        
        // Stop any current speech
        this.speechSynthesis.cancel();
        
        // Create speech utterance
        const utterance = new SpeechSynthesisUtterance(message);
        utterance.voice = this.warningVoice;
        utterance.rate = 0.9; // Slightly slower for clarity
        utterance.pitch = 1.1; // Slightly higher pitch for attention
        utterance.volume = this.voiceVolume; // Use configurable volume
        
        // Set priority-based properties
        if (priority === 'high') {
            utterance.rate = 0.8; // Slower for important warnings
            utterance.pitch = 1.2; // Higher pitch for urgency
            utterance.volume = Math.min(1.0, this.voiceVolume + 0.2); // Boost volume for critical warnings
        }
        
        // Speak the warning
        this.speechSynthesis.speak(utterance);
        
        console.log(`Voice warning spoken: "${message}"`);
    }
    
    getWarningMessage(warningType, data = {}) {
        const messages = {
            'gaze_violation': {
                normal: 'Please focus on the screen',
                moderate: 'You are looking away from the screen. Please focus on your exam',
                severe: 'Warning! You have been looking away for too long. Focus on the screen immediately',
                looking_down: 'You appear to be looking down. Please keep your eyes on the screen'
            },
            'lip_movement': {
                normal: 'Please do not talk or whisper during the exam',
                moderate: 'Lip movement detected. Please remain silent and focus on your exam',
                severe: 'Warning! Talking or whispering is not allowed. Please stop immediately'
            },
            'face_not_visible': {
                normal: 'Your face is not visible. Please return to camera view',
                moderate: 'Your face is not visible in the camera. Please adjust your position',
                severe: 'Critical warning! Your face must be visible in the camera at all times'
            },
            'tab_switch': {
                normal: 'Please do not switch tabs during the exam',
                moderate: 'Tab switching detected. Please stay on the exam page',
                severe: 'Warning! Multiple tab switches detected. This is a violation'
            },
            'cheating_behavior': {
                normal: 'Please focus on your exam and avoid suspicious behavior',
                moderate: 'Suspicious behavior detected. Please focus on the screen',
                severe: 'Critical warning! Cheating behavior detected. This is a serious violation'
            },
            'general': {
                normal: 'Please focus on your exam',
                moderate: 'Warning! Please pay attention to your exam',
                severe: 'Critical warning! This is a serious violation'
            }
        };
        
        const typeMessages = messages[warningType];
        if (!typeMessages) {
            return 'Please focus on your exam';
        }
        
        // Determine severity based on data
        let severity = 'normal';
        if (data.severity) {
            severity = data.severity;
        } else if (data.duration && data.duration > 60) {
            severity = 'severe';
        } else if (data.duration && data.duration > 30) {
            severity = 'moderate';
        } else if (data.count && data.count >= 3) {
            severity = 'severe';
        } else if (data.count && data.count >= 2) {
            severity = 'moderate';
        }
        
        return typeMessages[severity] || typeMessages.normal;
    }
    
    // Voice Control Methods
    toggleVoiceWarnings() {
        this.voiceEnabled = !this.voiceEnabled;
        console.log(`Voice warnings ${this.voiceEnabled ? 'enabled' : 'disabled'}`);
        return this.voiceEnabled;
    }
    
    setVoiceVolume(volume) {
        this.voiceVolume = Math.max(0, Math.min(1, volume)); // Clamp between 0 and 1
        console.log(`Voice volume set to ${this.voiceVolume}`);
        return this.voiceVolume;
    }
    
    muteVoice() {
        this.voiceEnabled = false;
        console.log('Voice warnings muted');
        return false;
    }
    
    unmuteVoice() {
        this.voiceEnabled = true;
        console.log('Voice warnings unmuted');
        return true;
    }
    
    getVoiceStatus() {
        return {
            enabled: this.voiceEnabled,
            volume: this.voiceVolume,
            voiceName: this.warningVoice?.name || 'Default',
            supported: !!this.speechSynthesis
        };
    }
}

// Export for use in other files
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ProctorSystem;
} 