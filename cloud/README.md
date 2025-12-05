# Fleet Management Cloud Infrastructure

This directory contains the cloud-based components of the fleet management system.

## Structure

```
cloud/
├── workers/              # Cloudflare Workers (API, WebSocket proxy)
│   ├── api/             # API endpoint handlers
│   ├── websocket/       # WebSocket connection handlers
│   ├── durable-objects/ # Durable Object implementations
│   └── src/             # Main worker code
├── frontend/            # Minimal Angular frontend (for testing)
│   └── src/
│       └── app/         # App component
└── shared/              # Shared TypeScript types
```

**Note:** The frontend is intentionally minimal for testing backend functionality. A full-featured UI will be developed separately in Phase 4.

## Development Setup

### Prerequisites

- Node.js 18 or later
- npm or yarn
- Cloudflare account with Workers and Pages access
- Wrangler CLI (installed via npm)

### Workers Development

```bash
cd cloud/workers
npm install
npm run dev    # Start local development server
```

The Workers dev server will run on http://localhost:8787

### Frontend Development

```bash
cd cloud/frontend
npm install
npm start      # Start Angular dev server
```

The frontend will run on http://localhost:3000 and proxy API requests to Workers.

## Deployment

### Prerequisites

Set up GitHub Secrets:
- `CLOUDFLARE_API_TOKEN` - Cloudflare API token with Workers and Pages permissions
- `CLOUDFLARE_ACCOUNT_ID` - Your Cloudflare account ID

### Automatic Deployment

Push to main branch:
```bash
git add .
git commit -m "Deploy updates"
git push origin main
```

GitHub Actions will automatically:
1. Run tests and type checks
2. Build the frontend
3. Deploy Workers to production
4. Deploy frontend to Cloudflare Pages

### Manual Deployment

Workers:
```bash
cd cloud/workers
npm run deploy
```

Frontend:
```bash
cd cloud/frontend
npm run build
wrangler pages deploy dist/fleet-console --project-name=fleet-console
```

## Configuration

### Workers Configuration

Edit `cloud/workers/wrangler.toml`:
- Update `account_id` with your Cloudflare account ID
- Configure KV namespaces for robot registry
- Set up Durable Objects bindings
- Add environment-specific variables

### Secrets

Set secrets using Wrangler CLI:
```bash
cd cloud/workers
wrangler secret put CLOUDFLARE_CALLS_APP_ID
wrangler secret put CLOUDFLARE_CALLS_API_TOKEN
wrangler secret put JWT_SECRET
```

## API Endpoints

### Health Check
- `GET /health` - Returns worker health status

### Phase 1: Cloudflare Calls (Coming Soon)
- `POST /api/sessions/create` - Create SFU session
- `GET /api/sessions/:robotId` - Get session info
- `DELETE /api/sessions/:robotId` - Close session
- `GET /api/ice-servers` - Get TURN credentials

### Phase 2: Rosbridge Proxy (Coming Soon)
- `WS /ws/robot/:robotId/rosbridge` - Robot connection
- `WS /ws/client/:robotId/rosbridge` - Client connection

## Testing

Run all tests:
```bash
# Workers tests
cd cloud/workers
npm test

# Frontend build test
cd cloud/frontend
npm run build
```

## Monitoring

- Workers Analytics: https://dash.cloudflare.com/workers
- Pages Analytics: https://dash.cloudflare.com/pages
- Logs: Use `wrangler tail` for live logs

## Troubleshooting

### Workers not deploying
- Check `wrangler.toml` has correct account_id
- Verify API token has Workers permissions
- Run `wrangler whoami` to verify authentication

### Frontend build failures
- Clear node_modules and reinstall: `rm -rf node_modules package-lock.json && npm install`
- Check TypeScript errors: `npm run build`

### CORS issues in development
- Ensure Vite proxy is configured in `vite.config.ts`
- Check Workers CORS headers in `src/index.ts`

## Phase Progress

- [x] Phase 0: Foundation & Setup
- [ ] Phase 1: Cloudflare Calls Integration
- [ ] Phase 2: Rosbridge WebSocket Proxy
- [ ] Phase 3: Fleet Agent Integration
- [ ] Phase 4: React Fleet Console
- [ ] Phase 5: Production Hardening

## Resources

- [Cloudflare Workers Docs](https://developers.cloudflare.com/workers/)
- [Cloudflare Pages Docs](https://developers.cloudflare.com/pages/)
- [Wrangler CLI Docs](https://developers.cloudflare.com/workers/wrangler/)
- [Angular Docs](https://angular.dev/)
