# Cloud Setup Instructions

## Phase 0 Complete - Next Steps

Phase 0 foundation setup is complete! Here's what to do next to get your development environment running.

## Prerequisites

1. **Cloudflare Account**
   - Sign up at https://dash.cloudflare.com if you haven't already
   - You mentioned you have Cloudflare Calls API access ✓

2. **Install Node.js**
   ```bash
   # Check if Node.js is installed
   node --version  # Should be v18 or later
   npm --version
   ```

3. **Install Dependencies**
   ```bash
   # Install Workers dependencies
   cd cloud/workers
   npm install

   # Install Frontend dependencies
   cd ../frontend
   npm install
   ```

## Cloudflare Configuration

### 1. Get Your Account ID

1. Log in to https://dash.cloudflare.com
2. Click on any domain (or go to Workers & Pages)
3. Your Account ID is shown on the right sidebar
4. Copy this ID

### 2. Update wrangler.toml

Edit `cloud/workers/wrangler.toml`:

```toml
# Replace with your actual account ID
account_id = "your-account-id-here"
```

### 3. Authenticate Wrangler

```bash
cd cloud/workers
npx wrangler login
```

This will open a browser to authenticate with Cloudflare.

### 4. Set Up Secrets

These will be needed in Phase 1, but you can set them up now:

```bash
cd cloud/workers

# Cloudflare Calls API credentials
npx wrangler secret put CLOUDFLARE_CALLS_APP_ID
# Enter your Calls App ID when prompted

npx wrangler secret put CLOUDFLARE_CALLS_API_TOKEN
# Enter your Calls API token when prompted

# JWT secret for authentication (generate a random string)
npx wrangler secret put JWT_SECRET
# Enter a long random string (e.g., openssl rand -base64 32)
```

## GitHub Configuration (for CI/CD)

### 1. Generate Cloudflare API Token

1. Go to https://dash.cloudflare.com/profile/api-tokens
2. Click "Create Token"
3. Use the "Edit Cloudflare Workers" template
4. Add these permissions:
   - Account > Workers Scripts > Edit
   - Account > Workers KV Storage > Edit
   - Account > Cloudflare Pages > Edit
5. Copy the generated token

### 2. Add GitHub Secrets

1. Go to your GitHub repository
2. Settings > Secrets and variables > Actions
3. Add these secrets:
   - `CLOUDFLARE_API_TOKEN` = (token from step 1)
   - `CLOUDFLARE_ACCOUNT_ID` = (your account ID)

## Test the Setup

### 1. Test Workers Locally

```bash
cd cloud/workers
npm run dev
```

You should see:
```
⛅️ wrangler 4.53.0
-------------------
⎔ Starting local server...
[wrangler:inf] Ready on http://localhost:8787
```

Test it:
```bash
curl http://localhost:8787/health
```

Expected response:
```json
{
  "status": "ok",
  "environment": "development",
  "timestamp": "2025-12-04T..."
}
```

### 2. Test Frontend Locally

```bash
cd cloud/frontend
npm start
```

You should see:
```
** Angular Live Development Server is listening on localhost:3000 **
```

Open http://localhost:3000 in your browser. You should see the minimal Fleet Dashboard.

### 3. Test Deployment

Deploy Workers to Cloudflare:
```bash
cd cloud/workers
npm run deploy
```

You should see:
```
Uploaded fleet-workers (x.xx sec)
Published fleet-workers (x.xx sec)
  https://fleet-workers.your-subdomain.workers.dev
```

Test the deployed worker:
```bash
curl https://fleet-workers.your-subdomain.workers.dev/health
```

## Troubleshooting

### "wrangler: command not found"

```bash
cd cloud/workers
npx wrangler --version
```

Or install globally:
```bash
npm install -g wrangler
```

### "You need to authenticate with Cloudflare"

```bash
cd cloud/workers
npx wrangler login
```

### Workers deployment fails

1. Check `account_id` in `wrangler.toml` is correct
2. Verify you're authenticated: `npx wrangler whoami`
3. Check API token has correct permissions

### Frontend won't start

```bash
cd cloud/frontend
rm -rf node_modules package-lock.json
npm install
npm run dev
```

## What's Next?

Once everything is working:

1. **Phase 1: Cloudflare Calls Integration** (Next)
   - Implement SFU session management API
   - Create robot-side SFU client
   - Update browser client for SFU connection

2. **Keep the plan updated**
   - Edit `FLEET_ARCHITECTURE_PLAN.md` as you progress
   - Check off completed tasks
   - Add notes about issues or decisions

## Quick Reference

| Command | Purpose |
|---------|---------|
| `cd cloud/workers && npm run dev` | Start Workers dev server |
| `cd cloud/frontend && npm start` | Start frontend dev server |
| `cd cloud/workers && npm run deploy` | Deploy Workers to production |
| `cd cloud/workers && npm run tail` | View live Worker logs |
| `npx wrangler whoami` | Check authentication status |

## Need Help?

- Workers docs: https://developers.cloudflare.com/workers/
- Wrangler docs: https://developers.cloudflare.com/workers/wrangler/
- Cloudflare Calls docs: https://developers.cloudflare.com/calls/
- Angular docs: https://angular.dev/

Happy building! 🚀
