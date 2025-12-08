# ROSBridge Protocol Implementation

This document describes how the ROSBridge protocol is implemented in the UGV cloud infrastructure.

## Architecture

```
Operator Browser <-> Fleet DO (Cloudflare) <-> Robot <-> rosbridge_server <-> ROS2
```

## Message Flow & Wrapping Convention

### Critical Rule: **Asymmetric Wrapping**

The system uses **different message formats** for different legs of the journey:

#### 1. Operator → Fleet DO (WebSocket: `/ws/operator?robotId=xxx`)

**OPTION A (Recommended): Wrapped Format**
```javascript
{
    "type": "rosbridge",
    "payload": {
        "op": "subscribe",
        "id": "sub_1_12345",
        "topic": "/odom",
        "type": "nav_msgs/msg/Odometry"
    }
}
```

**OPTION B (Legacy): Raw ROSBridge Format**
```javascript
{
    "op": "subscribe",
    "id": "sub_1_12345",
    "topic": "/odom",
    "type": "nav_msgs/msg/Odometry"
}
```

**Both formats are supported** by the Fleet DO worker for backward compatibility.

---

#### 2. Fleet DO → Robot (WebSocket: `/ws/robot`)

**Always Wrapped Format:**
```javascript
{
    "type": "rosbridge",
    "payload": {
        "op": "subscribe",
        "id": "sub_1_12345",
        "topic": "/odom",
        "type": "nav_msgs/msg/Odometry"
    }
}
```

The robot-side proxy (`rosbridge_proxy.py`) extracts `payload` and forwards to local rosbridge_server.

---

#### 3. Robot → Fleet DO (WebSocket: `/ws/robot`)

**Always Wrapped Format:**
```javascript
{
    "type": "rosbridge",
    "payload": {
        "op": "publish",
        "topic": "/odom",
        "msg": { /* odometry data */ }
    }
}
```

The robot-side proxy wraps all messages from rosbridge_server before sending to Fleet DO.

---

#### 4. Fleet DO → Operator (WebSocket: `/ws/operator?robotId=xxx`)

**Raw ROSBridge Format (Unwrapped):**
```javascript
{
    "op": "publish",
    "topic": "/odom",
    "msg": { /* odometry data */ }
}
```

The Fleet DO unwraps messages before forwarding to operators, so they receive pure ROSBridge protocol messages.

---

## Message Validation

All components validate that rosbridge messages contain the required `"op"` field:

```javascript
// Valid operations per ROSBridge v2.0 protocol:
const VALID_OPS = [
    'advertise',
    'unadvertise',
    'publish',
    'subscribe',
    'unsubscribe',
    'call_service',
    'advertise_service',
    'unadvertise_service',
    'service_response',
    'advertise_action',
    'unadvertise_action',
    'send_action_goal',
    'cancel_action_goal',
    'action_feedback',
    'action_result',
    'set_level',
    'status',
    'fragment',
    'png',
    'cbor',
    'cbor-raw'
];
```

Invalid messages (missing `op` field) are rejected with error messages.

---

## ROSBridge Protocol Compliance

### ✅ Implemented Operations

- **subscribe**: Subscribe to ROS2 topics
- **unsubscribe**: Unsubscribe from topics
- **publish**: Publish messages to topics
- **advertise**: Advertise intent to publish
- **call_service**: Call ROS2 services
- **service_response**: Handle service responses
- **send_action_goal**: Send action goals
- **cancel_action_goal**: Cancel action goals
- **action_feedback**: Receive action feedback
- **action_result**: Receive action results

### ⚠️ Not Yet Implemented

- **unadvertise**: Stop advertising a topic
- **advertise_service**: Expose external service servers
- **unadvertise_service**: Remove service advertisements
- **set_level**: Adjust rosbridge logging level
- **fragment**, **png**, **cbor**, **cbor-raw**: Message compression/fragmentation

---

## Service Response Format

Per ROSBridge v2.0 protocol, service responses have this structure:

```javascript
{
    "op": "service_response",
    "id": "service_123",
    "result": true,        // Boolean: true = success, false = failure
    "values": {            // Actual response data
        "field1": "value1",
        "field2": 42
    }
}
```

**Important**: The `result` field is a **boolean success indicator**, not the response data.

---

## Example Message Flows

### Example 1: Subscribe to Topic

```
Operator:
  → Fleet DO: {"type": "rosbridge", "payload": {"op": "subscribe", "id": "sub_1", "topic": "/odom", "type": "nav_msgs/msg/Odometry"}}

Fleet DO:
  → Robot: {"type": "rosbridge", "payload": {"op": "subscribe", "id": "sub_1", "topic": "/odom", "type": "nav_msgs/msg/Odometry"}}

Robot Proxy:
  → rosbridge_server: {"op": "subscribe", "id": "sub_1", "topic": "/odom", "type": "nav_msgs/msg/Odometry"}

rosbridge_server:
  ← ROS2 /odom topic

rosbridge_server:
  → Robot Proxy: {"op": "publish", "topic": "/odom", "msg": {...}}

Robot Proxy:
  → Fleet DO: {"type": "rosbridge", "payload": {"op": "publish", "topic": "/odom", "msg": {...}}}

Fleet DO:
  → Operator: {"op": "publish", "topic": "/odom", "msg": {...}}
```

### Example 2: Call Service

```
Operator:
  → Fleet DO: {"type": "rosbridge", "payload": {"op": "call_service", "id": "srv_1", "service": "/get_map", "type": "nav_msgs/srv/GetMap", "args": {}}}

Fleet DO:
  → Robot: {"type": "rosbridge", "payload": {"op": "call_service", "id": "srv_1", "service": "/get_map", "type": "nav_msgs/srv/GetMap", "args": {}}}

Robot Proxy:
  → rosbridge_server: {"op": "call_service", "id": "srv_1", "service": "/get_map", "type": "nav_msgs/srv/GetMap", "args": {}}

rosbridge_server:
  ← ROS2 /get_map service

rosbridge_server:
  → Robot Proxy: {"op": "service_response", "id": "srv_1", "result": true, "values": {"map": {...}}}

Robot Proxy:
  → Fleet DO: {"type": "rosbridge", "payload": {"op": "service_response", "id": "srv_1", "result": true, "values": {"map": {...}}}}

Fleet DO:
  → Operator: {"op": "service_response", "id": "srv_1", "result": true, "values": {"map": {...}}}
```

---

## Error Handling

### Invalid Messages

All components reject messages that:
- Cannot be parsed as JSON
- Missing required `"op"` field
- Have invalid `"op"` value (not a string)

Error responses are sent back to the sender:

```javascript
{
    "type": "error",
    "message": "Invalid rosbridge message - missing required 'op' field"
}
```

### Robot Disconnection

When a robot disconnects, all connected operators receive:

```javascript
{
    "type": "robot_disconnected",
    "robotId": "robot-123"
}
```

---

## Implementation Files

- **Frontend Client**: `cloud/frontend/rosbridge_client.js`
- **Frontend UI**: `cloud/frontend/rosbridge_ui.js`
- **Fleet Worker (Proxy)**: `cloud/workers/fleet-worker/src/index.ts`
- **Robot-side Proxy**: `src/ugv_main/webrtc_ros2_bridge/webrtc_ros2_bridge/rosbridge_proxy.py`

---

## References

- [ROSBridge Protocol v2.0 Specification](https://github.com/RobotWebTools/rosbridge_suite/blob/ros2/ROSBRIDGE_PROTOCOL.md)
- [roslibjs Documentation](http://robotwebtools.github.io/roslibjs/current/)
