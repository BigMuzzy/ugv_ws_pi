# Fleet Operator Frontend

Web-based operator console for controlling UGV robots via WebRTC through Cloudflare Calls SFU.

## Current State

The operator console provides two communication channels:

### 1. WebRTC Video & Control (Existing)
- `operator.js` - WebRTC connection via Cloudflare SFU
- Video streaming from robot cameras
- Low-latency cmd_vel via DataChannel

### 2. ROSBridge Proxy (New in Phase 3)
- `rosbridge_client.js` - roslibjs-like client for Fleet DO
- `rosbridge_ui.js` - UI controls for ROS operations
- Full rosbridge protocol support via cloud proxy

## Files

| File | Description |
|------|-------------|
| `index.html` | Main operator console page |
| `operator.js` | WebRTC connection and video/control handling |
| `rosbridge_client.js` | FleetROSBridge client class (roslibjs-compatible API) |
| `rosbridge_ui.js` | ROSBridge UI controller and presets |

## Architecture Overview

```mermaid
graph TB
    subgraph "Cloudflare Edge"
        W[Fleet Worker]
        DO[FleetDO<br/>Durable Object]
        KV[(ROBOT_REGISTRY<br/>KV Store)]
        SFU[Cloudflare Calls<br/>SFU]
    end
    
    subgraph "Robots"
        R1[Robot 1<br/>WebRTC Bridge]
        RB[rosbridge_server<br/>:9090]
    end
    
    subgraph "Operators"
        O1[Operator UI<br/>Browser]
    end
    
    R1 -->|WebSocket| DO
    DO -->|Read/Write| KV
    O1 -->|REST API| W
    W -->|Route| DO
    R1 <-->|Video/Data| SFU
    O1 <-->|Video/Data| SFU
    O1 <-.->|ROSBridge via WS| DO
    R1 <-->|ROSBridge Proxy| RB
```

## ROSBridge Interface Features

### Topic Operations
- **Subscribe** to any ROS topic with message type
- **Publish** messages to topics
- **Throttle rate** control to limit message frequency
- **Presets** for common topics (/rosout, /odom, /scan, etc.)

### Service Calls
- Call ROS services with request data
- View response in JSON format
- Presets for rosapi services

### Action Clients
- Send action goals (NavigateToPose, Spin, BackUp, etc.)
- Receive feedback updates
- Cancel running actions

### Quick Navigation
- Send navigation goals with X, Y, Yaw
- Preset buttons for common movements
- Cancel navigation button

## Usage

1. Open `index.html` in a browser
2. Click "Refresh Robot List" to see online robots
3. Select a robot and click "Connect" (for WebRTC video)
4. Click "Connect ROSBridge" to enable ROS operations
5. Use the tabbed interface:
   - **Subscribe**: Monitor ROS topics
   - **Publish**: Send messages to topics
   - **Services**: Call ROS services
   - **Actions**: Send action goals
   - **Navigation**: Quick navigation controls

## Connection Flow

### Complete Sequence Diagram

```mermaid
sequenceDiagram
    participant O as Operator UI
    participant FW as Fleet Worker
    participant SFU as Cloudflare SFU
    participant R as Robot Bridge

    rect rgba(160, 208, 255, 1)
        Note over O,FW: Phase 1: Discovery
        O->>FW: GET /robots
        FW-->>O: [{id, sfuSessionId, videoTrackName, status}]
        Note over O: User selects robot
    end

    rect rgba(169, 255, 212, 1)
        Note over O,SFU: Phase 2: Session Creation
        O->>SFU: POST /sessions/new
        SFU-->>O: {sessionId: operatorSessionId}
        Note over O: Create RTCPeerConnection<br/>Add recvonly video transceiver
    end

    rect rgba(255, 219, 182, 1)
        Note over O,R: Phase 3: Video Pull & DataChannel Setup
        Note over O: Create temp DataChannel<br/>(ensures SCTP in SDP)
        Note over O: createOffer() + setLocalDescription()
        
        O->>SFU: POST /sessions/{id}/tracks/new<br/>{offer, tracks: [robot's video]}
        SFU-->>O: {sessionDescription: answer}
        Note over O: setRemoteDescription(answer)
        
        O-->>SFU: ICE candidates
        SFU-->>O: ICE candidates
        Note over O,SFU: ICE Connected ✓
        
        O->>SFU: POST /sessions/{id}/datachannels/new<br/>{dataChannels: [{name: 'cmd_vel'}]}
        SFU-->>O: {dataChannels: [{id: 42}]}
        Note over O: Create negotiated DataChannel<br/>id=42, negotiated=true
        
        O->>FW: POST /connect<br/>{robotId, operatorSessionId}
        FW->>R: WS: {action: 'subscribe_cmd',<br/>sessionId, channel: 'cmd_vel'}
        
        R->>SFU: POST /sessions/{id}/datachannels/new<br/>{location: 'remote', sessionId: operator}
        SFU-->>R: {dataChannels: [{id: 42}]}
        Note over R: Create negotiated DataChannel<br/>id=42, negotiated=true
        
        FW-->>O: {success: true}
    end

    rect rgba(206, 255, 206, 1)
        Note over O,R: Phase 4: Active Session
        
        loop Continuous
            R->>SFU: Video frames
            SFU->>O: Video frames
        end
        
        loop On joystick input
            O->>SFU: cmd_vel DataChannel<br/>{linear: {x,y,z}, angular: {x,y,z}}
            SFU->>R: cmd_vel DataChannel
            R->>R: Publish to /cmd_vel topic
        end
    end
```

### Phase Breakdown

#### Phase 1: Discovery
- Operator loads UI and fetches robot list from Fleet Worker
- Fleet Worker returns robots with their SFU session IDs and video track names
- Operator selects a robot to control

#### Phase 2: Session Creation  
- Operator creates their own SFU session via Cloudflare Calls API
- Creates RTCPeerConnection with recvonly video transceiver
- Session is ready but not yet connected to robot

#### Phase 3: Video Pull & DataChannel Setup
- **Critical**: Create temporary DataChannel BEFORE `createOffer()` to include SCTP transport
- Pull robot's video track via SFU `/tracks/new` endpoint
- Complete ICE negotiation and wait for connection
- Register `cmd_vel` DataChannel with SFU to get assigned ID
- **Critical**: Create DataChannel with `negotiated: true` and SFU-assigned ID
- Signal robot via Fleet Worker to subscribe to operator's DataChannel
- Robot creates matching negotiated DataChannel with same ID

#### Phase 4: Active Session
- Video flows: Robot → SFU → Operator (continuous)
- Commands flow: Operator → SFU → Robot (on input)
- Robot publishes received commands to ROS2 `/cmd_vel` topic

## Data Structures

### Robot Registry Entry (Fleet Worker KV)
```json
{
  "id": "robot-abc123",
  "status": "online",
  "sfuSessionId": "sfu-session-uuid",
  "videoTrackName": "robot-abc123-video",
  "dataChannelName": "robot-events",
  "lastSeen": "2024-12-07T10:30:00Z"
}
```

### Command Message (cmd_vel DataChannel)
```json
{
  "linear": { "x": 0.5, "y": 0.0, "z": 0.0 },
  "angular": { "x": 0.0, "y": 0.0, "z": 0.3 }
}
```

### Connect Signal (Fleet Worker → Robot)
```json
{
  "type": "operator_connect",
  "operatorSessionId": "operator-sfu-session-uuid"
}
```

## API Reference

### Fleet Worker Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/robots` | List all registered robots |
| GET | `/robots/:id` | Get specific robot details |
| POST | `/connect` | Signal robot to accept operator connection |
| WS | `/ws/operator` | WebSocket for real-time updates (future) |

### Cloudflare Calls API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/sessions/new` | Create new SFU session |
| POST | `/sessions/:id/tracks/new` | Push/pull media tracks |
| PUT | `/sessions/:id/renegotiate` | Update SDP after changes |
| POST | `/sessions/:id/datachannels/new` | Register DataChannel |

## Critical Implementation Notes

### DataChannel Routing (IMPORTANT!)
Both peers MUST use `negotiated: true` with the SFU-assigned ID:
```javascript
// WRONG - won't route through SFU
const dc = pc.createDataChannel('cmd_vel');

// CORRECT - use ID from /datachannels/new response
const dc = pc.createDataChannel('cmd_vel', {
  negotiated: true,
  id: sfuAssignedId  // from API response
});
```

### SCTP Transport in SDP
The initial SDP offer MUST include SCTP transport for DataChannels to work:
```javascript
// Create a temporary DataChannel BEFORE createOffer()
const temp = pc.createDataChannel('temp');
const offer = await pc.createOffer();  // Now includes SCTP
temp.close();  // Close after offer is created
```

### ICE Connection Timing
Wait for ICE connection before creating negotiated DataChannels:
```javascript
await waitForICE(peerConnection);  // Wait for 'connected' state
// Then register and create DataChannel
```
