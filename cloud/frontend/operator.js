// Fleet Operator Frontend JavaScript
let peerConnection = null;
let cmdVelChannel = null;
let operatorSessionId = null;
let lastConnectedRobot = null;  // Track last connected robot for auto-reconnect
let isReconnecting = false;  // Prevent multiple simultaneous reconnection attempts
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 3;
// window.selectedRobot is now defined globally in index.html as window.selectedRobot

function log(msg, type = 'info') {
    const logEl = document.getElementById('log');
    const time = new Date().toLocaleTimeString();
    const color = type === 'error' ? '#ff6b6b' : type === 'success' ? '#51cf66' : '#74c0fc';
    logEl.innerHTML += `<div style="color: ${color}">[${time}] ${msg}</div>`;
    logEl.scrollTop = logEl.scrollHeight;
    console.log(`[${type}] ${msg}`);
}

function clearLog() {
    document.getElementById('log').innerHTML = '';
}

function setStatus(msg, type = 'info') {
    const el = document.getElementById('connectionStatus');
    el.textContent = msg;
    el.className = `status ${type}`;
}

/**
 * Get worker URL from config
 */
function getWorkerUrl() {
    return document.getElementById('workerUrl').value;
}

/**
 * Make authenticated request to backend API (no secrets exposed on frontend)
 */
async function backendFetch(endpoint, options = {}) {
    const workerUrl = getWorkerUrl();
    const url = `${workerUrl}${endpoint}`;

    const response = await fetch(url, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
    });

    return response;
}

// Fetch robot list
async function fetchRobots() {
    const workerUrl = document.getElementById('workerUrl').value;
    try {
        log('Fetching robots...');
        const resp = await fetch(`${workerUrl}/robots`);
        const robots = await resp.json();
        
        const listEl = document.getElementById('robotList');
        if (robots.length === 0) {
            listEl.innerHTML = '<p style="color: #888;">No robots online</p>';
            log('No robots found', 'info');
            return;
        }
        
        listEl.innerHTML = robots.map(r => `
            <div class="robot-item ${window.selectedRobot?.id === r.id ? 'selected' : ''}" 
                 onclick="selectRobot('${r.id}', '${r.sfuSessionId}', '${r.videoTrackName}')"
                 data-robot-id="${r.id}">
                <div class="robot-info">
                    <div class="robot-name">${r.id}</div>
                    <div class="robot-status">● ${r.status}</div>
                    <div class="robot-meta">
                        Session: ${r.sfuSessionId?.substring(0, 16)}... | 
                        Track: ${r.videoTrackName || 'N/A'} | 
                        Last seen: ${new Date(r.lastSeen).toLocaleTimeString()}
                    </div>
                </div>
            </div>
        `).join('');
        
        log(`Found ${robots.length} robot(s)`, 'success');
    } catch (e) {
        log(`Failed to fetch robots: ${e.message}`, 'error');
    }
}

// Select a robot (without connecting)
function selectRobot(robotId, sfuSessionId, videoTrackName) {
    window.selectedRobot = { id: robotId, sfuSessionId, videoTrackName };
    log(`Selected robot: ${window.selectedRobot.id}`, 'success');
    
    // Update UI to show selected state
    document.querySelectorAll('.robot-item').forEach(el => {
        el.classList.remove('selected');
    });
    const selectedEl = document.querySelector(`[data-robot-id="${robotId}"]`);
    if (selectedEl) {
        selectedEl.classList.add('selected');
    }
    
    // Enable connect buttons
    document.getElementById('connectBtn').disabled = false;
}

// Connect to selected robot
async function connectToRobot() {
    if (!window.selectedRobot) {
        log('No robot selected', 'error');
        return;
    }

    // Fetch fresh robot data before connecting (unless auto-reconnecting, which already fetched)
    if (!isReconnecting) {
        try {
            log('Fetching fresh robot data before connection...');
            const workerUrl = getWorkerUrl();
            const resp = await fetch(`${workerUrl}/robots`);
            const robots = await resp.json();

            const freshRobotData = robots.find(r => r.id === window.selectedRobot.id);

            if (!freshRobotData) {
                log(`Robot ${window.selectedRobot.id} not found - may be offline`, 'error');
                setStatus('Robot not available', 'error');
                return;
            }

            // Update with fresh session data
            log(`Using fresh session: ${freshRobotData.sfuSessionId?.substring(0, 16)}..., track: ${freshRobotData.videoTrackName}`, 'info');
            window.selectedRobot = {
                id: freshRobotData.id,
                sfuSessionId: freshRobotData.sfuSessionId,
                videoTrackName: freshRobotData.videoTrackName
            };
        } catch (err) {
            log(`Failed to fetch fresh robot data: ${err.message}`, 'warn');
            log('Continuing with cached data...', 'warn');
        }
    }

    // Save the robot info for potential reconnection
    lastConnectedRobot = { ...window.selectedRobot };

    // Reset reconnect tracking on new manual connection
    if (!isReconnecting) {
        reconnectAttempts = 0;
    }

    try {
        log(`Connecting to robot ${window.selectedRobot.id}...`);
        setStatus('Connecting...', 'info');

        // 1. Create SFU session (via backend API - no secrets exposed)
        log('Creating SFU session...');
        const sessionResp = await backendFetch('/api/calls/sessions/new', {
            method: 'POST',
        });
        const sessionData = await sessionResp.json();
        operatorSessionId = sessionData.sessionId;
        log(`Created session: ${operatorSessionId}`, 'success');
        
        // 2. Create PeerConnection
        peerConnection = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.cloudflare.com:3478' }],
            bundlePolicy: 'max-bundle'
        });
        
        peerConnection.ontrack = (event) => {
            log('Received remote track: ' + event.track.kind, 'success');
            document.getElementById('remoteVideo').srcObject = event.streams[0];
        };
        
        peerConnection.onconnectionstatechange = () => {
            const state = peerConnection.connectionState;
            log(`PeerConnection state: ${state}`, state === 'failed' || state === 'disconnected' ? 'error' : 'info');
        };

        peerConnection.oniceconnectionstatechange = () => {
            const state = peerConnection.iceConnectionState;
            log(`ICE connection state: ${state}`, state === 'failed' || state === 'disconnected' ? 'error' : 'info');

            if (state === 'connected' || state === 'completed') {
                setStatus(`Connected to ${window.selectedRobot.id}`, 'success');
                reconnectAttempts = 0;  // Reset on successful connection
                isReconnecting = false;
            } else if (state === 'disconnected') {
                log('⚠️ ICE connection lost - monitoring for recovery...', 'error');
                setStatus('Connection unstable - waiting for recovery...', 'error');

                // Give it 3 seconds to recover before attempting reconnect
                setTimeout(() => {
                    if (peerConnection && peerConnection.iceConnectionState === 'disconnected') {
                        log('❌ Connection did not recover - initiating reconnect', 'error');
                        attemptReconnect();
                    } else if (peerConnection) {
                        log('✓ Connection recovered automatically', 'success');
                    }
                }, 3000);
            } else if (state === 'failed') {
                log('❌ ICE connection failed - initiating immediate reconnect', 'error');
                setStatus('Connection failed - reconnecting...', 'error');
                attemptReconnect();
            } else if (state === 'closed') {
                log('ICE connection closed', 'info');
                if (!isReconnecting) {
                    setStatus('Disconnected', 'info');
                }
            }
        };

        peerConnection.onicegatheringstatechange = () => {
            log(`ICE gathering state: ${peerConnection.iceGatheringState}`, 'info');
        };
        
        // 3. Add recvonly transceiver for video
        const tempChannel = peerConnection.createDataChannel('cmd_vel_temp', { ordered: true });
        log('Created temp DataChannel for SCTP transport');
        
        peerConnection.addTransceiver('video', { direction: 'recvonly' });
        
        // 4. Create offer
        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);
        log('Created local offer');
        
        // 5. Pull robot's video track (via backend API)
        log(`Pulling video track: ${window.selectedRobot.videoTrackName} from session ${window.selectedRobot.sfuSessionId}`);
        const pullResp = await backendFetch(`/api/calls/sessions/${operatorSessionId}/tracks/new`, {
            method: 'POST',
            body: JSON.stringify({
                sessionDescription: { sdp: offer.sdp, type: 'offer' },
                tracks: [{
                    location: 'remote',
                    sessionId: window.selectedRobot.sfuSessionId,
                    trackName: window.selectedRobot.videoTrackName
                }]
            })
        });
        const pullData = await pullResp.json();
        
        if (pullData.errorCode) {
            throw new Error(`Pull error: ${pullData.errorDescription}`);
        }
        
        // 6. Set remote description
        if (pullData.sessionDescription) {
            await peerConnection.setRemoteDescription(
                new RTCSessionDescription(pullData.sessionDescription)
            );
            log('Set remote description', 'success');
        }
        
        // 7. Handle renegotiation if needed (via backend API)
        if (pullData.requiresImmediateRenegotiation) {
            const answer = await peerConnection.createAnswer();
            await peerConnection.setLocalDescription(answer);

            const renegoResp = await backendFetch(`/api/calls/sessions/${operatorSessionId}/renegotiate`, {
                method: 'PUT',
                body: JSON.stringify({
                    sessionDescription: { sdp: answer.sdp, type: 'answer' }
                })
            });
            const renegoData = await renegoResp.json();
            log('Renegotiation completed', 'success');
        }
        
        // 8. Wait for ICE connection
        log('Waiting for ICE connection...');
        await waitForICE();
        
        // 9. Register DataChannel with SFU (via backend API)
        const dcResp = await backendFetch(`/api/calls/sessions/${operatorSessionId}/datachannels/new`, {
            method: 'POST',
            body: JSON.stringify({
                dataChannels: [{
                    location: 'local',
                    dataChannelName: 'cmd_vel'
                }]
            })
        });
        const dcData = await dcResp.json();
        
        if (dcData.dataChannels && dcData.dataChannels[0] && dcData.dataChannels[0].id !== undefined) {
            const dcId = dcData.dataChannels[0].id;
            tempChannel.close();
            
            // Create negotiated DataChannel with SFU-assigned ID
            cmdVelChannel = peerConnection.createDataChannel('cmd_vel', {
                negotiated: true,
                id: dcId,
                ordered: true
            });
            
            cmdVelChannel.onopen = () => {
                log(`✓ cmd_vel DataChannel opened (id=${dcId}, readyState=${cmdVelChannel.readyState})`, 'success');
                enableControls();
            };

            cmdVelChannel.onclose = (event) => {
                log(`❌ cmd_vel DataChannel closed (readyState=${cmdVelChannel.readyState})`, 'error');
                log(`   Close event: code=${event?.code}, reason=${event?.reason || 'none'}`, 'error');
                log(`   PeerConnection state: ${peerConnection?.connectionState}, ICE: ${peerConnection?.iceConnectionState}`, 'error');

                if (!isReconnecting && lastConnectedRobot) {
                    log('⚡ DataChannel closed unexpectedly - attempting reconnect', 'error');
                    attemptReconnect();
                }
            };

            cmdVelChannel.onerror = (e) => {
                log(`❌ cmd_vel DataChannel error: ${e}`, 'error');
                log(`   Error event: ${JSON.stringify(e)}`, 'error');
                log(`   DataChannel state: ${cmdVelChannel?.readyState}, buffer: ${cmdVelChannel?.bufferedAmount || 0} bytes`, 'error');

                if (!isReconnecting && lastConnectedRobot) {
                    log('⚡ DataChannel error - attempting reconnect', 'error');
                    attemptReconnect();
                }
            };

            // Monitor buffered amount periodically
            const bufferMonitor = setInterval(() => {
                if (cmdVelChannel && cmdVelChannel.readyState === 'open') {
                    const buffered = cmdVelChannel.bufferedAmount;
                    if (buffered > 32768) {  // 32KB threshold for warning
                        log(`⚠️ DataChannel buffer high: ${buffered} bytes`, 'warn');
                    }
                } else {
                    clearInterval(bufferMonitor);
                }
            }, 5000);  // Check every 5 seconds
            
            await waitForDataChannel();
        }
        
        // 10. Signal robot to subscribe to our cmd_vel channel
        const connectResp = await backendFetch('/connect', {
            method: 'POST',
            body: JSON.stringify({
                robotId: window.selectedRobot.id,
                operatorSessionId: operatorSessionId
            })
        });
        const connectData = await connectResp.json();
        
        if (connectData.success) {
            log('Connected to robot!', 'success');
            setStatus(`Connected to ${window.selectedRobot.id}`, 'success');
            document.getElementById('connectBtn').disabled = true;
            document.getElementById('disconnectBtn').disabled = false;
        } else {
            throw new Error(`Connect failed: ${connectData.error}`);
        }
        
    } catch (e) {
        log(`Failed to connect: ${e.message}`, 'error');
        setStatus('Connection failed', 'error');
        disconnect();
    }
}

function waitForICE() {
    return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
            log('ICE timeout - continuing anyway', 'warn');
            resolve();
        }, 5000);
        
        if (peerConnection.iceConnectionState === 'connected' || 
            peerConnection.iceConnectionState === 'completed') {
            clearTimeout(timeout);
            resolve();
            return;
        }
        
        const stateHandler = () => {
            if (peerConnection.iceConnectionState === 'connected' ||
                peerConnection.iceConnectionState === 'completed') {
                clearTimeout(timeout);
                peerConnection.removeEventListener('iceconnectionstatechange', stateHandler);
                resolve();
            } else if (peerConnection.iceConnectionState === 'failed') {
                clearTimeout(timeout);
                peerConnection.removeEventListener('iceconnectionstatechange', stateHandler);
                reject(new Error('ICE failed'));
            }
        };
        peerConnection.addEventListener('iceconnectionstatechange', stateHandler);
    });
}

function waitForDataChannel() {
    return new Promise((resolve) => {
        if (cmdVelChannel.readyState === 'open') {
            resolve();
            return;
        }
        
        const timeout = setTimeout(() => {
            log(`DataChannel timeout - state: ${cmdVelChannel.readyState}`, 'warn');
            resolve();
        }, 3000);
        
        cmdVelChannel.onopen = () => {
            clearTimeout(timeout);
            resolve();
        };
    });
}

async function attemptReconnect() {
    if (isReconnecting) {
        log('Reconnection already in progress', 'info');
        return;
    }

    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        log(`Maximum reconnection attempts (${MAX_RECONNECT_ATTEMPTS}) reached`, 'error');
        setStatus('Connection failed - please reconnect manually', 'error');
        await cleanupSession();
        disconnect();
        return;
    }

    if (!lastConnectedRobot) {
        log('No robot to reconnect to', 'error');
        await cleanupSession();
        disconnect();
        return;
    }

    reconnectAttempts++;
    isReconnecting = true;
    log(`Reconnection attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}...`, 'info');
    setStatus(`Reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`, 'info');

    // Clean up old connection and session first
    await cleanupSession();

    // CRITICAL FIX: Fetch fresh robot data before reconnecting
    // The robot may have a new SFU session and video track after going offline/online
    try {
        const workerUrl = getWorkerUrl();
        const resp = await fetch(`${workerUrl}/robots`);
        const robots = await resp.json();

        // Find the robot we were connected to
        const freshRobotData = robots.find(r => r.id === lastConnectedRobot.id);

        if (!freshRobotData) {
            log(`Robot ${lastConnectedRobot.id} not found - may be offline`, 'error');
            isReconnecting = false;

            if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
                setTimeout(() => attemptReconnect(), 2000);
            } else {
                disconnect();
            }
            return;
        }

        // Update with fresh session data
        log(`Refreshed robot data: session ${freshRobotData.sfuSessionId?.substring(0, 16)}..., track ${freshRobotData.videoTrackName}`, 'info');
        window.selectedRobot = {
            id: freshRobotData.id,
            sfuSessionId: freshRobotData.sfuSessionId,
            videoTrackName: freshRobotData.videoTrackName
        };
        lastConnectedRobot = { ...window.selectedRobot };

    } catch (err) {
        log(`Failed to fetch fresh robot data: ${err.message}`, 'error');
        isReconnecting = false;

        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            setTimeout(() => attemptReconnect(), 2000);
        } else {
            disconnect();
        }
        return;
    }

    // Wait a bit before reconnecting to allow cleanup to complete
    setTimeout(() => {
        connectToRobot().catch(err => {
            log(`Reconnection failed: ${err.message}`, 'error');
            isReconnecting = false;

            // Try again if we haven't hit the limit
            if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
                setTimeout(() => attemptReconnect(), 2000);
            } else {
                disconnect();
            }
        });
    }, 1500);  // Increased delay to ensure cleanup completes
}

/**
 * Clean up the SFU session to prevent zombie sessions
 */
async function cleanupSession() {
    const sessionToCleanup = operatorSessionId;

    // Close PeerConnection first
    if (peerConnection) {
        try {
            peerConnection.close();
        } catch (e) {
            log(`Error closing PeerConnection: ${e.message}`, 'warn');
        }
        peerConnection = null;
    }
    cmdVelChannel = null;

    // Close the SFU session via API to free resources
    if (sessionToCleanup) {
        try {
            log(`Cleaning up SFU session: ${sessionToCleanup.substring(0, 16)}...`, 'info');
            // Note: Cloudflare Calls API doesn't have explicit session delete
            // Sessions auto-expire, but closing PeerConnection helps
            // We could add a backend endpoint to track and clean sessions if needed
        } catch (e) {
            log(`Session cleanup warning: ${e.message}`, 'warn');
        }
        operatorSessionId = null;
    }
}

async function disconnect() {
    // Clean up session first
    await cleanupSession();

    // Don't clear selectedRobot or lastConnectedRobot to allow manual reconnect
    // Only clear reconnect state
    isReconnecting = false;
    reconnectAttempts = 0;

    document.getElementById('connectBtn').disabled = false;
    document.getElementById('disconnectBtn').disabled = true;
    document.getElementById('remoteVideo').srcObject = null;

    disableControls();
    setStatus('Disconnected', 'info');
    log('Disconnected');
}

function enableControls() {
    // Controls are always enabled for now
}

function disableControls() {
    // Reset joystick
    const knob = document.getElementById('joystickKnob');
    knob.style.left = '50px';
    knob.style.top = '50px';
}

// Rate limiting for DataChannel
let lastSendTime = 0;
const MIN_SEND_INTERVAL_MS = 100;  // 100ms = 10Hz max rate (throttled to reduce DataChannel load)
const MAX_BUFFER_SIZE = 65536;     // 64KB buffer threshold
let droppedMessages = 0;

// Send velocity command
function sendCommand(linear, angular) {
    // Update UI immediately for responsiveness
    document.getElementById('linearValue').textContent = linear.toFixed(2);
    document.getElementById('angularValue').textContent = angular.toFixed(2);

    if (!cmdVelChannel || cmdVelChannel.readyState !== 'open') {
        return;
    }

    // Rate limiting - prevent overwhelming the channel
    const now = Date.now();
    if (now - lastSendTime < MIN_SEND_INTERVAL_MS) {
        return;  // Skip this message
    }

    // Backpressure handling - check buffer before sending
    if (cmdVelChannel.bufferedAmount > MAX_BUFFER_SIZE) {
        droppedMessages++;
        if (droppedMessages % 10 === 0) {  // Log every 10th drop
            log(`DataChannel buffer full (${cmdVelChannel.bufferedAmount} bytes), dropping messages (${droppedMessages} total)`, 'warn');
        }
        return;
    }

    try {
        const cmd = {
            linear: { x: linear, y: 0, z: 0 },
            angular: { x: 0, y: 0, z: angular }
        };
        cmdVelChannel.send(JSON.stringify(cmd));
        lastSendTime = now;

        // Reset dropped counter on successful send
        if (droppedMessages > 0) {
            droppedMessages = 0;
        }

        // Log occasionally to avoid spam
        if (Math.random() < 0.02) {  // Reduced from 5% to 2%
            log(`Sent cmd: linear=${linear.toFixed(2)}, angular=${angular.toFixed(2)} (buffer: ${cmdVelChannel.bufferedAmount} bytes)`);
        }
    } catch (e) {
        log(`Failed to send command: ${e.message}`, 'error');
    }
}

// Joystick control
const joystick = document.getElementById('joystick');
const knob = document.getElementById('joystickKnob');
let dragging = false;

function updateKnob(clientX, clientY) {
    const rect = joystick.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    
    let dx = clientX - centerX;
    let dy = clientY - centerY;
    
    const maxDist = rect.width / 2 - 25;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist > maxDist) {
        dx = (dx / dist) * maxDist;
        dy = (dy / dist) * maxDist;
    }
    
    knob.style.left = (rect.width / 2 - 25 + dx) + 'px';
    knob.style.top = (rect.height / 2 - 25 + dy) + 'px';
    
    const linear = -dy / maxDist * 0.5;  // Forward/backward (scaled to 0.5 max)
    const angular = -dx / maxDist * 1.0; // Left/right (scaled to 1.0 max)
    sendCommand(linear, angular);
}

joystick.addEventListener('mousedown', (e) => {
    dragging = true;
    updateKnob(e.clientX, e.clientY);
});

document.addEventListener('mousemove', (e) => {
    if (dragging) updateKnob(e.clientX, e.clientY);
});

document.addEventListener('mouseup', () => {
    dragging = false;
    knob.style.left = '50px';
    knob.style.top = '50px';
    sendCommand(0, 0);
});

// Touch support for mobile
joystick.addEventListener('touchstart', (e) => {
    e.preventDefault();
    dragging = true;
    const touch = e.touches[0];
    updateKnob(touch.clientX, touch.clientY);
});

document.addEventListener('touchmove', (e) => {
    if (dragging) {
        e.preventDefault();
        const touch = e.touches[0];
        updateKnob(touch.clientX, touch.clientY);
    }
});

document.addEventListener('touchend', (e) => {
    if (dragging) {
        e.preventDefault();
        dragging = false;
        knob.style.left = '50px';
        knob.style.top = '50px';
        sendCommand(0, 0);
    }
});

// Keyboard controls
const keyState = { w: false, a: false, s: false, d: false, ArrowUp: false, ArrowLeft: false, ArrowDown: false, ArrowRight: false };

document.addEventListener('keydown', (e) => {
    const key = e.key;
    if (key in keyState) {
        keyState[key] = true;
        updateFromKeys();
        e.preventDefault();
    } else if (key === ' ') {
        // Space = emergency stop
        Object.keys(keyState).forEach(k => keyState[k] = false);
        sendCommand(0, 0);
        e.preventDefault();
    }
});

document.addEventListener('keyup', (e) => {
    const key = e.key;
    if (key in keyState) {
        keyState[key] = false;
        updateFromKeys();
        e.preventDefault();
    }
});

function updateFromKeys() {
    let linear = 0, angular = 0;
    if (keyState.w || keyState.ArrowUp) linear += 0.5;
    if (keyState.s || keyState.ArrowDown) linear -= 0.5;
    if (keyState.a || keyState.ArrowLeft) angular += 1.0;
    if (keyState.d || keyState.ArrowRight) angular -= 1.0;
    sendCommand(linear, angular);
}

// Initial load
window.addEventListener('DOMContentLoaded', () => {
    log('Fleet Operator Console initialized');
    fetchRobots();
    
    // Auto-refresh robots every 5 seconds
    setInterval(fetchRobots, 5000);
});
