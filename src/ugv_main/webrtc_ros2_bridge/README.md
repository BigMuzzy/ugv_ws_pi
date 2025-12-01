```mermaid
graph TB
    subgraph "Peer A Network"
        A[Peer A<br/>Browser/App]
        NAT_A[NAT/Firewall A]
    end
    
    subgraph "Peer B Network"
        B[Peer B<br/>Browser/App]
        NAT_B[NAT/Firewall B]
    end
    
    subgraph "Public Internet"
        SS[Signaling Server<br/>WebSocket/HTTP]
        STUN[STUN Server<br/>Discovers public IP]
        TURN[TURN Server<br/>Relay fallback]
    end
    
    A <-.->|1. Signal Exchange| SS
    B <-.->|1. Signal Exchange| SS
    A -.->|2. Get Public IP| STUN
    B -.->|2. Get Public IP| STUN
    A <-.->|3. Direct P2P Media<br/>if possible| B
    A <-.->|4. Relay via TURN<br/>if NAT traversal fails| TURN
    TURN <-.-> B
    
    style A fill:#e1f5ff
    style B fill:#e1f5ff
    style SS fill:#fff4e1
    style STUN fill:#f0fff4
    style TURN fill:#fff0f0
```
```mermaid
sequenceDiagram
    participant A as Peer A<br/>(192.168.1.100)
    participant NAT_A as NAT A
    participant STUN as STUN Server
    participant NAT_B as NAT B
    participant B as Peer B<br/>(10.0.0.50)
    
    Note over A,B: Step 1: Discover Public Endpoints
    A->>NAT_A: Send to STUN
    NAT_A->>STUN: From 203.0.113.10:54321
    STUN->>NAT_A: You are 203.0.113.10:54321
    NAT_A->>A: Your public endpoint
    
    B->>NAT_B: Send to STUN
    NAT_B->>STUN: From 198.51.100.20:12345
    STUN->>NAT_B: You are 198.51.100.20:12345
    NAT_B->>B: Your public endpoint
    
    Note over A,B: Step 2: Exchange via Signaling
    Note over A: Now knows B is at<br/>198.51.100.20:12345
    Note over B: Now knows A is at<br/>203.0.113.10:54321
    
    Note over A,B: Step 3: Simultaneous Open (The Magic!)
    A->>NAT_A: Send to 198.51.100.20:12345
    Note over NAT_A: Opens hole for<br/>198.51.100.20:12345
    NAT_A->>NAT_B: Packet arrives
    
    B->>NAT_B: Send to 203.0.113.10:54321
    Note over NAT_B: Opens hole for<br/>203.0.113.10:54321
    NAT_B->>NAT_A: Packet arrives
    
    Note over A,B: ✅ Bidirectional P2P established!
    A<<->>B: Direct communication
```

### 2. **Firewall Rules Must Permit**
```
┌─────────────────────────────────────────┐
│ ✅ REQUIRED FIREWALL CONDITIONS:        │
├─────────────────────────────────────────┤
│                                         │
│ 1. Allow OUTBOUND UDP traffic           │
│    • Port range: 1024-65535 (ephemeral)│
│    • Destination: Any                   │
│                                         │
│ 2. Allow INBOUND UDP on same ports      │
│    • From: Specific IP learned via STUN│
│    • NAT must maintain port mapping     │
│                                         │
│ 3. UDP timeout >= 30 seconds            │
│    • Connection must stay "open"        │
│    • Keepalives prevent timeout         │
│                                         │
└─────────────────────────────────────────┘
```

### 3. **Timing Synchronization**

The "simultaneous open" must happen within NAT timeout window:
```
Time →
    0s        1s        2s        3s        4s        5s
    │         │         │         │         │         │
A:  ●─────────●─────────●─────────●─────────●─────────●
    Send      Send      Send      (hole open for 30s)
    
B:            ●─────────●─────────●─────────●─────────●
              Send      Send      (hole open for 30s)
    
        ┌─────┴─────┐
        │   Both    │
        │ NATs have │   ✅ Success!
        │holes open │
        └───────────┘
```

If timing is off:
```
Time →
    0s        10s       20s       30s
    │         │         │         │
A:  ●─────────────────────────────X (NAT closes hole)
    Send
    
B:                                ●
                                  Send (too late!)
                                  
                                  ❌ Blocked by NAT_A
```

## Why Symmetric NAT Breaks P2P

Here's the problem with Symmetric NAT:
```
┌──────────────────────────────────────────────┐
│ Symmetric NAT Behavior                       │
├──────────────────────────────────────────────┤
│                                              │
│ Internal IP: 192.168.1.100:5000             │
│                                              │
│ When talking to STUN (1.2.3.4:3478):        │
│   → Public mapping: 203.0.113.10:54321      │
│                                              │
│ When talking to Peer B (5.6.7.8:9999):      │
│   → Public mapping: 203.0.113.10:54322      │
│      (DIFFERENT PORT!)                       │
│                                              │
│ Peer B learns 54321 from STUN exchange,     │
│ but A will use 54322 when contacting B!     │
│                                              │
│ ❌ Mismatch = Connection fails               │
└──────────────────────────────────────────────┘
```

Visualization:
```
        ┌─────────────────┐
        │  Symmetric NAT  │
        │   (Peer A)      │
        └─────────────────┘
              ││  ││
    To STUN   ││  ││  To Peer B
    :54321    ││  ││  :54322
              ││  ││
              ││  ││
          Different ports!
          Peer B will send
          to :54321, but
          NAT expects :54322
              ❌ BLOCKED
```

## Real-World Conditions Summary

For **direct P2P to work**, you need:

### ✅ Must Have:
1. **At least ONE peer NOT behind Symmetric NAT**
2. **Both NATs allow UDP hole punching** (most do)
3. **Firewalls allow established UDP sessions**
4. **STUN server accessible** from both peers
5. **Coordinated "simultaneous open"** via signaling

### 🚫 Deal Breakers:
1. **Both peers behind Symmetric NAT** → 95% failure rate
2. **Corporate firewall blocks all UDP** → 100% failure
3. **Carrier-grade NAT (CGNAT)** → Often needs TURN
4. **Mobile networks with strict firewalls** → Often needs TURN

### 📊 Statistics from the Field:
- **~80-85%** of connections work with just STUN
- **~10-15%** require TURN relay
- **~5%** fail completely (strict enterprise networks)

## Practical Example: Your Robot Setup

If your Raspberry Pi is at home and remote viewer is also at home:
```
Home Network A              Home Network B
┌─────────────┐            ┌─────────────┐
│ Router/NAT  │            │ Router/NAT  │
│  (typical   │◀═══════════▶│  (typical   │
│  home ISP)  │   Direct   │  home ISP)  │
│             │    P2P     │             │
│  ┌──────┐   │   Works!   │  ┌───────┐  │
│  │ Pi/  │   │    ✅      │  │Browser│  │
│  │Robot │   │            │  │       │  │
│  └──────┘   │            │  └───────┘  │
└─────────────┘            └─────────────┘
```
```mermaid
sequenceDiagram
    participant A as Peer A
    participant TURN as TURN Server<br/>(73.157.62.135:3478)
    participant B as Peer B
    
    Note over A,TURN: Authentication Phase
    A->>TURN: Allocate Request<br/>(username: ugvuser, credential: ...)
    TURN->>A: Allocate Success<br/>Your relay: 73.157.62.135:50000
    
    B->>TURN: Allocate Request<br/>(username: ugvuser, credential: ...)
    TURN->>B: Allocate Success<br/>Your relay: 73.157.62.135:50001
    
    Note over A,B: Permission Setup
    A->>TURN: CreatePermission for B's IP
    B->>TURN: CreatePermission for A's IP
    
    Note over A,B: Channel Binding (optional, for efficiency)
    A->>TURN: ChannelBind 0x4000 → B
    B->>TURN: ChannelBind 0x4001 → A
    
    Note over A,B: Media Relay
    A->>TURN: Video packet (via channel 0x4000)
    TURN->>B: Video packet forwarded
    
    B->>TURN: Control message (via channel 0x4001)
    TURN->>A: Control message forwarded
    
    Note over A,B: Keepalive (every 15-30s)
    A->>TURN: Refresh request
    TURN->>A: Allocation refreshed
```

## When to Use TURN
```
┌─────────────────────────────────────────┐
│ ALWAYS configure TURN servers, because: │
├─────────────────────────────────────────┤
│                                         │
│ ✅ Provides guaranteed connectivity     │
│ ✅ Handles worst-case NAT scenarios     │
│ ✅ Required for ~10-15% of connections  │
│ ✅ Automatic fallback (transparent)     │
│                                         │
│ But expect:                             │
│ ⚠️  2x bandwidth usage                  │
│ ⚠️  Higher latency                      │
│ ⚠️  Server infrastructure costs         │
│                                         │
└─────────────────────────────────────────┘
