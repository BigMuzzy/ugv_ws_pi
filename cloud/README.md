# UGV Fleet Management - Cloud Infrastructure

Web-based fleet management system for remotely controlling UGV (Unmanned Ground Vehicle) robots via WebRTC and ROS 2.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (Browser) - NO SECRETS              │
│  - Robot selection & video streaming                            │
│  - Control interface (joystick/keyboard)                        │
│  - ROSBridge interface for ROS 2 operations                     │
└─────────────────────────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│            Backend (Cloudflare Worker + Durable Object)         │
│  - Robot registry (KV storage)                                  │
│  - WebSocket signaling (robot ↔ operator)                      │
│  - ROSBridge message proxying                                   │
│  - **Cloudflare Calls API proxy (stores secrets securely)**     │
└─────────────────────────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Cloudflare Calls API (SFU)                  │
│  - WebRTC media routing                                         │
│  - DataChannel management                                       │
└─────────────────────────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Robot (UGV + ROS 2)                     │
│  - Navigation stack & camera streaming                          │
│  - WebRTC client & ROSBridge server                             │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
cloud/
├── frontend/              # Operator web interface (Cloudflare Pages)
│   ├── index.html         # Main UI
│   ├── operator.js        # WebRTC & control logic
│   ├── rosbridge_client.js # ROSBridge client
│   ├── rosbridge_ui.js    # ROS interface UI
│   └── README.md          # Frontend documentation
│
├── workers/               # Backend services (Cloudflare Workers)
│   └── fleet-worker/      # Fleet management worker
│       ├── src/index.ts   # Worker code with Calls API proxy
│       ├── wrangler.toml  # Worker configuration
│       ├── .dev.vars.example # Example environment variables
│       └── README.md      # Worker documentation
│
└── README.md              # This file
```

## Key Features

### Security ✅
- **No secrets in frontend** - All Cloudflare API credentials stored on backend
- **Backend API proxy** - Frontend calls worker endpoints, not Cloudflare APIs directly
- **Secure token storage** - Tokens stored as Cloudflare Worker secrets
- **Clean separation** - Frontend is purely UI, backend handles authentication

### Operator Interface
- Robot selection and live status
- WebRTC video streaming (low latency)
- Manual control (joystick & keyboard)
- ROSBridge integration for full ROS 2 interaction
- Launch Manager for mode switching
- Navigation goal setting

### Backend Services
- Robot registration and heartbeat tracking
- WebSocket-based signaling
- ROSBridge message routing
- **Cloudflare Calls API proxy** (keeps secrets secure)
- KV storage for robot metadata
- Durable Object for persistent connections

## Quick Start

### Prerequisites

1. [Wrangler CLI](https://developers.cloudflare.com/workers/wrangler/install-and-update/) installed
2. Cloudflare account
3. Cloudflare Calls API credentials (App ID & Token)

### 1. Deploy Backend

```bash
cd cloud/workers/fleet-worker

# Install dependencies
npm install

# Configure secrets (production)
wrangler secret put CF_CALLS_APP_ID
# Enter your Cloudflare Calls App ID

wrangler secret put CF_CALLS_APP_TOKEN
# Enter your Cloudflare Calls API Token

# Deploy
wrangler deploy

# Note the worker URL (e.g., https://fleet-worker.YOUR-NAME.workers.dev)
```

**For local development:**
```bash
# Copy example env file
cp .dev.vars.example .dev.vars

# Edit .dev.vars with your credentials
nano .dev.vars

# Run locally
wrangler dev
```

### 2. Deploy Frontend

```bash
cd cloud/frontend

# Update worker URL in index.html (line ~296)
# Change: value="https://YOUR-WORKER-URL.workers.dev"

# Deploy to Cloudflare Pages
npm run deploy
```

### 3. Connect a Robot

Update your robot's fleet worker URL configuration to point to your deployed worker:
```bash
# On robot
FLEET_WORKER_URL=https://YOUR-WORKER-URL.workers.dev
```

## API Endpoints

### Backend Endpoints

**Robot Management:**
- `GET /robots` - List registered robots
- `POST /connect` - Signal robot connection
- `WebSocket /ws/robot` - Robot signaling
- `WebSocket /ws/operator?robotId=xxx` - ROSBridge proxy

**Cloudflare Calls API Proxy (New):**
- `POST /api/calls/sessions/new` - Create SFU session
- `POST /api/calls/sessions/:id/tracks/new` - Pull video track
- `PUT /api/calls/sessions/:id/renegotiate` - Renegotiate connection
- `POST /api/calls/sessions/:id/datachannels/new` - Create DataChannel

All proxy endpoints add authentication transparently - frontend doesn't handle secrets.

## Environment Variables

### Backend (Worker Secrets)

| Variable | Description | Required |
|----------|-------------|----------|
| `CF_CALLS_APP_ID` | Cloudflare Calls Application ID | Yes |
| `CF_CALLS_APP_TOKEN` | Cloudflare Calls API Token | Yes |

**Set in production:**
```bash
wrangler secret put CF_CALLS_APP_ID
wrangler secret put CF_CALLS_APP_TOKEN
```

**Set for local development:**
Create `.dev.vars` file:
```
CF_CALLS_APP_ID=your_app_id_here
CF_CALLS_APP_TOKEN=your_token_here
```

### Frontend

**No environment variables needed!** All configuration is done at runtime via the UI.

## Development Workflow

### Local Backend Development
```bash
cd cloud/workers/fleet-worker

# Ensure .dev.vars is configured
wrangler dev
# Worker available at http://localhost:8787
```

### Local Frontend Development
```bash
cd cloud/frontend

# Option 1: Wrangler pages dev
npm run dev

# Option 2: Any static file server
python -m http.server 8080

# Update worker URL in UI to: http://localhost:8787
```

### Testing

1. **Backend:**
   ```bash
   curl http://localhost:8787/robots
   ```

2. **Frontend:** Open browser, check console for errors

3. **End-to-end:** Connect robot → select in UI → connect → verify video

## Deployment Checklist

Before deploying to production:

- [ ] Backend secrets configured (`wrangler secret list`)
- [ ] Worker deployed (`wrangler deploy`)
- [ ] Worker URL updated in frontend
- [ ] Frontend deployed to Cloudflare Pages
- [ ] KV namespace created and configured
- [ ] No secrets visible in browser DevTools
- [ ] Robot connection tested
- [ ] Video streaming verified
- [ ] Controls functional
- [ ] ROSBridge working

## Connection Flow

See [frontend/README.md](./frontend/README.md) for detailed connection sequence diagrams.

**Summary:**
1. Frontend requests session creation from backend
2. Backend proxies to Cloudflare Calls API (adds auth)
3. Frontend sets up WebRTC with returned session ID
4. Frontend pulls robot's video track via backend proxy
5. Frontend registers DataChannel via backend proxy
6. Frontend signals robot via backend `/connect` endpoint
7. Connection established - video streams, controls work

## Troubleshooting

### "Cloudflare Calls credentials not configured"
**Fix:** Ensure secrets are set
```bash
wrangler secret put CF_CALLS_APP_ID
wrangler secret put CF_CALLS_APP_TOKEN
wrangler deploy
```

### "Failed to proxy Calls API request"
**Fix:** Check worker logs and verify credentials
```bash
wrangler tail
```

### "CORS errors"
**Fix:** Ensure worker is deployed with latest code
```bash
cd cloud/workers/fleet-worker
wrangler deploy
```

### "Robot not connected"
**Check:**
- Robot is running and connected to worker WebSocket
- Robot registration in worker logs
- KV namespace configured correctly

## Architecture Benefits

### Security
- Zero secrets exposed in browser
- Backend handles all authentication
- Encrypted WebRTC media (DTLS)
- Secure signaling through worker

### Scalability
- Globally distributed edge workers
- Cloudflare Calls SFU handles media routing
- KV storage for persistent state
- Durable Objects for WebSocket connections

### Future-Proof
- Clean API separation enables easy UI refactoring
- Can migrate to React/Vue/Svelte without changing backend
- Same backend can support mobile/desktop apps
- Business logic stays on backend

## Related Documentation

- [frontend/README.md](./frontend/README.md) - Frontend details & connection flow
- [workers/fleet-worker/README.md](./workers/fleet-worker/README.md) - Backend details
- [Cloudflare Workers Docs](https://developers.cloudflare.com/workers/)
- [Cloudflare Calls API](https://developers.cloudflare.com/calls/)

## License

See project root for license information.
