# WebRTC TURN Configuration with Cloudflare

This document explains how to configure Cloudflare TURN servers for the WebRTC bridge.

## Overview

The WebRTC bridge now dynamically fetches TURN credentials from Cloudflare's TURN service. This provides:

- **Secure credentials**: Time-limited credentials generated on-demand
- **Automatic rotation**: Credentials expire and are automatically refreshed
- **No hardcoded secrets**: API tokens stored in environment variables
- **Fallback support**: Automatically falls back to public STUN servers if Cloudflare is unavailable

## Setup Instructions

### 1. Get Cloudflare TURN Credentials

1. Sign up for a Cloudflare account at https://dash.cloudflare.com/
2. Navigate to the TURN service: https://dash.cloudflare.com/calls
3. Create a new TURN key and note down:
   - **API Token** (Bearer token for authentication)
   - **TURN Key ID** (identifier for your TURN key)

### 2. Set Environment Variables

Set the following environment variables on your system:

```bash
export CLOUDFLARE_API_TOKEN="your_api_token_here"
export CLOUDFLARE_TURN_KEY_ID="your_turn_key_id_here"
```

For permanent configuration, add these to your `~/.bashrc` or `~/.bash_profile`:

```bash
echo 'export CLOUDFLARE_API_TOKEN="your_api_token_here"' >> ~/.bashrc
echo 'export CLOUDFLARE_TURN_KEY_ID="your_turn_key_id_here"' >> ~/.bashrc
source ~/.bashrc
```

### 3. Install Required Python Package

The Cloudflare integration requires the `requests` package:

```bash
pip install requests
```

Or add it to your `requirements.txt`:

```
requests>=2.31.0
```

## How It Works

### Backend (Python)

1. When the signaling server starts, it initializes a `CloudflareTURNProvider`
2. The provider reads credentials from environment variables
3. A new endpoint `/ice-servers` is exposed by the server
4. When requested, it calls the Cloudflare API to generate time-limited credentials
5. Credentials are cached for 24 hours (minus 5 minutes for safety)
6. If Cloudflare is unavailable, it falls back to public STUN servers

### Frontend (JavaScript)

1. When the user clicks "Connect", the frontend requests ICE servers from the backend
2. It calls `GET http://your-server:8080/ice-servers`
3. The backend returns credentials in the format:
   ```json
   {
     "iceServers": [
       {
         "urls": [
           "stun:stun.cloudflare.com:3478",
           "turn:turn.cloudflare.com:3478?transport=udp",
           "turn:turn.cloudflare.com:3478?transport=tcp",
           "turns:turn.cloudflare.com:5349?transport=tcp"
         ],
         "username": "generated_username",
         "credential": "generated_credential"
       }
     ]
   }
   ```
4. These credentials are used to establish the WebRTC connection

## Testing

### Test the Backend Endpoint

```bash
curl http://localhost:8080/ice-servers
```

Expected response (if configured):
```json
{
  "iceServers": [
    {
      "urls": [
        "stun:stun.cloudflare.com:3478",
        "turn:turn.cloudflare.com:3478?transport=udp",
        ...
      ],
      "username": "...",
      "credential": "..."
    }
  ]
}
```

Fallback response (if not configured):
```json
{
  "iceServers": [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"}
  ]
}
```

### Test with the Frontend

1. Start the backend server
2. Open the web interface
3. Click "Connect"
4. Check browser console - you should see:
   - "Using ICE servers from backend"
   - WebRTC connection logs showing TURN candidates

## Cloudflare API Details

The backend makes the following API call:

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ttl": 86400}' \
  https://rtc.live.cloudflare.com/v1/turn/keys/YOUR_TURN_KEY_ID/credentials/generate-ice-servers
```

Parameters:
- `ttl`: Time to live in seconds (default: 86400 = 24 hours)

## Troubleshooting

### "Using fallback STUN servers" message

**Cause**: Environment variables not set or Cloudflare API call failed

**Solution**:
1. Verify environment variables are set: `echo $CLOUDFLARE_API_TOKEN`
2. Check the API token has the correct permissions
3. Verify the TURN key ID is correct
4. Check network connectivity to Cloudflare API

### Credentials expire too quickly

**Cause**: TTL set too low

**Solution**: Adjust TTL when initializing `CloudflareTURNProvider`:

```python
self._turn_provider = CloudflareTURNProvider(
    ttl=86400,  # 24 hours
    logger=logger
)
```

### Connection fails even with TURN

**Cause**: Firewall blocking TURN traffic

**Solution**:
1. Ensure ports 3478 (UDP/TCP) and 5349 (TCP/TLS) are open
2. Test with different transport protocols
3. Check browser console for ICE connection failures

## Alternative: Using Without Cloudflare

If you don't want to use Cloudflare, you can:

1. Set up your own TURN server (coturn)
2. Modify `webrtc-config.js` to return static configuration
3. Comment out the backend API call in `app.js`

## Security Notes

- **Never commit API tokens to git**
- Use environment variables or secrets management
- Rotate API tokens periodically
- Set appropriate TTL for credentials (not too long)
- Consider using Cloudflare API token permissions to restrict access

## References

- [Cloudflare Calls Documentation](https://developers.cloudflare.com/calls/)
- [WebRTC ICE Documentation](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API/Protocols)
- [TURN Server Setup Guide](https://github.com/coturn/coturn)
