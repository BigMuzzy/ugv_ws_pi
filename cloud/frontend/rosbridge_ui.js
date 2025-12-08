/**
 * ROSBridge UI Controller for Fleet Operator Console
 * 
 * Provides UI controls for topic subscription, publishing, and action clients
 */

// Global ROSBridge instance
let rosBridge = null;
let activeSubscriptions = new Map();  // topic -> subscription handle

// ========== Connection Management ==========

function initROSBridge() {
    const workerUrl = document.getElementById('workerUrl').value;
    
    rosBridge = new FleetROSBridge({
        workerUrl: workerUrl,
        onConnection: onROSBridgeConnected,
        onClose: onROSBridgeDisconnected,
        onError: onROSBridgeError
    });
    
    logROS('ROSBridge client initialized');
}

function connectROSBridge() {
    if (!window.selectedRobot) {
        logROS('Please select a robot first', 'error');
        return;
    }
    
    if (!rosBridge) {
        initROSBridge();
    }
    
    logROS(`Connecting ROSBridge to ${window.selectedRobot.id}...`);
    updateROSBridgeStatus('Connecting...', 'info');
    rosBridge.connect(window.selectedRobot.id);
}

function disconnectROSBridge() {
    if (rosBridge) {
        // Unsubscribe all active subscriptions
        activeSubscriptions.forEach((sub, topic) => {
            sub.unsubscribe();
        });
        activeSubscriptions.clear();
        
        rosBridge.disconnect();
        logROS('ROSBridge disconnected');
    }
    updateROSBridgeStatus('Disconnected', 'info');
    updateSubscriptionsList();
    
    // Re-enable connect button, disable disconnect
    document.getElementById('rosbridgeConnectBtn').disabled = false;
    document.getElementById('rosbridgeDisconnectBtn').disabled = true;
    enableROSControls(false);
}

function onROSBridgeConnected() {
    logROS('ROSBridge connected!', 'success');
    updateROSBridgeStatus(`Connected to ${window.selectedRobot?.id || 'robot'}`, 'success');
    document.getElementById('rosbridgeConnectBtn').disabled = true;
    document.getElementById('rosbridgeDisconnectBtn').disabled = false;
    enableROSControls(true);
}

function onROSBridgeDisconnected(event) {
    logROS(`ROSBridge disconnected: ${event.reason || 'Connection closed'}`, 'info');
    updateROSBridgeStatus('Disconnected', 'info');
    document.getElementById('rosbridgeConnectBtn').disabled = false;
    document.getElementById('rosbridgeDisconnectBtn').disabled = true;
    enableROSControls(false);
    activeSubscriptions.clear();
    updateSubscriptionsList();
}

function onROSBridgeError(error) {
    logROS(`ROSBridge error: ${error.message || error}`, 'error');
    updateROSBridgeStatus('Error', 'error');
}

function updateROSBridgeStatus(msg, type) {
    const el = document.getElementById('rosbridgeStatus');
    el.textContent = msg;
    el.className = `status ${type}`;
}

function enableROSControls(enabled) {
    document.querySelectorAll('.ros-control').forEach(el => {
        el.disabled = !enabled;
    });
}

// ========== Topic Subscription ==========

function subscribeTopic() {
    const topic = document.getElementById('subTopicName').value.trim();
    const msgType = document.getElementById('subMsgType').value.trim();
    
    if (!topic || !msgType) {
        logROS('Please enter topic name and message type', 'error');
        return;
    }
    
    if (!rosBridge || !rosBridge.connected) {
        logROS('ROSBridge not connected', 'error');
        return;
    }
    
    if (activeSubscriptions.has(topic)) {
        logROS(`Already subscribed to ${topic}`, 'error');
        return;
    }
    
    const sub = rosBridge.subscribe(topic, msgType, (msg) => {
        displayTopicMessage(topic, msg);
    }, {
        throttle_rate: parseInt(document.getElementById('subThrottleRate').value) || 0
    });
    
    activeSubscriptions.set(topic, sub);
    updateSubscriptionsList();
    logROS(`Subscribed to ${topic}`, 'success');
}

function unsubscribeTopic(topic) {
    const sub = activeSubscriptions.get(topic);
    if (sub) {
        sub.unsubscribe();
        activeSubscriptions.delete(topic);
        updateSubscriptionsList();
        logROS(`Unsubscribed from ${topic}`, 'info');
    }
}

function updateSubscriptionsList() {
    const listEl = document.getElementById('activeSubscriptions');
    
    if (activeSubscriptions.size === 0) {
        listEl.innerHTML = '<p style="color: #888; margin: 0;">No active subscriptions</p>';
        return;
    }
    
    listEl.innerHTML = Array.from(activeSubscriptions.keys()).map(topic => `
        <div class="subscription-item">
            <span class="subscription-topic">${topic}</span>
            <button onclick="unsubscribeTopic('${topic}')" class="btn-small btn-danger">✕</button>
        </div>
    `).join('');
}

function displayTopicMessage(topic, msg) {
    const messagesEl = document.getElementById('topicMessages');
    const time = new Date().toLocaleTimeString();
    
    // Format message for display
    let msgDisplay;
    try {
        msgDisplay = JSON.stringify(msg, null, 2);
        // Truncate long messages
        if (msgDisplay.length > 500) {
            msgDisplay = msgDisplay.substring(0, 500) + '\n... (truncated)';
        }
    } catch (e) {
        msgDisplay = String(msg);
    }
    
    const msgHtml = `
        <div class="topic-message">
            <div class="topic-header">
                <span class="topic-name">${topic}</span>
                <span class="topic-time">${time}</span>
            </div>
            <pre class="topic-data">${escapeHtml(msgDisplay)}</pre>
        </div>
    `;
    
    // Add new message at top
    messagesEl.insertAdjacentHTML('afterbegin', msgHtml);
    
    // Keep only last 50 messages
    const messages = messagesEl.querySelectorAll('.topic-message');
    if (messages.length > 50) {
        messages[messages.length - 1].remove();
    }
}

function clearTopicMessages() {
    document.getElementById('topicMessages').innerHTML = '';
}

// ========== Topic Publishing ==========

function publishTopic() {
    const topic = document.getElementById('pubTopicName').value.trim();
    const msgType = document.getElementById('pubMsgType').value.trim();
    const msgData = document.getElementById('pubMsgData').value.trim();
    
    if (!topic || !msgType || !msgData) {
        logROS('Please enter topic name, message type, and data', 'error');
        return;
    }
    
    if (!rosBridge || !rosBridge.connected) {
        logROS('ROSBridge not connected', 'error');
        return;
    }
    
    try {
        const msg = JSON.parse(msgData);
        rosBridge.publish(topic, msgType, msg);
        logROS(`Published to ${topic}`, 'success');
    } catch (e) {
        logROS(`Invalid JSON: ${e.message}`, 'error');
    }
}

// Quick publish buttons for common topics
function publishCmdVel(linear, angular) {
    if (!rosBridge || !rosBridge.connected) {
        logROS('ROSBridge not connected', 'error');
        return;
    }
    
    rosBridge.publish('/cmd_vel', 'geometry_msgs/msg/Twist', {
        linear: { x: linear, y: 0.0, z: 0.0 },
        angular: { x: 0.0, y: 0.0, z: angular }
    });
}

function emergencyStop() {
    publishCmdVel(0.0, 0.0);
    logROS('Emergency stop sent!', 'success');
}

// ========== Service Calls ==========

function callService() {
    const service = document.getElementById('srvName').value.trim();
    const srvType = document.getElementById('srvType').value.trim();
    const reqData = document.getElementById('srvRequest').value.trim();
    
    if (!service || !srvType) {
        logROS('Please enter service name and type', 'error');
        return;
    }
    
    if (!rosBridge || !rosBridge.connected) {
        logROS('ROSBridge not connected', 'error');
        return;
    }
    
    try {
        const request = reqData ? JSON.parse(reqData) : {};
        
        logROS(`Calling service ${service}...`);
        rosBridge.callService(service, srvType, request, (success, response) => {
            if (success) {
                logROS(`Service response: ${JSON.stringify(response)}`, 'success');
                document.getElementById('srvResponse').value = JSON.stringify(response, null, 2);
            } else {
                logROS(`Service call failed: ${JSON.stringify(response)}`, 'error');
                document.getElementById('srvResponse').value = `Error: ${JSON.stringify(response)}`;
            }
        });
    } catch (e) {
        logROS(`Invalid JSON request: ${e.message}`, 'error');
    }
}

// ========== Action Clients ==========

let currentAction = null;

function sendActionGoal() {
    const actionName = document.getElementById('actionName').value.trim();
    const actionType = document.getElementById('actionType').value.trim();
    const goalData = document.getElementById('actionGoal').value.trim();
    
    if (!actionName || !actionType || !goalData) {
        logROS('Please enter action name, type, and goal', 'error');
        return;
    }
    
    if (!rosBridge || !rosBridge.connected) {
        logROS('ROSBridge not connected', 'error');
        return;
    }
    
    try {
        const goal = JSON.parse(goalData);
        
        logROS(`Sending goal to ${actionName}...`);
        currentAction = rosBridge.sendActionGoal(actionName, actionType, goal, {
            feedback: (feedback) => {
                logROS(`Action feedback: ${JSON.stringify(feedback)}`);
                document.getElementById('actionFeedback').value = JSON.stringify(feedback, null, 2);
            },
            result: (success, result) => {
                if (success) {
                    logROS(`Action completed: ${JSON.stringify(result)}`, 'success');
                } else {
                    logROS(`Action failed: ${JSON.stringify(result)}`, 'error');
                }
                document.getElementById('actionResult').value = JSON.stringify(result, null, 2);
                currentAction = null;
                document.getElementById('cancelActionBtn').disabled = true;
            }
        });
        
        document.getElementById('cancelActionBtn').disabled = false;
    } catch (e) {
        logROS(`Invalid JSON goal: ${e.message}`, 'error');
    }
}

function cancelAction() {
    if (currentAction) {
        currentAction.cancel();
        logROS('Action cancelled');
        currentAction = null;
        document.getElementById('cancelActionBtn').disabled = true;
    }
}

// ========== Navigation Quick Actions ==========

function sendNavGoal(x, y, yaw = 0.0) {
    if (!rosBridge || !rosBridge.connected) {
        logROS('ROSBridge not connected', 'error');
        return;
    }
    
    // Convert yaw to quaternion (simplified, only z-rotation)
    const qz = Math.sin(yaw / 2);
    const qw = Math.cos(yaw / 2);
    
    const goal = {
        pose: {
            header: {
                frame_id: 'map'
            },
            pose: {
                position: { x: x, y: y, z: 0.0 },
                orientation: { x: 0.0, y: 0.0, z: qz, w: qw }
            }
        }
    };
    
    logROS(`Sending navigation goal: x=${x}, y=${y}, yaw=${yaw}`);
    
    currentAction = rosBridge.sendActionGoal(
        '/navigate_to_pose',
        'nav2_msgs/action/NavigateToPose',
        goal,
        {
            feedback: (feedback) => {
                const pos = feedback.current_pose?.pose?.position;
                const dist = feedback.distance_remaining;
                if (pos) {
                    logROS(`Nav feedback: pos=(${pos.x?.toFixed(2)}, ${pos.y?.toFixed(2)}), remaining=${dist?.toFixed(2)}m`);
                }
            },
            result: (success, result) => {
                if (success) {
                    logROS('Navigation completed!', 'success');
                } else {
                    logROS('Navigation failed', 'error');
                }
                currentAction = null;
            }
        }
    );
}

function cancelNavigation() {
    if (currentAction) {
        currentAction.cancel();
        logROS('Navigation cancelled');
        currentAction = null;
    }
}

// ========== Presets ==========

function loadSubscriptionPreset(preset) {
    const presets = {
        'rosout': { topic: '/rosout', type: 'rcl_interfaces/msg/Log' },
        'odom': { topic: '/odom', type: 'nav_msgs/msg/Odometry' },
        'scan': { topic: '/scan', type: 'sensor_msgs/msg/LaserScan' },
        'tf': { topic: '/tf', type: 'tf2_msgs/msg/TFMessage' },
        'battery': { topic: '/battery_state', type: 'sensor_msgs/msg/BatteryState' },
        'imu': { topic: '/imu', type: 'sensor_msgs/msg/Imu' },
        'joint_states': { topic: '/joint_states', type: 'sensor_msgs/msg/JointState' },
        'cmd_vel': { topic: '/cmd_vel', type: 'geometry_msgs/msg/Twist' },
        'map': { topic: '/map', type: 'nav_msgs/msg/OccupancyGrid' },
        'amcl_pose': { topic: '/amcl_pose', type: 'geometry_msgs/msg/PoseWithCovarianceStamped' }
    };
    
    const p = presets[preset];
    if (p) {
        document.getElementById('subTopicName').value = p.topic;
        document.getElementById('subMsgType').value = p.type;
    }
}

function loadPublishPreset(preset) {
    const presets = {
        'cmd_vel_fwd': {
            topic: '/cmd_vel',
            type: 'geometry_msgs/msg/Twist',
            data: '{\n  "linear": { "x": 0.2, "y": 0.0, "z": 0.0 },\n  "angular": { "x": 0.0, "y": 0.0, "z": 0.0 }\n}'
        },
        'cmd_vel_stop': {
            topic: '/cmd_vel',
            type: 'geometry_msgs/msg/Twist',
            data: '{\n  "linear": { "x": 0.0, "y": 0.0, "z": 0.0 },\n  "angular": { "x": 0.0, "y": 0.0, "z": 0.0 }\n}'
        },
        'cmd_vel_turn': {
            topic: '/cmd_vel',
            type: 'geometry_msgs/msg/Twist',
            data: '{\n  "linear": { "x": 0.0, "y": 0.0, "z": 0.0 },\n  "angular": { "x": 0.0, "y": 0.0, "z": 0.5 }\n}'
        },
        'initial_pose': {
            topic: '/initialpose',
            type: 'geometry_msgs/msg/PoseWithCovarianceStamped',
            data: '{\n  "header": { "frame_id": "map" },\n  "pose": {\n    "pose": {\n      "position": { "x": 0.0, "y": 0.0, "z": 0.0 },\n      "orientation": { "x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0 }\n    }\n  }\n}'
        }
    };
    
    const p = presets[preset];
    if (p) {
        document.getElementById('pubTopicName').value = p.topic;
        document.getElementById('pubMsgType').value = p.type;
        document.getElementById('pubMsgData').value = p.data;
    }
}

function loadServicePreset(preset) {
    const presets = {
        'get_topics': {
            service: '/rosapi/topics',
            type: 'rosapi_msgs/srv/Topics',
            request: '{}'
        },
        'get_nodes': {
            service: '/rosapi/nodes',
            type: 'rosapi_msgs/srv/Nodes',
            request: '{}'
        },
        'get_params': {
            service: '/rosapi/get_param_names',
            type: 'rosapi_msgs/srv/GetParamNames',
            request: '{}'
        },
        'clear_costmaps': {
            service: '/global_costmap/clear_entirely_global_costmap',
            type: 'nav2_msgs/srv/ClearEntireCostmap',
            request: '{}'
        },
        // Launch Manager Services
        'ugv_get_mode': {
            service: '/ugv/get_mode',
            type: 'ugv_interface/srv/GetMode',
            request: '{}'
        },
        'ugv_switch_idle': {
            service: '/ugv/switch_mode',
            type: 'ugv_interface/srv/SwitchMode',
            request: '{\n  "mode": "idle"\n}'
        },
        'ugv_switch_mapping': {
            service: '/ugv/switch_mode',
            type: 'ugv_interface/srv/SwitchMode',
            request: '{\n  "mode": "mapping"\n}'
        },
        'ugv_switch_navigation': {
            service: '/ugv/switch_mode',
            type: 'ugv_interface/srv/SwitchMode',
            request: '{\n  "mode": "navigation"\n}'
        },
        'ugv_stop_all': {
            service: '/ugv/stop_all',
            type: 'ugv_interface/srv/StopAll',
            request: '{\n  "stop_mode": true,\n  "stop_webrtc": true,\n  "stop_rosbridge": true\n}'
        },
        'ugv_stop_mode_only': {
            service: '/ugv/stop_all',
            type: 'ugv_interface/srv/StopAll',
            request: '{\n  "stop_mode": true,\n  "stop_webrtc": false,\n  "stop_rosbridge": false\n}'
        },
        'ugv_save_map': {
            service: '/ugv/save_map',
            type: 'ugv_interface/srv/MapSave',
            request: '{\n  "map_path": "/home/ws/ugv_ws/maps/my_map"\n}'
        }
    };

    const p = presets[preset];
    if (p) {
        document.getElementById('srvName').value = p.service;
        document.getElementById('srvType').value = p.type;
        document.getElementById('srvRequest').value = p.request;
    }
}

function loadActionPreset(preset) {
    const presets = {
        'navigate': {
            name: '/navigate_to_pose',
            type: 'nav2_msgs/action/NavigateToPose',
            goal: '{\n  "pose": {\n    "header": { "frame_id": "map" },\n    "pose": {\n      "position": { "x": 1.0, "y": 0.0, "z": 0.0 },\n      "orientation": { "x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0 }\n    }\n  }\n}'
        },
        'navigate_through': {
            name: '/navigate_through_poses',
            type: 'nav2_msgs/action/NavigateThroughPoses',
            goal: '{\n  "poses": []\n}'
        },
        'follow_waypoints': {
            name: '/follow_waypoints',
            type: 'nav2_msgs/action/FollowWaypoints',
            goal: '{\n  "poses": []\n}'
        },
        'spin': {
            name: '/spin',
            type: 'nav2_msgs/action/Spin',
            goal: '{\n  "target_yaw": 3.14\n}'
        },
        'backup': {
            name: '/backup',
            type: 'nav2_msgs/action/BackUp',
            goal: '{\n  "target": {\n    "x": -0.5,\n    "y": 0.0\n  },\n  "speed": 0.1\n}'
        }
    };
    
    const p = presets[preset];
    if (p) {
        document.getElementById('actionName').value = p.name;
        document.getElementById('actionType').value = p.type;
        document.getElementById('actionGoal').value = p.goal;
    }
}

// ========== Utility Functions ==========

function logROS(msg, type = 'info') {
    const logEl = document.getElementById('rosLog');
    const time = new Date().toLocaleTimeString();
    const color = type === 'error' ? '#ff6b6b' : type === 'success' ? '#51cf66' : '#74c0fc';
    logEl.innerHTML += `<div style="color: ${color}">[${time}] ${msg}</div>`;
    logEl.scrollTop = logEl.scrollHeight;
    console.log(`[ROS ${type}] ${msg}`);
}

function clearROSLog() {
    document.getElementById('rosLog').innerHTML = '';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize on page load
window.addEventListener('DOMContentLoaded', () => {
    initROSBridge();
});
