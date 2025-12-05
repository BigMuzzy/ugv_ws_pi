# WebRTC Signaling Implementation Complete

**Status:** ✅ Fully Implemented  
**Date:** December 5, 2025  
**Phase:** Phase 1 - Cloudflare Calls Integration

---

## Overview

The complete WebRTC signaling flow has been implemented for communication between robots and viewers through Cloudflare Calls SFU. This enables:

- ✅ Robot can create SFU sessions
- ✅ Robot sends offer and receives answer
- ✅ Viewers can connect and receive video
- ✅ Commands flow through DataChannel
- ✅ ICE candidate handling
- ✅ Automatic reconnection

---

## Signaling Flow

### 1. Session Creation (Robot → Workers → Cloudflare Calls)

```
Robot                    Workers API              Cloudflare Calls
  │                          │                           │
  ├─ POST /sessions/create ─→│                           │
  │                          ├─ POST /sessions/new ─────→│
  │                          │←─── sessionId ────────────┤
  │←─ sessionInfo + ICE ─────┤                           │
  │                          │                           │
```

**API Endpoint:** `POST /api/sessions/create`

**Request:**
```json
{
  "robotId": "robot_01"
}
```

**Response:**
```json
{
  "success": true,
  "session": {
    "sessionId": "abc123...",
    "robotId": "robot_01",
    "created": "2025-12-05T...",
    "expires": "2025-12-05T...",
    "iceServers": [
      { "urls": "stun:stun.cloudflare.com:3478" }
    ]
  }
}
```

### 2. Offer/Answer Exchange (Robot Publishes Video)

```
Robot                    Workers API              Cloudflare Calls
  │                          │                           │
  │ Create RTCPeerConnection │                           │
  │ Add video track          │                           │
  │ Create offer             │                           │
  │                          │                           │
  ├─ POST /sessions/:id/offer ─→│                        │
  │   { offer: { type, sdp } }│                          │
  │                          ├─ POST /tracks/new ───────→│
  │                          │   { sessionDescription }  │
  │                          │←─── answer ───────────────┤
  │←─ { answer } ────────────┤                           │
  │                          │                           │
  │ Set remote description   │                           │
  │ ICE negotiation starts   │                           │
  │                          │                           │
```

**API Endpoint:** `POST /api/sessions/:robotId/offer`

**Request:**
```json
{
  "offer": {
    "type": "offer",
    "sdp": "v=0\r\no=- ... [SDP content]"
  }
}
```

**Response:**
```json
{
  "success": true,
  "answer": {
    "type": "answer",
    "sdp": "v=0\r\no=- ... [SDP content]"
  }
}
```

### 3. Viewer Connection (Pull Video Stream)

```
Viewer                   Workers API              Cloudflare Calls
  │                          │                           │
  ├─ GET /sessions/:id ─────→│                           │
  │←─ sessionInfo ───────────┤                           │
  │                          │                           │
  │ Create RTCPeerConnection │                           │
  │ Create offer             │                           │
  │                          │                           │
  ├─ POST /sessions/:id/offer ─→│                        │
  │   { offer }              │                           │
  │                          ├─ POST /tracks/new ───────→│
  │                          │   { tracks: [remote] }    │
  │                          │←─── answer + tracks ──────┤
  │←─ { answer } ────────────┤                           │
  │                          │                           │
  │ Set remote description   │                           │
  │ Receive video track      │                           │
  │                          │                           │
```

**API Endpoints:**

1. **Get Session:** `GET /api/sessions/:robotId`
2. **Send Offer:** `POST /api/sessions/:robotId/offer`
3. **Get ICE Servers:** `GET /api/ice-servers`

### 4. DataChannel for Commands

```
Viewer                   SFU                      Robot
  │                       │                        │
  │ Create DataChannel    │                        │
  │ "commands"            │                        │
  │                       │                        │
  ├─ { type: "command" } ─→│                       │
  │   linear: 0.5          │                       │
  │   angular: 0.0         │                       │
  │                       ├─→ DataChannel message │
  │                       │  { type: "command" }   │
  │                       │    linear: 0.5         │
  │                       │    angular: 0.0        │
  │                       │                        │
  │                       │←─ publish /cmd_vel ────┤
  │                       │                        │
```

---

## API Reference

### Session Management

#### Create Session
```
POST /api/sessions/create
Content-Type: application/json

{ "robotId": "robot_01" }
```

#### Get Session
```
GET /api/sessions/:robotId
```

#### Delete Session
```
DELETE /api/sessions/:robotId
```

### Signaling

#### Send Offer
```
POST /api/sessions/:robotId/offer
Content-Type: application/json

{
  "offer": {
    "type": "offer",
    "sdp": "..."
  }
}
```

#### Get Answer (Alternative for viewers)
```
GET /api/sessions/:robotId/answer
```

#### Add ICE Candidate (Optional)
```
POST /api/sessions/:robotId/ice-candidate
Content-Type: application/json

{
  "candidate": {
    "candidate": "...",
    "sdpMLineIndex": 0,
    "sdpMid": "0"
  }
}
```

### ICE Servers

#### Get STUN/TURN Servers
```
GET /api/ice-servers
```

---

## Implementation Details

### Workers (Cloudflare)

**Files:**
- `cloud/workers/api/calls-session.ts` - Session and signaling endpoints
- `cloud/workers/src/index.ts` - Main router

**Key Functions:**
- `createSession()` - Creates SFU session
- `handleOffer()` - Processes WebRTC offers, returns answers
- `getAnswer()` - Alternative answer retrieval for viewers
- `addIceCandidate()` - Stores ICE candidates
- `getIceServers()` - Returns STUN/TURN configuration

**Cloudflare Calls API Integration:**
- Uses `/v1/apps/:appId/sessions/new` to create sessions
- Uses `/v1/apps/:appId/sessions/:sessionId/tracks/new` for offer/answer
- Automatic ICE handling by Cloudflare infrastructure

### Robot (Python)

**File:** `src/ugv_main/webrtc_ros2_bridge/webrtc_ros2_bridge/sfu_client.py`

**Key Methods:**
- `connect()` - Establishes SFU connection
- `_create_sfu_session()` - Requests session from Workers
- `_create_peer_connection()` - Sets up RTCPeerConnection with ICE servers
- `_create_and_send_offer()` - Creates offer, sends to Workers, processes answer
- `_reconnect()` - Automatic reconnection with exponential backoff

**Flow:**
1. Fetch session info from Workers API
2. Create RTCPeerConnection with returned ICE servers
3. Add video track
4. Create and send offer
5. Receive and set remote description (answer)
6. ICE negotiation completes automatically

### Frontend (TypeScript)

**File:** `cloud/frontend/src/lib/sfuClient.ts`

**Key Methods:**
- `connect()` - Connects to existing robot session
- `fetchSessionInfo()` - Gets session details from Workers
- `createPeerConnection()` - Sets up RTCPeerConnection
- `sendOfferAndGetAnswer()` - Exchanges SDP with Workers
- `sendCommand()` - Sends velocity commands via DataChannel

**Flow:**
1. Fetch session info for robot
2. Create RTCPeerConnection
3. Create DataChannel for commands
4. Create and send offer
5. Receive and set remote description (answer)
6. Receive video track from SFU
7. Send commands through DataChannel

---

## Testing

### 1. Test Workers Endpoints

```bash
# Create session
curl -X POST https://fleet-workers.mssemyonov.workers.dev/api/sessions/create \
  -H "Content-Type: application/json" \
  -d '{"robotId": "robot_01"}'

# Get session
curl https://fleet-workers.mssemyonov.workers.dev/api/sessions/robot_01

# Get ICE servers
curl https://fleet-workers.mssemyonov.workers.dev/api/ice-servers
```

### 2. Test Robot Connection

```bash
# Launch robot in SFU mode
ros2 launch webrtc_ros2_bridge sfu_bridge.launch.py robot_id:=robot_01

# Check logs
ros2 topic echo /rosout | grep webrtc_bridge_sfu
```

**Expected logs:**
```
[INFO] Using SFU mode (Cloudflare Calls)
[INFO] Initializing SFU client for robot: robot_01
[INFO] Workers endpoint: https://fleet-workers.mssemyonov.workers.dev
[INFO] Created SFU session: <session_id>
[INFO] Created offer for SFU
[INFO] Set remote description from SFU answer
[INFO] SFU connection state: connected
```

### 3. Test Frontend Connection

```bash
# In cloud/frontend/
npm start

# Open browser console
```

**Expected console logs:**
```
[SFUClient] Joining SFU session: <session_id>
[SFUClient] Created offer, waiting for ICE gathering...
[SFUClient] Connection state: connected
[SFUClient] Received video track
[SFUClient] Data channel opened
```

### 4. Verify Multi-Viewer

1. Open multiple browser tabs
2. Navigate to robot viewer
3. All should receive the same video stream
4. Commands from any viewer should control robot

---

## Connection States

### ICE Connection States

- `new` - ICE agent gathering addresses
- `checking` - ICE agent checking candidates
- `connected` - ICE agent found a working connection
- `completed` - ICE agent finished checking
- `failed` - ICE agent failed to find connection
- `disconnected` - Connection lost
- `closed` - Connection closed

### Peer Connection States

- `new` - Connection just created
- `connecting` - Negotiating connection
- `connected` - Connected and ready
- `disconnected` - Connection lost
- `failed` - Connection failed
- `closed` - Connection closed

---

## Troubleshooting

### Issue: "Failed to send offer"

**Check:**
1. Workers endpoint is correct and reachable
2. Session was created successfully
3. Network allows outbound HTTPS

**Solution:**
```bash
# Test Workers endpoint
curl https://fleet-workers.mssemyonov.workers.dev/health

# Verify session exists
curl https://fleet-workers.mssemyonov.workers.dev/api/sessions/robot_01
```

### Issue: "ICE connection failed"

**Possible causes:**
1. NAT/firewall blocking WebRTC traffic
2. TURN servers not configured
3. Network doesn't allow UDP

**Solution:**
1. Enable Cloudflare TURN (set CLOUDFLARE_TURN_SERVICE_ID and CLOUDFLARE_TURN_API_TOKEN)
2. Check firewall allows UDP ports
3. Try different network

### Issue: "No video track received"

**Check:**
1. Robot successfully connected to SFU
2. Video track was added to peer connection
3. Browser supports VP8/H264 codecs

**Debug:**
```javascript
// In browser console
pc.getReceivers().forEach(r => {
  console.log('Receiver:', r.track.kind, r.track.id);
});
```

### Issue: "Commands not working"

**Check:**
1. DataChannel is open
2. Message format is correct
3. Robot is subscribed to /cmd_vel

**Debug:**
```bash
# On robot
ros2 topic echo /cmd_vel

# Should see Twist messages when sending commands
```

---

## Performance Metrics

### Expected Latency

- **Video:** 100-300ms (network dependent)
- **Commands:** 50-100ms end-to-end
- **ICE negotiation:** 1-3 seconds

### Bandwidth Usage

- **Video (640x480 @ 30fps):** ~1-2 Mbps
- **Commands:** < 1 Kbps
- **Signaling:** Minimal (only during setup)

---

## Next Steps

1. **Test multi-robot scenario** - Multiple robots, multiple viewers
2. **Add telemetry DataChannel** - Send robot status to viewers
3. **Implement fleet_agent** - Phase 3 fleet management
4. **Add recording** - Store video streams to R2
5. **Add analytics** - Track connection quality, viewer counts

---

## Architecture Benefits

### SFU vs P2P

**Advantages of SFU:**
- ✅ Multiple viewers without robot load
- ✅ Scalable to hundreds of viewers
- ✅ Centralized session management
- ✅ Easier NAT traversal
- ✅ Better monitoring capabilities

**Trade-offs:**
- Increased latency (~50-100ms) vs direct P2P
- Dependency on cloud infrastructure
- Additional signaling complexity

---

## Security Considerations

### Current Implementation

- ✅ HTTPS for all signaling
- ✅ Session expiration (1 hour TTL)
- ✅ Robot ID validation
- ⚠️ No authentication yet

### Recommended Enhancements

1. **Add authentication** - Require tokens for session creation
2. **Rate limiting** - Prevent abuse of API endpoints
3. **Access control** - Per-robot viewer permissions
4. **Encryption** - DTLS-SRTP (automatic with WebRTC)

---

**Status:** Signaling implementation complete and ready for testing! 🚀
