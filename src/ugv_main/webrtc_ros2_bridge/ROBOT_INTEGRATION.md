# Robot Integration Guide - SFU Mode

**Status:** Ready for Testing  
**Date:** December 5, 2025

---

## Overview

The WebRTC ROS2 Bridge now supports **SFU mode** (Selective Forwarding Unit) using Cloudflare Calls, in addition to the traditional P2P mode. This enables:

- Multiple viewers watching the same robot simultaneously
- Improved scalability
- Centralized session management via Cloudflare Workers
- Automatic fallback to P2P mode if SFU is unavailable

---

## Prerequisites

### On the Robot (Raspberry Pi 5)

1. **Python Dependencies:**
   ```bash
   pip install aiortc aiohttp opencv-python numpy
   ```

2. **ROS2 Humble:** Already installed in your Docker container

3. **Camera:** OAK-D Lite or any V4L2 compatible camera

### Cloud Infrastructure

- ✅ Cloudflare Workers deployed: `https://fleet-workers.mssemyonov.workers.dev`
- ✅ KV namespace configured
- ✅ Cloudflare Calls API configured

---

## Quick Start

### Option 1: Launch with SFU Mode (Recommended)

```bash
# On the robot
ros2 launch webrtc_ros2_bridge sfu_bridge.launch.py robot_id:=robot_01
```

This will:
1. Connect to Cloudflare Workers API
2. Create an SFU session
3. Start streaming video to Cloudflare Calls SFU
4. Listen for commands via DataChannel

### Option 2: Launch with Config File

```bash
# Use the SFU config file
ros2 launch webrtc_ros2_bridge sfu_bridge.launch.py \
  robot_id:=robot_01 \
  workers_endpoint:=https://fleet-workers.mssemyonov.workers.dev
```

### Option 3: Traditional P2P Mode

```bash
# Falls back to P2P signaling server
ros2 launch webrtc_ros2_bridge bridge.launch.py
```

---

## Configuration

### SFU Mode Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `sfu.enabled` | `false` | Enable SFU mode |
| `sfu.robot_id` | `robot_01` | Unique robot identifier |
| `sfu.workers_endpoint` | `https://fleet-workers.mssemyonov.workers.dev` | Workers API URL |
| `sfu.fallback_to_p2p` | `true` | Fallback to P2P if SFU fails |

### Video Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `video.device` | `/dev/video0` | Camera device path |
| `video.width` | `640` | Frame width |
| `video.height` | `480` | Frame height |
| `video.fps` | `30` | Frames per second |

### Robot Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `robot.cmd_vel_topic` | `/cmd_vel` | Velocity command topic |
| `robot.max_linear_speed` | `1.0` | Max linear speed (m/s) |
| `robot.max_angular_speed` | `2.0` | Max angular speed (rad/s) |

---

## Testing

### 1. Verify Robot Connection

```bash
# Launch the bridge
ros2 launch webrtc_ros2_bridge sfu_bridge.launch.py robot_id:=test_robot

# In another terminal, check logs
ros2 topic echo /rosout
```

**Expected output:**
```
[webrtc_bridge_sfu]: Using SFU mode (Cloudflare Calls)
[webrtc_bridge_sfu]: Initializing SFU client for robot: test_robot
[webrtc_bridge_sfu]: Workers endpoint: https://fleet-workers.mssemyonov.workers.dev
[webrtc_bridge_sfu]: Created SFU session: <session_id>
[webrtc_bridge_sfu]: Successfully connected to Cloudflare SFU
```

### 2. Verify Session Created

```bash
# Check if session exists via Workers API
curl https://fleet-workers.mssemyonov.workers.dev/api/sessions/test_robot
```

**Expected response:**
```json
{
  "success": true,
  "session": {
    "sessionId": "...",
    "robotId": "test_robot",
    "created": "2025-12-05T...",
    "expires": "2025-12-05T...",
    "iceServers": [...]
  }
}
```

### 3. Test Command Reception

```bash
# Publish test velocity command
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.5}, angular: {z: 0.0}}"

# Robot should receive and execute the command
```

### 4. Test Frontend Connection

See `cloud/frontend/README.md` for frontend testing instructions.

---

## Architecture Flow

```
┌─────────────────────────────────────────────────────┐
│              Robot (Raspberry Pi 5)                 │
│                                                     │
│  ┌────────────────────────────────────────────┐   │
│  │  webrtc_ros2_bridge                        │   │
│  │                                            │   │
│  │  ┌──────────────┐   ┌──────────────────┐  │   │
│  │  │ bridge_node  │   │  sfu_client.py   │  │   │
│  │  └──────┬───────┘   └────────┬─────────┘  │   │
│  │         │                    │            │   │
│  │         │ cmd_vel            │ connect()  │   │
│  │         ▼                    ▼            │   │
│  │  ┌──────────────┐   ┌──────────────────┐  │   │
│  │  │ CommandHandler│   │ CloudflareSFU   │  │   │
│  │  └──────────────┘   │ RTCPeerConnection│  │   │
│  │                     └────────┬─────────┘  │   │
│  └─────────────────────────────┼────────────┘   │
└────────────────────────────────┼────────────────┘
                                 │
                                 │ WebRTC
                                 │ (Video + DataChannel)
                                 │
┌────────────────────────────────▼────────────────────┐
│              Cloudflare Edge                        │
│                                                     │
│  ┌──────────────┐         ┌─────────────────────┐ │
│  │   Workers    │◄────────┤  Calls SFU          │ │
│  │   (API)      │         │  (Video Hub)        │ │
│  └──────────────┘         └───────┬─────────────┘ │
│                                   │               │
└───────────────────────────────────┼─────────────────┘
                                   │
                                   │ WebRTC
                                   │
                            ┌──────▼──────┐
                            │  Browser    │
                            │  (Viewer)   │
                            └─────────────┘
```

---

## Troubleshooting

### Issue: "Failed to connect to SFU"

**Possible causes:**
1. Workers endpoint unreachable
2. Robot ID already in use
3. Network connectivity issues

**Solutions:**
```bash
# Test Workers endpoint
curl https://fleet-workers.mssemyonov.workers.dev/health

# Check network connectivity
ping 1.1.1.1

# Try with a different robot_id
ros2 launch webrtc_ros2_bridge sfu_bridge.launch.py robot_id:=robot_02
```

### Issue: "aiortc not available"

```bash
# Install aiortc
pip install aiortc

# If on Raspberry Pi, you may need additional dependencies
sudo apt-get install libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
  libswscale-dev libswresample-dev libavfilter-dev libopus-dev libvpx-dev pkg-config
```

### Issue: "Camera not found"

```bash
# List available cameras
v4l2-ctl --list-devices

# Test camera
ffplay /dev/video0

# Update launch parameter
ros2 launch webrtc_ros2_bridge sfu_bridge.launch.py video_device:=/dev/video2
```

### Issue: "Session expired"

Sessions expire after 1 hour. The robot should automatically reconnect. If not:

```bash
# Restart the bridge node
ros2 lifecycle set /webrtc_bridge_sfu shutdown
ros2 launch webrtc_ros2_bridge sfu_bridge.launch.py robot_id:=robot_01
```

---

## Fallback to P2P Mode

If SFU mode fails, the bridge can automatically fall back to P2P mode (if `sfu.fallback_to_p2p: true`):

```
[webrtc_bridge_sfu]: Failed to connect to SFU
[webrtc_bridge_sfu]: Falling back to P2P mode
[webrtc_bridge_sfu]: Starting signaling server on 0.0.0.0:8080
```

You can then access the P2P interface at: `http://<robot_ip>:8080`

---

## Performance Tips

### 1. Optimize Video Encoding

```yaml
# config/sfu_config.yaml
video:
  width: 640
  height: 480
  fps: 30  # Lower to 15-20 for better performance on Pi
```

### 2. Hardware Encoding (Pi 5)

The Raspberry Pi 5 has hardware H.264 encoding. This is automatically used by aiortc if available.

### 3. Reduce Network Latency

- Use ethernet connection instead of WiFi
- Ensure robot is close to WiFi access point
- Check for network congestion

### 4. Monitor Connection Quality

```bash
# Check ROS2 diagnostics
ros2 topic echo /diagnostics

# Check system resources
htop
```

---

## Next Steps

1. **Complete signaling implementation** - Currently, the offer/answer exchange is incomplete
2. **Test multi-viewer** - Connect multiple browsers to same robot
3. **Add telemetry** - Send robot status through DataChannel
4. **Implement fleet_agent** - Phase 3 for fleet management

---

## Files Modified/Created

### Core Integration
- ✅ `webrtc_ros2_bridge/sfu_client.py` - SFU client implementation
- ✅ `webrtc_ros2_bridge/bridge_node.py` - Modified for SFU mode
- ✅ `launch/sfu_bridge.launch.py` - SFU launch file
- ✅ `config/sfu_config.yaml` - SFU configuration

### Documentation
- ✅ `ROBOT_INTEGRATION.md` - This file
- ✅ `PHASE_1_IMPLEMENTATION.md` - Phase 1 status

---

## Support

For issues or questions:
1. Check logs: `ros2 topic echo /rosout`
2. Check Workers logs: `npx wrangler tail` (in `cloud/workers/`)
3. Test Workers API: `curl https://fleet-workers.mssemyonov.workers.dev/health`
4. Review `PHASE_1_IMPLEMENTATION.md` for known limitations

---

**Status:** Robot integration code complete! Ready for testing once signaling is implemented. 🚀
