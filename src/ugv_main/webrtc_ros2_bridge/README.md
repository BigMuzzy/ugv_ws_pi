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
