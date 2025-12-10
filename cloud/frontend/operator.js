// Fleet Operator Frontend JavaScript
let peerConnection = null;
let cmdVelChannel = null;
let operatorSessionId = null;
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
        
        peerConnection.oniceconnectionstatechange = () => {
            log(`ICE state: ${peerConnection.iceConnectionState}`);
            if (peerConnection.iceConnectionState === 'connected') {
                setStatus(`Connected to ${window.selectedRobot.id}`, 'success');
            }
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
                log(`cmd_vel channel opened (id=${dcId})`, 'success');
                enableControls();
            };
            cmdVelChannel.onclose = () => log('cmd_vel channel closed');
            cmdVelChannel.onerror = (e) => log(`cmd_vel error: ${e}`, 'error');
            
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

function disconnect() {
    if (peerConnection) {
        peerConnection.close();
        peerConnection = null;
    }
    cmdVelChannel = null;
    operatorSessionId = null;
    window.selectedRobot = null;
    
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

// Send velocity command
function sendCommand(linear, angular) {
    if (cmdVelChannel && cmdVelChannel.readyState === 'open') {
        const cmd = {
            linear: { x: linear, y: 0, z: 0 },
            angular: { x: 0, y: 0, z: angular }
        };
        cmdVelChannel.send(JSON.stringify(cmd));
        
        // Log occasionally to avoid spam
        if (Math.random() < 0.05) {
            log(`Sent cmd: linear=${linear.toFixed(2)}, angular=${angular.toFixed(2)}`);
        }
    }
    document.getElementById('linearValue').textContent = linear.toFixed(2);
    document.getElementById('angularValue').textContent = angular.toFixed(2);
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
