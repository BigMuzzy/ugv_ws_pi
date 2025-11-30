# WebRTC TURN Server Debugging Session

## Current Status: TURN Server Not Reachable from External Networks

### Problem Summary
- WebRTC connections are failing between external clients and the UGV robot
- STUN is working (getting srflx candidates with public IP 73.157.62.135)
- TURN is NOT working (NO relay candidates appearing)
- External clients cannot reach the TURN server at 73.157.62.135:3478

### Test Results

#### Test 1 - Robot's WebRTC Connection
```
✅ WebSocket connected
✅ ICE gathering: host candidates (local)
✅ ICE gathering: srflx candidates (73.157.62.135 via STUN)
❌ NO relay candidates (TURN failed)
❌ ICE connection: disconnected → failed
```

#### Test 2 - Trickle ICE Test (from external network 166.198.240.161)
```
✅ host candidates: 10.22.61.73
✅ srflx candidates: 166.198.240.161 (via Google STUN)
❌ NO relay candidates (TURN server unreachable)
```

### What We've Verified ✅

1. **CoTURN Server on Raspberry Pi (192.168.100.47)**
   - ✅ Service is running (active since 11:38:04)
   - ✅ Listening on 0.0.0.0:3478 (TCP and UDP)
   - ✅ Configuration looks correct:
     - listening-ip=0.0.0.0
     - external-ip=73.157.62.135/192.168.100.47
     - relay-ip=192.168.100.47
     - user=ugvuser:ugvpass123
     - realm=ugvrpi.local
   - ✅ Ports in use: 3478 (TCP/UDP), relay ports 49152-65535

2. **WebRTC Client Configuration (index.html:440-456)**
   ```javascript
   iceServers: [
       { urls: 'stun:stun.l.google.com:19302' },
       { urls: 'stun:stun1.l.google.com:19302' },
       {
           urls: [
               'turn:73.157.62.135:3478',
               'turn:73.157.62.135:3478?transport=tcp'
           ],
           username: 'ugvuser',
           credential: 'ugvpass123'
       }
   ]
   ```

3. **WebRTC Server Configuration (webrtc_manager.py:40-52)**
   ```python
   self._turn_servers = [
       {
           "url": "turn:73.157.62.135:3478",
           "username": "ugvuser",
           "credential": "ugvpass123"
       },
       {
           "url": "turn:73.157.62.135:3478?transport=tcp",
           "username": "ugvuser",
           "credential": "ugvpass123"
       }
   ]
   ```

4. **CoTURN Logs Analysis**
   - OLD logs (11:24-11:34) show sessions from 192.168.100.1 (local network only)
   - NO logs since restart at 11:38
   - **NO external connection attempts logged**
   - This confirms external clients cannot reach the TURN server

### Root Cause: pfSense Port Forwarding or Firewall Issue

The TURN server is running correctly but **NOT reachable from external networks**.

---

## ACTION ITEMS FOR TOMORROW

### 1. Verify pfSense Port Forwarding Rules

**Navigate to:** Firewall → NAT → Port Forward

**Check these rules exist:**
```
Interface: WAN
Protocol: TCP/UDP
Source: any (*)
Source Port: any (*)
Destination: WAN address
Destination Port: 3478
Redirect Target IP: 192.168.100.47
Redirect Target Port: 3478
Description: CoTURN STUN/TURN

---

Interface: WAN
Protocol: TCP/UDP
Source: any (*)
Source Port: any (*)
Destination: WAN address
Destination Port: 5349
Redirect Target IP: 192.168.100.47
Redirect Target Port: 5349
Description: CoTURN TLS

---

Interface: WAN
Protocol: UDP
Source: any (*)
Source Port: any (*)
Destination: WAN address
Destination Port: 49152-65535
Redirect Target IP: 192.168.100.47
Redirect Target Port: 49152-65535
Description: CoTURN Relay Ports
```

**CRITICAL CHECKS:**
- [ ] Interface is **WAN** (not LAN or another interface)
- [ ] "Filter rule association" is set to "Add associated filter rule"
- [ ] Rules are **enabled** (not disabled)
- [ ] **Apply Changes** has been clicked after creating rules

### 2. Check WAN Firewall Rules

**Navigate to:** Firewall → Rules → WAN

**Verify these rules exist** (should be auto-created by port forwards):
```
Action: Pass
Interface: WAN
Protocol: TCP/UDP
Source: any
Destination: WAN address
Destination Port: 3478
Description: NAT CoTURN STUN/TURN

Action: Pass
Interface: WAN
Protocol: TCP/UDP
Source: any
Destination: WAN address
Destination Port: 5349
Description: NAT CoTURN TLS

Action: Pass
Interface: WAN
Protocol: UDP
Source: any
Destination: WAN address
Destination Port: 49152-65535
Description: NAT CoTURN Relay Ports
```

**If rules are missing, manually add them!**

### 3. Check WAN Interface Configuration

**Navigate to:** Status → Interfaces → WAN

**Verify:**
- [ ] WAN interface has IP: **73.157.62.135**
- [ ] Status is **up**
- [ ] Gateway is reachable

**If WAN IP is different:**
- You might have another router/modem in front of pfSense (double NAT)
- Or you're behind Carrier-Grade NAT (CGNAT)
- Check if WAN IP is 100.x.x.x (indicates CGNAT)

### 4. Disable NAT Reflection (Temporary Test)

**Navigate to:** System → Advanced → Firewall & NAT

**Change:**
- "NAT Reflection mode for port forwards" → **Disabled**
- Click **Save**

This prevents internal clients from using external IPs, which can interfere with testing.

### 5. Test Port Connectivity from External Network

**Use phone hotspot or different network:**

**Option A - Command line:**
```bash
# Test UDP port 3478
nc -u -v 73.157.62.135 3478

# Test TCP port 3478
nc -v 73.157.62.135 3478

# If you get a connection, type something and press Enter
# TURN server should respond
```

**Option B - Online tools:**
1. **TCP Port Test:**
   - https://www.yougetsignal.com/tools/open-ports/
   - Host: 73.157.62.135
   - Port: 3478

2. **TURN Server Test:**
   - https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/
   - TURN URI: turn:73.157.62.135:3478
   - Username: ugvuser
   - Password: ugvpass123
   - Click "Gather candidates"
   - **Look for [relay] candidates**

### 6. Check pfSense Logs

**Navigate to:** Status → System Logs → Firewall

**Filter for:**
- Destination port: 3478
- Look for BLOCKED packets from external IPs
- If you see blocks, your firewall rules aren't working

---

## Potential CoTURN Configuration Issues

### Issue 1: relay-ip setting
The current config has:
```
relay-ip=192.168.100.47
```

This might cause TURN to advertise the internal IP. Consider removing this line and letting `external-ip` handle it.

### Recommended CoTURN Config Changes

```bash
# Edit /etc/turnserver.conf
sudo nano /etc/turnserver.conf

# Remove or comment out this line:
# relay-ip=192.168.100.47

# Add these lines if not present:
no-cli
no-tcp-relay  # Force UDP relay only (better for WebRTC)

# Restart CoTURN
sudo systemctl restart coturn

# Check logs
sudo journalctl -u coturn -f
```

---

## Network Architecture

```
External Client (166.198.240.161)
    ↓
Internet
    ↓
Public IP: 73.157.62.135
    ↓
pfSense Firewall/Router
    ↓ (Port forward 3478 → 192.168.100.47:3478)
    ↓
LAN: 192.168.100.0/24
    ↓
Raspberry Pi: 192.168.100.47
    ↓
CoTURN Server (listening on 0.0.0.0:3478)
```

**Current Problem:** Traffic is NOT reaching the Raspberry Pi from external networks.

---

## Diagnostic Questions to Answer Tomorrow

1. **Is pfSense WAN interface showing IP 73.157.62.135?**
   - If NO: You have double NAT or CGNAT issue

2. **Are port forward rules on WAN interface?**
   - If NO: They won't work

3. **Do WAN firewall rules exist for these ports?**
   - If NO: Packets will be blocked

4. **Can you ping/traceroute to 73.157.62.135 from external network?**
   - If NO: Routing/connectivity issue

5. **Are there any pfSense firewall logs blocking port 3478?**
   - If YES: Rules aren't configured correctly

---

## Success Criteria

When fixed, you should see in Trickle ICE test:
```
✅ host candidates
✅ srflx candidates (via STUN)
✅ relay candidates (via TURN) ← THIS IS MISSING NOW!
```

And in browser console:
```
ICE candidate [host]: ...
ICE candidate [srflx]: ...
ICE candidate [relay]: udp 73.157.62.135:XXXXX  ← THIS SHOULD APPEAR!
ICE connection state: connected
Connection state: connected
```

---

## Files Modified

- `src/ugv_main/webrtc_ros2_bridge/static/index.html` (already configured correctly)
- `src/ugv_main/webrtc_ros2_bridge/webrtc_ros2_bridge/webrtc_manager.py` (already configured correctly)

## Next Session Plan

1. Check all pfSense items above
2. Test port connectivity
3. Fix any firewall/NAT issues found
4. Optionally update CoTURN config
5. Retest with Trickle ICE
6. If working, test full WebRTC connection

---

**Session Date:** 2025-11-30
**Saved for continuation:** Yes
**Location:** /home/ws/ugv_ws/WEBRTC_DEBUG_SESSION.md
