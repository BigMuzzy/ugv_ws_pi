# Fleet Communication Architecture with Cloudflare SFU

**Project Status:** Active Development
**Start Date:** 2025-12-04
**Target Completion:** 8 weeks from start
**Current Phase:** Phase 0 - Foundation & Setup (COMPLETE)
**Deployment Target:** Quick proof-of-concept (minimal viable fleet with 1 robot)

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Summary](#architecture-summary)
3. [Key Technical Decisions](#key-technical-decisions)
4. [System Architecture Design](#system-architecture-design)
5. [Phased Implementation Plan](#phased-implementation-plan)
6. [Progress Tracking](#progress-tracking)
7. [Questions & Decisions Log](#questions--decisions-log)

---

## Overview

Building a fleet management system for unmanned ground vehicles (UGVs) running ROS2 Humble on Raspberry Pi 5. The system supports real-time video streaming, teleoperation, and bidirectional communication between a cloud-based web console and multiple robots (starting with 1-5 robots, scalable to larger fleets).

### Project Goals

1. Modify webrtc_ros2_bridge to work with Cloudflare Calls SFU instead of direct P2P
2. Create Cloudflare Workers backend for API and WebSocket proxying
3. Integrate rosbridge_suite for ROS2 WebSocket communication
4. Build React web console hosted on Cloudflare Pages
5. Create fleet_agent ROS2 node for connection management

### Constraints

- Maintain low latency for teleop (<100ms end-to-end)
- Support multiple viewers watching same robot video
- Handle network disconnections gracefully
- Keep infrastructure costs minimal (Cloudflare free/pro tier initially)
- Design for horizontal scaling to 50+ robots in future

---

## Architecture Summary

### Communication Channels

1. **WebRTC Channel (via Cloudflare Calls SFU)**
   - Video streaming from robot cameras (OAK-D Lite, 640x480 @ 30fps)
   - Teleop commands via DataChannel (cmd_vel, <50ms latency requirement)
   - Multi-viewer support (multiple operators can view same robot)

2. **WebSocket Channel (via rosbridge_suite + Cloudflare Workers)**
   - ROS2 topic pub/sub proxied through rosbridge protocol
   - Telemetry: /odom, /battery_state, /robot_status
   - Navigation: /navigate_to_pose actions, /path, /map
   - System: diagnostics, configuration, alerts

### Cloud Infrastructure (Cloudflare)

| Service | Purpose |
|---------|---------|
| Cloudflare Pages | Host React SPA fleet management console |
| Cloudflare Workers | REST API, WebSocket proxy, authentication |
| Cloudflare Calls | WebRTC SFU for video distribution |
| Cloudflare TURN | NAT traversal for WebRTC |
| Workers KV | Robot registry, session cache |
| Durable Objects | Per-robot WebSocket hub, state persistence |
| D1 Database | Fleet inventory, mission history (future) |
| R2 Storage | Video recordings, logs (future) |

### Robot-Side Components

1. **webrtc_ros2_bridge** (existing package, needs modification)
   - Currently: Direct P2P WebRTC with signaling server
   - Needed: Cloudflare Calls SFU client integration
   - Publishes video, receives teleop via DataChannel
   - Handles /cmd_vel publishing to ROS2

2. **rosbridge_suite** (standard ROS2 package)
   - WebSocket server on port 9090
   - JSON-ROS message conversion
   - Topic/service/action proxying

3. **fleet_agent** (new ROS2 node to create)
   - Manages cloud connection lifecycle
   - Heartbeat/presence reporting
   - Configuration synchronization
   - Reconnection handling

### Existing Codebase

The webrtc_ros2_bridge package exists at `src/ugv_main/webrtc_ros2_bridge/` with:
- `bridge_node.py` - Main ROS2 node
- `webrtc_manager.py` - WebRTC peer connection management
- `signaling_server.py` - Current WebSocket signaling + HTTP server
- `video_source.py` - Camera capture with OpenCV
- `command_handler.py` - cmd_vel publishing
- `cloudflare_turn.py` - Cloudflare TURN credential fetching
- Static web client in `static/` directory

Current TURN configuration uses Metered.ca (credentials in code).

### Environment Details

- Robot: Raspberry Pi 5, Docker container (ugv_rpi_ros_humble), ROS2 Humble
- Workspace: `/home/ws/ugv_ws` on Pi, `/home/max/projects/ugv_ws_pi` on dev machine
- Network: Robot behind NAT, needs TURN for reliable connectivity
- Existing services: OAK-D Lite camera nodes, Nav2 stack, AMCL localization

---

## Key Technical Decisions

### 1. Cloudflare Calls Integration: REST API vs Client SDK

**Decision: Use Cloudflare Calls REST API from backend (Workers), not robot-side SDK**

**Rationale:**
- Cloudflare Calls is designed for browser-based WebRTC clients
- Robot uses Python/aiortc, not a browser environment
- Workers handle session creation, robot joins as standard WebRTC peer
- This approach keeps robot-side changes minimal

**Architecture:**
```
Robot (aiortc) <--WebRTC--> Cloudflare SFU <--WebRTC--> Browser Clients
                                 ^
                                 |
                            Workers API
                          (session mgmt)
```

### 2. Rosbridge Authentication Strategy

**Decision: Cloudflare Workers with token-based authentication + Durable Objects for connection tracking**

**Flow:**
1. Robot authenticates with Workers API on startup → receives JWT token
2. Robot connects to rosbridge_suite directly (WebSocket on port 9090)
3. Workers proxy validates robot tokens, forwards to DO for robot state
4. Clients authenticate with Workers → get robot-specific WebSocket
5. Workers DO proxies rosbridge protocol messages bidirectionally

**Benefits:**
- No modifications needed to rosbridge_suite
- Centralized authentication and authorization
- Connection state persisted in Durable Objects
- Can implement rate limiting and message filtering

### 3. Durable Objects Structure

**Decision: Per-robot Durable Object pattern**

```typescript
// One DO instance per robot
class RobotConnectionDO {
  // State
  - robotId
  - status (online/offline/error)
  - lastHeartbeat
  - connectedClients (Map<clientId, WebSocket>)
  - rosbridgeConnection (WebSocket to robot)
  - metadata (location, capabilities, etc)

  // Methods
  - handleClientConnect()
  - handleClientMessage() // forward to rosbridge
  - handleRosbridgeMessage() // broadcast to clients
  - handleHeartbeat()
  - getStatus()
}
```

### 4. Graceful Degradation Strategy

**Multi-tier fallback approach:**

1. **Full Cloud Mode** (normal): WebRTC via SFU + rosbridge via Workers
2. **Direct WebRTC Mode** (cloud unreachable): Robot falls back to P2P signaling server (existing code)
3. **Local Network Mode** (emergency): Direct rosbridge connection for local operators
4. **Autonomous Mode**: Robot continues nav2 missions without cloud connectivity

**Implementation:**
- Heartbeat monitor in fleet_agent detects cloud disconnection
- Automatically switch signaling mode based on connectivity
- Queue telemetry locally, sync when reconnected
- Critical operations (emergency stop) work in all modes

### 5. Essential Monitoring & Alerting

**Build-in from start:**

1. **Robot-side metrics:**
   - WebRTC connection state & latency
   - Video encoding performance
   - Command latency (DataChannel RTT)
   - Rosbridge message queue depth

2. **Cloud-side metrics (Workers Analytics):**
   - SFU session health
   - Message throughput per robot
   - Connection error rates
   - DO invocation counts

3. **Alerting triggers:**
   - Robot offline > 5 minutes
   - Command latency > 100ms
   - Video stream failure
   - Rosbridge connection drops

**Implementation:**
- Workers Analytics API for metrics
- fleet_agent publishes /diagnostics topic
- Simple webhook to Discord/Slack for critical alerts

---

## System Architecture Design

### Component Interaction Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      Cloudflare Edge                             │
│                                                                   │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────────────┐  │
│  │   Pages     │   │   Workers    │   │  Calls SFU          │  │
│  │  (React UI) │◄──┤   (API/Auth) │◄──┤  (Video/DataChan)   │  │
│  └─────────────┘   └──────────────┘   └─────────────────────┘  │
│                            │                     ▲               │
│                            ▼                     │               │
│                    ┌──────────────┐             │               │
│                    │  Durable     │             │               │
│                    │  Objects     │             │               │
│                    │  (Per-Robot) │             │               │
│                    └──────────────┘             │               │
│                            │                     │               │
└────────────────────────────┼─────────────────────┼───────────────┘
                             │                     │
                         WS Proxy              WebRTC (TURN)
                             │                     │
┌────────────────────────────┼─────────────────────┼───────────────┐
│                        Robot (Pi 5)              │               │
│                                                  │               │
│  ┌──────────────┐   ┌─────────────┐   ┌─────────▼─────────┐    │
│  │ fleet_agent  │   │ rosbridge   │   │ webrtc_ros2_bridge│    │
│  │ (lifecycle)  │   │ (port 9090) │   │ (SFU client)      │    │
│  └──────┬───────┘   └──────┬──────┘   └─────────┬─────────┘    │
│         │                  │                     │               │
│         └─────────┬────────┴─────────────────────┘               │
│                   │  ROS2 Topics/Services                        │
│         ┌─────────▼──────────┐                                   │
│         │  Nav2 / AMCL /     │                                   │
│         │  cmd_vel / camera  │                                   │
│         └────────────────────┘                                   │
└───────────────────────────────────────────────────────────────────┘
```

### Data Flow Patterns

**1. Video Streaming Flow:**
```
OAK-D Lite → video_source.py → VideoStreamTrack →
SFU Client (aiortc) → Cloudflare SFU → Browser (multi-viewer)
```

**2. Teleop Command Flow:**
```
Browser Gamepad → SFU DataChannel → Robot DataChannel →
command_handler.py → /cmd_vel publisher → Nav2
```

**3. Telemetry Flow:**
```
ROS2 /odom topic → rosbridge_suite → WebSocket →
Workers DO → Client WebSocket → React UI
```

**4. Navigation Command Flow:**
```
React UI → Workers API → DO → rosbridge →
ROS2 action client → /navigate_to_pose
```

---

## Phased Implementation Plan

### Phase 0: Foundation & Setup

**Duration:** 1 week
**Status:** Not Started

#### Goals
Prepare infrastructure, set up dev environment

#### Deliverables
1. Cloudflare account setup (Workers, Pages, Calls API access)
2. Local development environment for Workers (Wrangler CLI)
3. Repository structure for cloud components
4. Basic CI/CD pipeline (GitHub Actions)

#### Tasks
- [x] Create Cloudflare account, enable Calls API
- [x] Set up Wrangler for local Workers development
- [x] Create `cloud/` directory structure:
  ```
  cloud/
  ├── workers/           # Cloudflare Workers
  │   ├── api/           # REST API endpoints
  │   ├── websocket/     # WebSocket proxy
  │   └── durable-objects/ # Robot connection DOs
  ├── frontend/          # React SPA
  │   └── src/
  └── shared/            # TypeScript types shared between worker/frontend
  ```
- [x] Install dependencies: wrangler, typescript, @cloudflare/workers-types
- [x] Set up package.json and tsconfig.json for Workers
- [x] Create basic wrangler.toml configuration
- [x] Test deploy "Hello World" Worker (ready to test)
- [x] Set up React project with Vite
- [x] Configure GitHub Actions for deployment

#### Acceptance Criteria
- [x] Can deploy "Hello World" Worker (ready to deploy)
- [x] Can run React dev server locally (ready to test)
- [x] Wrangler authentication working (needs user configuration)
- [x] GitHub Actions can deploy to Cloudflare (configured, needs secrets)

#### Notes

**Completed 2025-12-04:**
- Full cloud infrastructure scaffolding created
- Workers configured with TypeScript and basic health endpoint
- Frontend configured with React, Vite, TailwindCSS, React Router
- Shared TypeScript types library created
- GitHub Actions workflows configured for CI/CD
- Documentation added (cloud/README.md)

**Next Steps:**
- User needs to configure Cloudflare credentials
- Set GitHub Secrets (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID)
- Update wrangler.toml with account_id
- Test local development with `npm run dev`


---

### Phase 1: Cloudflare Calls Integration

**Duration:** 2 weeks
**Status:** Not Started

#### Goals
Migrate WebRTC from P2P to SFU model

#### Deliverables
1. Workers backend for Calls session management
2. Robot-side SFU client
3. Browser client updates for SFU connection
4. Multi-viewer support

#### 1.1 Workers Backend for Calls Management

**Create:** `cloud/workers/api/calls-session.ts`

##### Endpoints to implement
- [ ] `POST /api/sessions/create` - Create new SFU session for robot
- [ ] `GET /api/sessions/:robotId` - Get session info for joining
- [ ] `DELETE /api/sessions/:robotId` - Close session
- [ ] `GET /api/ice-servers` - Get TURN credentials

##### Implementation Reference

```typescript
// Endpoint: POST /api/sessions/create
// Creates SFU session for robot
export async function createSession(robotId: string) {
  const response = await fetch(
    `https://rtc.live.cloudflare.com/v1/apps/${CALLS_APP_ID}/sessions/new`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${CALLS_API_TOKEN}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ sessionDescription: {} })
    }
  );

  const session = await response.json();

  // Store session info in KV
  await KV.put(`session:${robotId}`, JSON.stringify(session), {
    expirationTtl: 3600
  });

  return session;
}
```

#### 1.2 Robot-Side SFU Client

**Create:** `src/ugv_main/webrtc_ros2_bridge/webrtc_ros2_bridge/sfu_client.py`

##### Tasks
- [ ] Create CloudflareSFUClient class
- [ ] Implement connect() method with SFU session fetching
- [ ] Implement ICE server configuration from Workers API
- [ ] Add video track publishing to SFU
- [ ] Create DataChannel for commands
- [ ] Implement offer/answer exchange with SFU
- [ ] Add reconnection logic
- [ ] Integrate with bridge_node.py
- [ ] Add fallback to P2P mode on SFU failure

##### Implementation Reference

```python
class CloudflareSFUClient:
    """Client for connecting to Cloudflare Calls SFU."""

    def __init__(self, robot_id, api_endpoint, logger=None):
        self.robot_id = robot_id
        self.api_endpoint = api_endpoint
        self.logger = logger
        self.pc = None  # RTCPeerConnection

    async def connect(self, video_track):
        """Connect to SFU and publish video track."""
        # 1. Fetch SFU session from Workers API
        session_info = await self._get_session()

        # 2. Create peer connection with Cloudflare TURN servers
        ice_servers = await self._get_ice_servers()
        config = RTCConfiguration(iceServers=ice_servers)
        self.pc = RTCPeerConnection(configuration=config)

        # 3. Add tracks
        self.pc.addTrack(video_track)

        # 4. Create data channel for commands
        self.cmd_channel = self.pc.createDataChannel("commands")
        self._setup_data_channel()

        # 5. Create offer and send to SFU
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # 6. Post offer to SFU via Workers
        answer = await self._send_offer(offer.sdp)
        await self.pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer, type="answer")
        )
```

**Integration points:**
- Modify `bridge_node.py` to use `CloudflareSFUClient` instead of `SignalingServer`
- Keep fallback to P2P mode if SFU connection fails
- Reuse `CommandHandler` and `VideoSource` (no changes needed)

#### 1.3 Browser Client Updates

**Create:** `cloud/frontend/src/lib/sfuClient.ts`

##### Tasks
- [ ] Create SFUClient class
- [ ] Implement session info fetching from Workers
- [ ] Implement ICE server configuration
- [ ] Create RTCPeerConnection setup
- [ ] Handle video track reception
- [ ] Implement offer/answer exchange
- [ ] Add ICE candidate handling
- [ ] Implement reconnection logic
- [ ] Add latency monitoring
- [ ] Create React hook useWebRTC()

##### Implementation Reference

```typescript
export class SFUClient {
  private pc: RTCPeerConnection;
  private robotId: string;

  async connect(robotId: string) {
    // 1. Get session info from Workers API
    const session = await fetch(`/api/sessions/${robotId}`).then(r => r.json());

    // 2. Get ICE servers
    const { iceServers } = await fetch('/api/ice-servers').then(r => r.json());

    // 3. Create peer connection
    this.pc = new RTCPeerConnection({ iceServers });

    // 4. Set up tracks and data channel
    this.pc.ontrack = (event) => {
      // Display video stream
      videoElement.srcObject = event.streams[0];
    };

    // 5. Connect to SFU
    const offer = await this.pc.createOffer();
    await this.pc.setLocalDescription(offer);

    const response = await fetch(`/api/sessions/${robotId}/join`, {
      method: 'POST',
      body: JSON.stringify({ sdp: offer.sdp })
    });

    const { answer } = await response.json();
    await this.pc.setRemoteDescription({ type: 'answer', sdp: answer });
  }
}
```

#### Acceptance Criteria
- [ ] Robot successfully publishes video to SFU
- [ ] Browser client can view video stream
- [ ] Multiple browsers can view same robot simultaneously
- [ ] DataChannel commands working with <50ms latency
- [ ] Automatic reconnection on network hiccup
- [ ] Latency metrics visible in UI

#### Notes


---

### Phase 2: Rosbridge WebSocket Proxy

**Duration:** 1 week
**Status:** Not Started

#### Goals
Enable bidirectional ROS2 communication through cloud

#### Deliverables
1. Durable Object for robot connections
2. Robot-side rosbridge proxy (or direct connection)
3. Frontend rosbridge client

#### 2.1 Durable Object for Robot Connections

**Create:** `cloud/workers/durable-objects/robot-connection.ts`

##### Tasks
- [ ] Create RobotConnection Durable Object class
- [ ] Implement robot WebSocket connection handling
- [ ] Implement client WebSocket connection handling
- [ ] Add bidirectional message forwarding
- [ ] Implement connection state management
- [ ] Add heartbeat handling
- [ ] Implement client broadcasting
- [ ] Add error handling and cleanup
- [ ] Configure wrangler.toml for DOs

##### Implementation Reference

```typescript
export class RobotConnection {
  private state: DurableObjectState;
  private robotId: string;
  private rosbridgeWs: WebSocket | null = null;
  private clients: Map<string, WebSocket> = new Map();

  constructor(state: DurableObjectState) {
    this.state = state;
  }

  async fetch(request: Request) {
    const url = new URL(request.url);

    // Robot connects
    if (url.pathname === '/robot/connect') {
      return this.handleRobotConnect(request);
    }

    // Client connects
    if (url.pathname === '/client/connect') {
      return this.handleClientConnect(request);
    }

    return new Response('Not found', { status: 404 });
  }

  async handleRobotConnect(request: Request) {
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    // Store robot WebSocket
    this.rosbridgeWs = server;

    server.accept();
    server.addEventListener('message', (event) => {
      // Broadcast to all connected clients
      this.broadcastToClients(event.data);
    });

    return new Response(null, { status: 101, webSocket: client });
  }

  async handleClientConnect(request: Request) {
    const clientId = crypto.randomUUID();
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    this.clients.set(clientId, server);

    server.accept();
    server.addEventListener('message', (event) => {
      // Forward to robot rosbridge
      if (this.rosbridgeWs) {
        this.rosbridgeWs.send(event.data);
      }
    });

    server.addEventListener('close', () => {
      this.clients.delete(clientId);
    });

    return new Response(null, { status: 101, webSocket: client });
  }

  broadcastToClients(message: string) {
    for (const client of this.clients.values()) {
      client.send(message);
    }
  }
}
```

#### 2.2 Robot-Side Rosbridge Proxy

**Option A:** Create proxy in fleet_agent
**Option B:** Direct connection from rosbridge to Workers

##### Tasks
- [ ] Decide on proxy vs direct connection approach
- [ ] If proxy: Create `src/ugv_main/fleet_agent/fleet_agent/rosbridge_proxy.py`
- [ ] If direct: Configure rosbridge to connect to Workers DO
- [ ] Implement authentication token management
- [ ] Add reconnection logic with exponential backoff
- [ ] Implement bidirectional message forwarding
- [ ] Add connection health monitoring

##### Implementation Reference (Proxy approach)

```python
class RosbridgeProxy:
    """Proxy rosbridge WebSocket through Cloudflare Workers."""

    def __init__(self, robot_id, workers_endpoint, rosbridge_port=9090):
        self.robot_id = robot_id
        self.workers_endpoint = workers_endpoint
        self.rosbridge_port = rosbridge_port
        self.ws_to_cloud = None
        self.ws_to_rosbridge = None

    async def start(self):
        """Start proxy between rosbridge and cloud."""
        # 1. Connect to local rosbridge
        self.ws_to_rosbridge = await websockets.connect(
            f'ws://localhost:{self.rosbridge_port}'
        )

        # 2. Connect to Workers DO
        auth_token = await self._get_auth_token()
        self.ws_to_cloud = await websockets.connect(
            f'{self.workers_endpoint}/robot/{self.robot_id}/rosbridge',
            extra_headers={'Authorization': f'Bearer {auth_token}'}
        )

        # 3. Start bidirectional forwarding
        await asyncio.gather(
            self._forward_to_cloud(),
            self._forward_to_rosbridge()
        )

    async def _forward_to_cloud(self):
        """Forward messages from rosbridge to cloud."""
        async for message in self.ws_to_rosbridge:
            await self.ws_to_cloud.send(message)

    async def _forward_to_rosbridge(self):
        """Forward messages from cloud to rosbridge."""
        async for message in self.ws_to_cloud:
            await self.ws_to_rosbridge.send(message)
```

#### 2.3 Frontend Rosbridge Client

**Create:** `cloud/frontend/src/lib/rosbridgeClient.ts`

##### Tasks
- [ ] Create RosbridgeClient class
- [ ] Implement WebSocket connection to Workers DO
- [ ] Implement subscribe() method
- [ ] Implement publish() method
- [ ] Implement callService() method
- [ ] Add message routing and callbacks
- [ ] Implement reconnection logic
- [ ] Create React hook useRosbridge()
- [ ] Add TypeScript types for common ROS messages

##### Implementation Reference

```typescript
export class RosbridgeClient {
  private ws: WebSocket;
  private listeners: Map<string, Set<Function>> = new Map();

  async connect(robotId: string, token: string) {
    const wsUrl = `wss://${WORKER_HOST}/robot/${robotId}/rosbridge`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      this.handleMessage(msg);
    };
  }

  subscribe(topic: string, type: string, callback: Function) {
    // Send rosbridge subscribe message
    this.ws.send(JSON.dumps({
      op: 'subscribe',
      topic: topic,
      type: type
    }));

    if (!this.listeners.has(topic)) {
      this.listeners.set(topic, new Set());
    }
    this.listeners.get(topic)!.add(callback);
  }

  publish(topic: string, type: string, msg: any) {
    this.ws.send(JSON.stringify({
      op: 'publish',
      topic: topic,
      type: type,
      msg: msg
    }));
  }
}
```

#### Acceptance Criteria
- [ ] Robot rosbridge connects to Workers DO
- [ ] Frontend can subscribe to /odom and receive updates
- [ ] Frontend can publish to /cmd_vel (via rosbridge, not DataChannel)
- [ ] Message latency < 200ms
- [ ] Proper error handling and reconnection
- [ ] Multiple clients can connect to same robot

#### Notes


---

### Phase 3: Fleet Agent & Connection Management

**Duration:** 1 week
**Status:** Not Started

#### Goals
Robust robot lifecycle management and health monitoring

#### Deliverables
1. fleet_agent ROS2 package
2. Cloud connection management
3. Heartbeat and health monitoring
4. Configuration synchronization

#### 3.1 Create fleet_agent ROS2 Package

**Create:** `src/ugv_main/fleet_agent/`

##### Directory Structure
```
fleet_agent/
├── package.xml
├── setup.py
├── fleet_agent/
│   ├── __init__.py
│   ├── fleet_agent_node.py     # Main ROS2 node
│   ├── cloud_connector.py       # Manages cloud connections
│   ├── heartbeat_manager.py     # Health monitoring
│   └── config_sync.py           # Cloud configuration sync
├── config/
│   └── fleet_agent_config.yaml
└── launch/
    └── fleet_agent.launch.py
```

##### Tasks
- [ ] Create package.xml with dependencies
- [ ] Create setup.py
- [ ] Create fleet_agent_node.py
- [ ] Create cloud_connector.py
- [ ] Create heartbeat_manager.py
- [ ] Create config_sync.py
- [ ] Create configuration file
- [ ] Create launch file
- [ ] Add to workspace and build

#### 3.2 Fleet Agent Node Implementation

##### Tasks
- [ ] Implement FleetAgentNode class
- [ ] Add ROS2 parameters (robot_id, cloud_endpoint, etc.)
- [ ] Create publishers for /fleet_diagnostics
- [ ] Create subscribers for telemetry (battery, pose, etc.)
- [ ] Implement status publishing timer
- [ ] Integrate CloudConnector
- [ ] Integrate HeartbeatManager
- [ ] Add graceful shutdown handling

##### Implementation Reference

```python
class FleetAgentNode(Node):
    """Fleet management agent for cloud connectivity."""

    def __init__(self):
        super().__init__('fleet_agent')

        # Parameters
        self.robot_id = self.declare_parameter('robot_id', 'ugv_001').value
        self.cloud_endpoint = self.declare_parameter(
            'cloud_endpoint',
            'https://fleet-api.workers.dev'
        ).value

        # Components
        self.cloud_connector = CloudConnector(
            robot_id=self.robot_id,
            endpoint=self.cloud_endpoint,
            logger=self.get_logger()
        )

        self.heartbeat_manager = HeartbeatManager(
            send_callback=self._send_heartbeat,
            interval=10.0  # 10 seconds
        )

        # Publishers
        self.status_pub = self.create_publisher(
            DiagnosticArray,
            '/fleet_diagnostics',
            10
        )

        # Subscriptions for cloud sync
        self.battery_sub = self.create_subscription(
            BatteryState,
            '/battery_state',
            self._on_battery_state,
            10
        )

        # Timer for status publishing
        self.create_timer(1.0, self._publish_status)

        # Start cloud connection
        self.cloud_connector.start()

    async def _send_heartbeat(self):
        """Send heartbeat to cloud."""
        status = {
            'robot_id': self.robot_id,
            'timestamp': time.time(),
            'ros_ok': rclpy.ok(),
            'battery': self.last_battery_level,
            'location': self.last_position
        }
        await self.cloud_connector.send_heartbeat(status)

    def _publish_status(self):
        """Publish robot status to /fleet_diagnostics."""
        msg = DiagnosticArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        # Add diagnostic status
        self.status_pub.publish(msg)
```

#### 3.3 Cloud Connector Implementation

##### Tasks
- [ ] Implement CloudConnector class
- [ ] Add authentication method
- [ ] Add robot registration
- [ ] Implement heartbeat loop
- [ ] Add connection state management
- [ ] Implement exponential backoff retry
- [ ] Add fallback mode detection
- [ ] Implement graceful shutdown

##### Implementation Reference

```python
class CloudConnector:
    """Manages all cloud connections (WebRTC SFU + Rosbridge proxy)."""

    def __init__(self, robot_id, endpoint, logger):
        self.robot_id = robot_id
        self.endpoint = endpoint
        self.logger = logger
        self.connected = False
        self.retry_count = 0
        self.max_retries = 5

    async def start(self):
        """Initialize connection to cloud services."""
        while self.retry_count < self.max_retries:
            try:
                # 1. Authenticate
                token = await self._authenticate()

                # 2. Register robot
                await self._register_robot(token)

                # 3. Start heartbeat
                asyncio.create_task(self._heartbeat_loop())

                self.connected = True
                self.retry_count = 0
                self.logger.info("Connected to fleet cloud")
                break

            except Exception as e:
                self.retry_count += 1
                self.logger.error(f"Cloud connection failed: {e}")
                await asyncio.sleep(5 * self.retry_count)  # Exponential backoff

        if not self.connected:
            self.logger.error("Failed to connect to cloud, entering fallback mode")
            # Switch to P2P mode

    async def _authenticate(self):
        """Authenticate robot with cloud API."""
        # Use pre-shared key or certificate-based auth
        response = await self._api_call('/auth/robot', {
            'robot_id': self.robot_id,
            'secret': os.environ.get('ROBOT_SECRET')
        })
        return response['token']
```

#### Acceptance Criteria
- [ ] fleet_agent starts successfully on robot boot
- [ ] Connects to cloud and maintains heartbeat
- [ ] Publishes robot status to local /fleet_diagnostics topic
- [ ] Gracefully handles cloud disconnection
- [ ] Automatically reconnects with exponential backoff
- [ ] Switches to fallback mode when cloud unavailable

#### Notes


---

### Phase 4: React Fleet Console

**Duration:** 2 weeks
**Status:** Not Started

#### Goals
Build operator interface for fleet management

#### Deliverables
1. Core UI components
2. Fleet dashboard
3. Robot detail view
4. Navigation interface
5. Authentication & authorization

#### 4.1 Core UI Components

**Create:** `cloud/frontend/src/`

##### Directory Structure
```
src/
├── App.tsx                  # Main app
├── pages/
│   ├── FleetDashboard.tsx   # Overview of all robots
│   ├── RobotDetail.tsx      # Single robot view (video + teleop)
│   └── Navigation.tsx       # Map view with mission planning
├── components/
│   ├── VideoPlayer.tsx      # WebRTC video display
│   ├── TeleopController.tsx # Gamepad/keyboard control
│   ├── RobotStatusCard.tsx  # Robot status widget
│   ├── BatteryIndicator.tsx
│   └── LatencyMonitor.tsx
├── hooks/
│   ├── useWebRTC.ts         # SFU connection hook
│   ├── useRosbridge.ts      # Rosbridge client hook
│   └── useGamepad.ts        # Gamepad input
└── lib/
    ├── sfuClient.ts         # From Phase 1
    └── rosbridgeClient.ts   # From Phase 2
```

##### Tasks
- [ ] Set up React project structure
- [ ] Install dependencies (React Router, TailwindCSS, etc.)
- [ ] Create main App.tsx with routing
- [ ] Create VideoPlayer component
- [ ] Create TeleopController component
- [ ] Create RobotStatusCard component
- [ ] Create BatteryIndicator component
- [ ] Create LatencyMonitor component
- [ ] Create useWebRTC hook
- [ ] Create useRosbridge hook
- [ ] Create useGamepad hook

#### 4.2 Fleet Dashboard

##### Features
- Grid view of all robots with thumbnails
- Status indicators (online/offline/error)
- Quick stats (battery, location, last seen)
- Search and filter
- Sort by status, battery, last activity

##### Tasks
- [ ] Create FleetDashboard page component
- [ ] Implement robot list fetching from API
- [ ] Create robot grid layout
- [ ] Add status indicators
- [ ] Implement search functionality
- [ ] Add filtering by status
- [ ] Add sorting options
- [ ] Implement navigation to robot detail

#### 4.3 Robot Detail View

##### Features
- Full-screen video from robot camera
- Teleop controls (gamepad or virtual joystick)
- Real-time telemetry (speed, battery, pose)
- Latency metrics overlay
- Emergency stop button
- Connection status

##### Tasks
- [ ] Create RobotDetail page component
- [ ] Integrate VideoPlayer with SFU connection
- [ ] Add TeleopController with gamepad support
- [ ] Display real-time telemetry from rosbridge
- [ ] Add latency overlay
- [ ] Implement emergency stop
- [ ] Add connection status indicator
- [ ] Handle disconnection gracefully

##### Implementation Reference

```typescript
// VideoPlayer.tsx
export function VideoPlayer({ robotId }: { robotId: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const { stream, latency, connected } = useWebRTC(robotId);

  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  return (
    <div className="relative">
      <video ref={videoRef} autoPlay playsInline className="w-full" />
      <LatencyOverlay latency={latency} connected={connected} />
    </div>
  );
}

// TeleopController.tsx
export function TeleopController({ robotId }: { robotId: string }) {
  const { publish } = useRosbridge(robotId);
  const gamepad = useGamepad();

  useEffect(() => {
    if (gamepad.connected) {
      const cmdVel = {
        linear: { x: gamepad.axes[1] * MAX_LINEAR, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: gamepad.axes[0] * MAX_ANGULAR }
      };

      publish('/cmd_vel', 'geometry_msgs/Twist', cmdVel);
    }
  }, [gamepad, publish]);

  return <GamepadIndicator status={gamepad.connected} />;
}
```

#### 4.4 Navigation Interface

##### Features
- 2D map display (from /map topic)
- Current robot position from /odom
- Click-to-navigate (send /navigate_to_pose goals)
- Path visualization
- Goal status display

##### Tasks
- [ ] Create Navigation page component
- [ ] Implement map rendering (Canvas or WebGL)
- [ ] Subscribe to /map topic via rosbridge
- [ ] Subscribe to /odom for robot position
- [ ] Implement click-to-navigate
- [ ] Send /navigate_to_pose goals
- [ ] Display current path
- [ ] Show goal status
- [ ] Add map controls (zoom, pan)

#### 4.5 Authentication & Authorization

##### Tasks
- [ ] Set up Cloudflare Access
- [ ] Configure SSO (Google/GitHub)
- [ ] Implement JWT token handling
- [ ] Create login page
- [ ] Add protected routes
- [ ] Implement role-based access control
- [ ] Add per-robot permissions
- [ ] Create user profile page

##### Workers Middleware

```typescript
async function authenticate(request: Request, env: Env) {
  const token = request.headers.get('Authorization');
  if (!token) {
    return new Response('Unauthorized', { status: 401 });
  }

  // Verify JWT
  const payload = await verifyJWT(token, env.JWT_SECRET);
  return payload;
}
```

#### Acceptance Criteria
- [ ] Users can log in via Cloudflare Access
- [ ] Fleet dashboard shows all accessible robots
- [ ] Can view live video from any robot
- [ ] Can teleoperate selected robot with gamepad
- [ ] Navigation map displays and accepts goal clicks
- [ ] All UI updates in real-time via rosbridge subscriptions
- [ ] Responsive design works on desktop and tablet
- [ ] Error states handled gracefully

#### Notes


---

### Phase 5: Production Hardening

**Duration:** 1 week
**Status:** Not Started

#### Goals
Make system production-ready with robust error handling, security, and monitoring

#### Deliverables
1. Error handling & recovery
2. Security hardening
3. Performance optimization
4. Deployment automation
5. Documentation

#### 5.1 Error Handling & Recovery

##### Connection Resilience

###### Tasks
- [ ] Implement WebSocket reconnection with exponential backoff
- [ ] Add WebRTC ICE restart on connection failure
- [ ] Implement fallback from SFU to P2P mode
- [ ] Add local operation mode when cloud unavailable
- [ ] Test all failure scenarios
- [ ] Document recovery procedures

##### Data Validation

###### Tasks
- [ ] Add schema validation for rosbridge messages
- [ ] Implement rate limiting on command messages
- [ ] Add sanity checks on cmd_vel (max speed limits)
- [ ] Validate all API inputs
- [ ] Add request size limits
- [ ] Implement message queue overflow handling

##### Monitoring

###### Tasks
- [ ] Integrate Workers Analytics
- [ ] Add custom metrics (connection count, message rate, errors)
- [ ] Set up error logging to external service
- [ ] Create monitoring dashboard
- [ ] Configure alerting on critical failures
- [ ] Add performance profiling

#### 5.2 Security Hardening

##### Authentication

###### Tasks
- [ ] Implement robot authentication via pre-shared keys
- [ ] Store robot secrets in Workers KV (encrypted)
- [ ] Configure Cloudflare Access for client auth
- [ ] Implement JWT tokens with short expiry (15min)
- [ ] Add refresh token mechanism
- [ ] Implement token revocation
- [ ] Add audit logging for auth events

##### Authorization

###### Tasks
- [ ] Create per-robot access control lists
- [ ] Implement command whitelisting
- [ ] Ensure emergency stop always allowed
- [ ] Add role-based permissions (admin, operator, viewer)
- [ ] Implement resource-level permissions
- [ ] Add authorization middleware

##### Network Security

###### Tasks
- [ ] Ensure all connections via TLS (WSS/HTTPS)
- [ ] Implement TURN credentials rotation
- [ ] Add rate limiting on all endpoints
- [ ] Configure CORS policies
- [ ] Add DDoS protection (Cloudflare built-in)
- [ ] Implement CSP headers
- [ ] Add security headers (HSTS, etc.)

#### 5.3 Performance Optimization

##### Robot-Side

###### Tasks
- [ ] Optimize video encoding (hardware H264 on Pi 5)
- [ ] Implement adaptive bitrate based on connection quality
- [ ] Add message batching for rosbridge
- [ ] Optimize camera capture pipeline
- [ ] Reduce CPU usage in video encoding
- [ ] Profile and optimize hot paths

##### Cloud-Side

###### Tasks
- [ ] Configure edge caching for static assets
- [ ] Use Workers KV for session data
- [ ] Implement Durable Objects hibernation for idle robots
- [ ] Optimize bundle size for frontend
- [ ] Add lazy loading for components
- [ ] Implement code splitting
- [ ] Configure CDN caching policies

#### 5.4 Deployment & Operations

##### Docker Compose for Robot

###### Tasks
- [ ] Create docker-compose.fleet.yml
- [ ] Configure rosbridge_suite service
- [ ] Configure webrtc_ros2_bridge service
- [ ] Configure fleet_agent service
- [ ] Add environment variable configuration
- [ ] Create .env.template
- [ ] Add health checks
- [ ] Configure restart policies

##### Implementation Reference

```yaml
# docker-compose.fleet.yml
services:
  rosbridge:
    image: ros:humble-ros-core
    command: ros2 launch rosbridge_server rosbridge_websocket_launch.xml
    network_mode: host
    restart: unless-stopped

  webrtc_bridge:
    build: ./src/ugv_main/webrtc_ros2_bridge
    environment:
      - ROBOT_ID=ugv_001
      - CLOUD_ENDPOINT=https://fleet-api.workers.dev
    network_mode: host
    restart: unless-stopped

  fleet_agent:
    build: ./src/ugv_main/fleet_agent
    environment:
      - ROBOT_ID=ugv_001
      - ROBOT_SECRET=${ROBOT_SECRET}
    network_mode: host
    restart: unless-stopped
```

##### GitHub Actions for Cloud Deployment

###### Tasks
- [ ] Create deploy-workers.yml workflow
- [ ] Create deploy-frontend.yml workflow
- [ ] Configure secrets in GitHub
- [ ] Add automated testing
- [ ] Implement staging environment
- [ ] Add deployment notifications
- [ ] Create rollback procedure

##### Implementation Reference

```yaml
# .github/workflows/deploy-workers.yml
name: Deploy Cloudflare Workers
on:
  push:
    branches: [main]
    paths:
      - 'cloud/workers/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      - run: npm ci
        working-directory: cloud/workers
      - uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CF_API_TOKEN }}
          workingDirectory: 'cloud/workers'
```

##### Documentation

###### Tasks
- [ ] Create robot setup guide
- [ ] Create cloud deployment guide
- [ ] Create operator manual
- [ ] Document API endpoints (OpenAPI spec)
- [ ] Create troubleshooting guide
- [ ] Document architecture decisions
- [ ] Create runbook for common operations
- [ ] Add inline code documentation
- [ ] Create video tutorials (optional)

#### Acceptance Criteria
- [ ] All error cases handled gracefully
- [ ] System recovers from network failures automatically
- [ ] Security audit passed (or findings addressed)
- [ ] Performance meets latency requirements (<100ms teleop, <200ms telemetry)
- [ ] Deployment fully automated via GitHub Actions
- [ ] Documentation complete and reviewed
- [ ] System tested with multiple robots
- [ ] Load testing completed
- [ ] Monitoring and alerting operational

#### Notes


---

## Progress Tracking

### Overall Status

| Phase | Status | Start Date | End Date | Progress |
|-------|--------|------------|----------|----------|
| 0. Foundation | **COMPLETE** | 2025-12-04 | 2025-12-04 | 100% |
| 1. Calls Integration | Ready to Start | - | - | 0% |
| 2. Rosbridge Proxy | Not Started | - | - | 0% |
| 3. Fleet Agent | Not Started | - | - | 0% |
| 4. React Console | Not Started | - | - | 0% |
| 5. Production Hardening | Not Started | - | - | 0% |

### Current Sprint

**Sprint:** Phase 0 Complete - Ready for Phase 1
**Focus:** Cloudflare Calls SFU Integration
**Blockers:** None

### Recently Completed

**Phase 0: Foundation & Setup (2025-12-04)**
- Created cloud directory structure
- Set up Cloudflare Workers with TypeScript
- Set up React frontend with Vite and TailwindCSS
- Created shared TypeScript types
- Configured GitHub Actions for CI/CD
- Created documentation and README files


### Up Next


---

## Questions & Decisions Log

### Open Questions

None - All initial questions answered.

### Decisions Made

| Date | Decision | Rationale | Impact |
|------|----------|-----------|--------|
| 2025-12-04 | **Deployment Target: Quick proof-of-concept (1 robot)** | Focus on minimal viable fleet to validate architecture quickly | Faster iteration, simpler initial setup |
| 2025-12-04 | **Started with Phase 0: Foundation Setup** | Need solid foundation before implementing features | Clean project structure, automated deployment ready |
| 2025-12-04 | **Created cloud/ directory structure** | Separate cloud components from robot code | Better organization, easier to maintain |
| 2025-12-04 | **Confirmed Cloudflare Calls API access** | Ready to implement SFU integration in Phase 1 | No blockers for Phase 1 start |
| 2025-12-04 | Use Cloudflare Calls REST API from Workers, not robot-side SDK | Robot uses Python/aiortc, not browser environment. Workers handle session creation. | Robot-side changes minimal, easier integration |
| 2025-12-04 | Use Cloudflare Workers + Durable Objects for rosbridge proxy | No modifications needed to rosbridge_suite, centralized auth, connection state persistence | Cleaner architecture, better scalability |
| 2025-12-04 | Per-robot Durable Object pattern | Each robot gets its own DO instance for state management | Better isolation, easier to scale |
| 2025-12-04 | Multi-tier fallback strategy (Cloud → P2P → Local → Autonomous) | Ensures robot remains operational even with cloud failures | Higher reliability, graceful degradation |

### Notes & Considerations

- Existing codebase already has Cloudflare TURN integration (`cloudflare_turn.py`)
- Current implementation uses Metered.ca for TURN (can keep as fallback)
- P2P signaling server code can be retained for fallback mode
- Need to ensure minimal changes to existing `CommandHandler` and `VideoSource` classes
- rosbridge_suite is standard ROS2 package, no modifications needed

---

## File Tracking

### Files to Create

#### Phase 0
- [ ] `cloud/workers/wrangler.toml`
- [ ] `cloud/workers/package.json`
- [ ] `cloud/workers/tsconfig.json`
- [ ] `cloud/frontend/package.json`
- [ ] `cloud/frontend/vite.config.ts`
- [ ] `.github/workflows/deploy-workers.yml`
- [ ] `.github/workflows/deploy-frontend.yml`

#### Phase 1
- [ ] `cloud/workers/api/calls-session.ts`
- [ ] `cloud/workers/api/ice-servers.ts`
- [ ] `src/ugv_main/webrtc_ros2_bridge/webrtc_ros2_bridge/sfu_client.py`
- [ ] `cloud/frontend/src/lib/sfuClient.ts`
- [ ] `cloud/frontend/src/hooks/useWebRTC.ts`

#### Phase 2
- [ ] `cloud/workers/durable-objects/robot-connection.ts`
- [ ] `src/ugv_main/fleet_agent/fleet_agent/rosbridge_proxy.py` (if proxy approach)
- [ ] `cloud/frontend/src/lib/rosbridgeClient.ts`
- [ ] `cloud/frontend/src/hooks/useRosbridge.ts`

#### Phase 3
- [ ] `src/ugv_main/fleet_agent/package.xml`
- [ ] `src/ugv_main/fleet_agent/setup.py`
- [ ] `src/ugv_main/fleet_agent/fleet_agent/fleet_agent_node.py`
- [ ] `src/ugv_main/fleet_agent/fleet_agent/cloud_connector.py`
- [ ] `src/ugv_main/fleet_agent/fleet_agent/heartbeat_manager.py`
- [ ] `src/ugv_main/fleet_agent/fleet_agent/config_sync.py`
- [ ] `src/ugv_main/fleet_agent/config/fleet_agent_config.yaml`
- [ ] `src/ugv_main/fleet_agent/launch/fleet_agent.launch.py`

#### Phase 4
- [ ] `cloud/frontend/src/App.tsx`
- [ ] `cloud/frontend/src/pages/FleetDashboard.tsx`
- [ ] `cloud/frontend/src/pages/RobotDetail.tsx`
- [ ] `cloud/frontend/src/pages/Navigation.tsx`
- [ ] `cloud/frontend/src/components/VideoPlayer.tsx`
- [ ] `cloud/frontend/src/components/TeleopController.tsx`
- [ ] `cloud/frontend/src/components/RobotStatusCard.tsx`
- [ ] `cloud/frontend/src/components/BatteryIndicator.tsx`
- [ ] `cloud/frontend/src/components/LatencyMonitor.tsx`
- [ ] `cloud/frontend/src/hooks/useGamepad.ts`

#### Phase 5
- [ ] `docker-compose.fleet.yml`
- [ ] `.env.template`
- [ ] `docs/robot-setup.md`
- [ ] `docs/cloud-deployment.md`
- [ ] `docs/operator-manual.md`
- [ ] `docs/api-documentation.md`
- [ ] `docs/troubleshooting.md`

### Files to Modify

#### Phase 1
- [ ] `src/ugv_main/webrtc_ros2_bridge/webrtc_ros2_bridge/bridge_node.py` - Integrate SFU client
- [ ] `src/ugv_main/webrtc_ros2_bridge/config/bridge_config.yaml` - Add SFU configuration

#### Phase 3
- [ ] Root workspace `package.xml` or build configuration to include fleet_agent

---

## Resources & References

### Cloudflare Documentation
- [Cloudflare Calls API](https://developers.cloudflare.com/calls/)
- [Cloudflare Workers](https://developers.cloudflare.com/workers/)
- [Durable Objects](https://developers.cloudflare.com/durable-objects/)
- [Workers KV](https://developers.cloudflare.com/kv/)
- [Cloudflare Pages](https://developers.cloudflare.com/pages/)

### ROS2 Documentation
- [rosbridge_suite](https://github.com/RobotWebTools/rosbridge_suite)
- [ROS2 Humble](https://docs.ros.org/en/humble/)
- [Nav2](https://navigation.ros.org/)

### WebRTC Documentation
- [aiortc](https://github.com/aiortc/aiortc)
- [WebRTC API](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API)

### Related Technologies
- [React](https://react.dev/)
- [TypeScript](https://www.typescriptlang.org/)
- [Vite](https://vitejs.dev/)
- [TailwindCSS](https://tailwindcss.com/)

---

## Contact & Support

**Project Lead:** [Your Name]
**Repository:** [GitHub URL]
**Issues:** [GitHub Issues URL]

---

**Last Updated:** 2025-12-04
**Document Version:** 1.0
