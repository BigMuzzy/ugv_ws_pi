// WebRTC and WebSocket connections
let ws = null;
let pc = null;
let dataChannel = null;

// State
let isConnected = false;
let emergencyStop = false;
let currentVelocity = { linear: { x: 0, y: 0, z: 0 }, angular: { x: 0, y: 0, z: 0 } };
let commandCount = 0;
let lastCommandCountReset = Date.now();
let wsPingInterval = null;

// Configuration
const MAX_LINEAR_SPEED = 0.5;
const MAX_ANGULAR_SPEED = 1.0;
const COMMAND_RATE = 20; // Hz
const WS_PING_INTERVAL = 30000; // 30 seconds

// DOM elements
let statusDot, statusText, latencyDisplay, videoLatencyDisplay;
let videoElement, videoStatus, latencyCanvas;
let serverUrlInput, connectBtn, estopBtn;
let joystick, joystickKnob;

// Video latency measurement
let videoLatencyInterval = null;

// Joystick controls
let isDragging = false;
let joystickRect = null;

// Keyboard controls
const keyState = {};

/**
 * Initialize DOM element references
 */
function initDOMElements() {
    statusDot = document.getElementById('statusDot');
    statusText = document.getElementById('statusText');
    latencyDisplay = document.getElementById('latency');
    videoLatencyDisplay = document.getElementById('videoLatency');
    videoElement = document.getElementById('remoteVideo');
    videoStatus = document.getElementById('videoStatus');
    latencyCanvas = document.getElementById('latencyCanvas');
    serverUrlInput = document.getElementById('serverUrl');
    connectBtn = document.getElementById('connectBtn');
    estopBtn = document.getElementById('estopBtn');
    joystick = document.getElementById('joystick');
    joystickKnob = document.getElementById('joystickKnob');
}

/**
 * Initialize default server URL
 */
function initServerUrl() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const port = window.location.protocol === 'https:' ? '' : ':8080';
    serverUrlInput.value = `${protocol}//${window.location.hostname || 'localhost'}${port}/ws`;
}

/**
 * Update status display
 */
function updateStatus(status, text) {
    statusDot.className = 'status-dot ' + status;
    statusText.textContent = text;
    document.getElementById('connState').textContent = text;
}

/**
 * Toggle connection
 */
function toggleConnection() {
    if (isConnected) {
        disconnect();
    } else {
        connect();
    }
}

/**
 * Connect to signaling server
 */
async function connect() {
    const serverUrl = serverUrlInput.value;
    if (!serverUrl) {
        alert('Please enter server URL');
        return;
    }
    
    updateStatus('connecting', 'Connecting...');
    connectBtn.disabled = true;
    
    try {
        // Create WebSocket connection
        ws = new WebSocket(serverUrl);
        
        ws.onopen = () => {
            console.log('WebSocket connected');
            startWebSocketPing();
            createPeerConnection();
        };
        
        ws.onmessage = async (event) => {
            const message = JSON.parse(event.data);
            await handleSignalingMessage(message);
        };
        
        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            updateStatus('error', 'Connection Error');
            connectBtn.disabled = false;
        };
        
        ws.onclose = () => {
            console.log('WebSocket closed');
            disconnect();
        };
        
    } catch (error) {
        console.error('Connection error:', error);
        updateStatus('error', 'Failed to connect');
        connectBtn.disabled = false;
    }
}

/**
 * Create WebRTC peer connection
 */
async function createPeerConnection() {
    const config = {
        iceServers: [
            // Google STUN servers
            { urls: 'stun:stun.l.google.com:19302' },
            { urls: 'stun:stun1.l.google.com:19302' },
            // Metered.ca STUN server
            { urls: 'stun:stun.relay.metered.ca:80' },
            // Metered.ca TURN servers (free tier) - multiple transports for maximum compatibility
            // https://www.metered.ca/tools/openrelay/
            {
                urls: [
                    'turn:global.relay.metered.ca:80',
                    'turn:global.relay.metered.ca:80?transport=tcp',
                    'turn:global.relay.metered.ca:443',
                    'turns:global.relay.metered.ca:443?transport=tcp'
                ],
                username: 'bbded4f052d4c3c9e8e6342f',
                credential: 'UWI3yEJTIVm+nT0J'
            }
        ],
        iceCandidatePoolSize: 10,  // Gather candidates more aggressively
        iceTransportPolicy: 'all'  // Try all candidates including relay
    };

    pc = new RTCPeerConnection(config);

    // Handle ICE gathering state changes
    pc.onicegatheringstatechange = () => {
        console.log('ICE gathering state:', pc.iceGatheringState);
    };

    // Handle ICE connection state changes
    pc.oniceconnectionstatechange = () => {
        console.log('ICE connection state:', pc.iceConnectionState);
    };

    // Handle ICE candidates
    pc.onicecandidate = (event) => {
        if (event.candidate) {
            const c = event.candidate;
            console.log(`ICE candidate [${c.type}]:`,
                c.protocol, c.address + ':' + c.port,
                c.relatedAddress ? `(via ${c.relatedAddress}:${c.relatedPort})` : '');

            ws.send(JSON.stringify({
                type: 'ice_candidate',
                candidate: event.candidate
            }));
        } else {
            console.log('ICE gathering complete');
        }
    };
    
    // Handle connection state changes
    pc.onconnectionstatechange = () => {
        console.log('Connection state:', pc.connectionState);
        if (pc.connectionState === 'connected') {
            isConnected = true;
            updateStatus('connected', 'Connected');
            connectBtn.textContent = 'Disconnect';
            connectBtn.disabled = false;
            startCommandLoop();
        } else if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
            disconnect();
        }
    };
    
    // Handle incoming video track
    pc.ontrack = (event) => {
        console.log('Received track:', event.track.kind);
        if (event.track.kind === 'video') {
            videoElement.srcObject = event.streams[0];
            videoStatus.textContent = 'Video connected';
            startVideoLatencyMeasurement();
        }
    };
    
    // Create data channel for commands
    dataChannel = pc.createDataChannel('commands', { ordered: false });
    dataChannel.onopen = () => {
        console.log('Data channel opened');
    };
    dataChannel.onclose = () => {
        console.log('Data channel closed');
    };
    dataChannel.onmessage = (event) => {
        handleDataChannelMessage(JSON.parse(event.data));
    };
    
    // Create and send offer
    try {
        const offer = await pc.createOffer({
            offerToReceiveVideo: true,
            offerToReceiveAudio: false
        });
        await pc.setLocalDescription(offer);
        
        ws.send(JSON.stringify({
            type: 'offer',
            sdp: offer.sdp
        }));
    } catch (error) {
        console.error('Error creating offer:', error);
    }
}

/**
 * Handle signaling messages
 */
async function handleSignalingMessage(message) {
    if (message.type === 'answer') {
        try {
            await pc.setRemoteDescription(new RTCSessionDescription({
                type: 'answer',
                sdp: message.sdp
            }));
        } catch (error) {
            console.error('Error setting remote description:', error);
        }
    } else if (message.type === 'ice_candidate') {
        try {
            await pc.addIceCandidate(new RTCIceCandidate(message.candidate));
        } catch (error) {
            console.error('Error adding ICE candidate:', error);
        }
    } else if (message.type === 'pong') {
        const latency = Date.now() - message.timestamp;
        latencyDisplay.textContent = latency;
    }
}

/**
 * Handle data channel messages
 */
function handleDataChannelMessage(message) {
    if (message.type === 'pong') {
        const latency = Date.now() - message.timestamp;
        latencyDisplay.textContent = latency;
    }
}

/**
 * Disconnect
 */
function disconnect() {
    stopCommandLoop();
    stopWebSocketPing();
    stopVideoLatencyMeasurement();

    if (dataChannel) {
        dataChannel.close();
        dataChannel = null;
    }

    if (pc) {
        pc.close();
        pc = null;
    }

    if (ws) {
        ws.close();
        ws = null;
    }

    isConnected = false;
    updateStatus('', 'Disconnected');
    connectBtn.textContent = 'Connect';
    connectBtn.disabled = false;
    videoStatus.textContent = 'No video';
    videoElement.srcObject = null;
    videoLatencyDisplay.textContent = '--';
}

/**
 * Start video latency measurement using timestamp barcode
 */
function startVideoLatencyMeasurement() {
    if (videoLatencyInterval) return;

    // Set canvas size to match video
    latencyCanvas.width = 640;
    latencyCanvas.height = 480;

    videoLatencyInterval = setInterval(() => {
        measureVideoLatency();
    }, 100); // Measure every 100ms
}

/**
 * Stop video latency measurement
 */
function stopVideoLatencyMeasurement() {
    if (videoLatencyInterval) {
        clearInterval(videoLatencyInterval);
        videoLatencyInterval = null;
    }
}

/**
 * Measure video latency from timestamp barcode
 */
function measureVideoLatency() {
    if (!videoElement || !videoElement.videoWidth || videoElement.videoWidth === 0) {
        return;
    }

    try {
        const ctx = latencyCanvas.getContext('2d');

        // Draw current video frame to canvas
        ctx.drawImage(videoElement, 0, 0, latencyCanvas.width, latencyCanvas.height);

        // Read the timestamp barcode from top-right corner
        const barWidth = 3;
        const barHeight = 20;
        const xOffset = latencyCanvas.width - (13 * barWidth) - 5;
        const yOffset = 5;

        let timestampStr = '';

        // Read each bar and decode the digit
        for (let i = 0; i < 13; i++) {
            const x = xOffset + (i * barWidth);
            const y = yOffset + Math.floor(barHeight / 2);

            // Get pixel data for the middle of the bar
            const imageData = ctx.getImageData(x, y, 1, 1);
            const grayValue = imageData.data[0]; // R value (same as G and B for grayscale)

            // Decode: gray_value = digit * 25, so digit = gray_value / 25
            const digit = Math.round(grayValue / 25);
            timestampStr += digit;
        }

        // Parse the timestamp
        const frameTimestamp = parseInt(timestampStr, 10);

        if (!isNaN(frameTimestamp) && frameTimestamp > 0) {
            const currentTime = Date.now();
            const latency = currentTime - frameTimestamp;

            // Only display reasonable latency values (0-5000ms)
            if (latency >= 0 && latency < 5000) {
                videoLatencyDisplay.textContent = latency;
            }
        }
    } catch (error) {
        // Silently fail - video might not be ready yet
        console.debug('Video latency measurement error:', error);
    }
}

/**
 * Start WebSocket keepalive ping
 */
function startWebSocketPing() {
    if (wsPingInterval) return;

    // Send initial ping
    sendWebSocketPing();

    // Set up interval for periodic pings
    wsPingInterval = setInterval(() => {
        sendWebSocketPing();
    }, WS_PING_INTERVAL);

    console.log(`WebSocket keepalive started (${WS_PING_INTERVAL / 1000}s interval)`);
}

/**
 * Stop WebSocket keepalive ping
 */
function stopWebSocketPing() {
    if (wsPingInterval) {
        clearInterval(wsPingInterval);
        wsPingInterval = null;
        console.log('WebSocket keepalive stopped');
    }
}

/**
 * Send WebSocket ping
 */
function sendWebSocketPing() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'ping',
            timestamp: Date.now()
        }));
    }
}

/**
 * Start command loop
 */
function startCommandLoop() {
    if (commandLoopInterval) return;

    commandLoopInterval = setInterval(() => {
        sendVelocityCommand();
        measureLatency();
        updateStats();
    }, 1000 / COMMAND_RATE);
}

/**
 * Stop command loop
 */
let commandLoopInterval = null;

function stopCommandLoop() {
    if (commandLoopInterval) {
        clearInterval(commandLoopInterval);
        commandLoopInterval = null;
    }
}

/**
 * Send velocity command
 */
function sendVelocityCommand() {
    if (!dataChannel || dataChannel.readyState !== 'open') return;
    if (emergencyStop) return;
    
    const message = {
        type: 'cmd_vel',
        linear: currentVelocity.linear,
        angular: currentVelocity.angular
    };
    
    dataChannel.send(JSON.stringify(message));
    commandCount++;
}

/**
 * Measure latency
 */
function measureLatency() {
    if (!dataChannel || dataChannel.readyState !== 'open') return;
    
    dataChannel.send(JSON.stringify({
        type: 'ping',
        timestamp: Date.now()
    }));
}

/**
 * Update statistics display
 */
function updateStats() {
    document.getElementById('linearX').textContent = currentVelocity.linear.x.toFixed(2);
    document.getElementById('angularZ').textContent = currentVelocity.angular.z.toFixed(2);
    
    const now = Date.now();
    if (now - lastCommandCountReset >= 1000) {
        document.getElementById('cmdRate').textContent = commandCount;
        commandCount = 0;
        lastCommandCountReset = now;
    }
}

/**
 * Toggle emergency stop
 */
function toggleEmergencyStop() {
    emergencyStop = !emergencyStop;
    
    if (emergencyStop) {
        estopBtn.classList.add('active');
        estopBtn.textContent = '✅ Resume';
        currentVelocity = { linear: { x: 0, y: 0, z: 0 }, angular: { x: 0, y: 0, z: 0 } };
        
        if (dataChannel && dataChannel.readyState === 'open') {
            dataChannel.send(JSON.stringify({
                type: 'emergency_stop',
                active: true
            }));
        }
    } else {
        estopBtn.classList.remove('active');
        estopBtn.textContent = '🛑 EMERGENCY STOP';
        
        if (dataChannel && dataChannel.readyState === 'open') {
            dataChannel.send(JSON.stringify({
                type: 'emergency_stop',
                active: false
            }));
        }
    }
}

/**
 * Update velocity from keyboard state
 */
function updateVelocityFromKeys() {
    if (emergencyStop) return;
    
    let linearX = 0;
    let angularZ = 0;
    
    // Forward/backward
    if (keyState['w'] || keyState['arrowup']) linearX += MAX_LINEAR_SPEED;
    if (keyState['s'] || keyState['arrowdown']) linearX -= MAX_LINEAR_SPEED;
    
    // Left/right rotation
    if (keyState['a'] || keyState['arrowleft']) angularZ += MAX_ANGULAR_SPEED;
    if (keyState['d'] || keyState['arrowright']) angularZ -= MAX_ANGULAR_SPEED;
    
    currentVelocity.linear.x = linearX;
    currentVelocity.angular.z = angularZ;
}

/**
 * Initialize keyboard controls
 */
function initKeyboardControls() {
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT') return;
        
        keyState[e.key.toLowerCase()] = true;
        
        if (e.key === ' ') {
            e.preventDefault();
            toggleEmergencyStop();
        }
        
        updateVelocityFromKeys();
    });
    
    document.addEventListener('keyup', (e) => {
        keyState[e.key.toLowerCase()] = false;
        updateVelocityFromKeys();
    });
}

/**
 * Initialize joystick controls
 */
function initJoystick() {
    joystickRect = joystick.getBoundingClientRect();
    
    joystickKnob.addEventListener('mousedown', startDrag);
    joystickKnob.addEventListener('touchstart', startDrag, { passive: false });
    
    document.addEventListener('mousemove', drag);
    document.addEventListener('touchmove', drag, { passive: false });
    
    document.addEventListener('mouseup', endDrag);
    document.addEventListener('touchend', endDrag);
}

/**
 * Start joystick drag
 */
function startDrag(e) {
    e.preventDefault();
    isDragging = true;
    joystickRect = joystick.getBoundingClientRect();
}

/**
 * Handle joystick drag
 */
function drag(e) {
    if (!isDragging || emergencyStop) return;
    e.preventDefault();
    
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    
    const centerX = joystickRect.left + joystickRect.width / 2;
    const centerY = joystickRect.top + joystickRect.height / 2;
    
    let deltaX = clientX - centerX;
    let deltaY = clientY - centerY;
    
    // Limit to joystick bounds
    const maxRadius = joystickRect.width / 2 - 30;
    const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
    
    if (distance > maxRadius) {
        deltaX = (deltaX / distance) * maxRadius;
        deltaY = (deltaY / distance) * maxRadius;
    }
    
    // Update knob position
    joystickKnob.style.transform = `translate(calc(-50% + ${deltaX}px), calc(-50% + ${deltaY}px))`;
    
    // Convert to velocity (-1 to 1)
    const normalizedX = -deltaY / maxRadius; // Forward/backward
    const normalizedZ = -deltaX / maxRadius; // Left/right
    
    currentVelocity.linear.x = normalizedX * MAX_LINEAR_SPEED;
    currentVelocity.angular.z = normalizedZ * MAX_ANGULAR_SPEED;
}

/**
 * End joystick drag
 */
function endDrag() {
    if (!isDragging) return;
    isDragging = false;
    
    // Reset joystick position
    joystickKnob.style.transform = 'translate(-50%, -50%)';
    
    // Stop robot
    currentVelocity.linear.x = 0;
    currentVelocity.angular.z = 0;
}

/**
 * Initialize page visibility handling
 */
function initPageVisibility() {
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            // Stop robot when page is hidden
            currentVelocity = { linear: { x: 0, y: 0, z: 0 }, angular: { x: 0, y: 0, z: 0 } };
        }
    });
    
    window.addEventListener('beforeunload', () => {
        disconnect();
    });
}

/**
 * Initialize the application
 */
function init() {
    initDOMElements();
    initServerUrl();
    initKeyboardControls();
    initJoystick();
    initPageVisibility();
}

// Initialize when page loads
window.addEventListener('load', init);
